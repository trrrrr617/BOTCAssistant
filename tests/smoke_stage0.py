"""Stage 0 end-to-end + bugfix regression tests."""
import asyncio
import sys
import os

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import socketio


def banner(text):
    print()
    print("=" * 60)
    print(text)
    print("=" * 60)


async def main():
    # ---- Test 1: ST creates room, players join, real-time sync ----
    sio_st = socketio.AsyncClient()
    sio_pl = socketio.AsyncClient()
    sio_pl2 = socketio.AsyncClient()
    st_events, pl_events, pl2_events = [], [], []

    @sio_st.on("room_created")
    def _st_created(d):
        st_events.append(("room_created", d))
        print(f"[ST] room_created code={d.get('room_code')} pid={d.get('player_id')}")

    @sio_st.on("st_player_list")
    def _st_list(d):
        st_events.append(("st_player_list", d))
        print(f"[ST] st_player_list: {[p['name'] for p in d.get('players',[])]}")

    @sio_pl.on("joined")
    def _pl_joined(d):
        pl_events.append(("joined", d))
        print(f"[PL] joined code={d.get('room_code')}")

    @sio_pl.on("player_list")
    def _pl_list(d):
        pl_events.append(("player_list", d))
        print(f"[PL] player_list: {[p['name'] for p in d.get('players',[])]}")

    @sio_pl2.on("joined")
    def _pl2_joined(d):
        pl2_events.append(("joined", d))
        print(f"[PL2] joined")

    @sio_pl2.on("player_list")
    def _pl2_list(d):
        pl2_events.append(("player_list", d))
        print(f"[PL2] player_list: {[p['name'] for p in d.get('players',[])]}")

    # 1. ST creates room
    await sio_st.connect("http://localhost:5000", transports=["websocket"])
    await sio_st.emit("create_room", {"name": "ST_tr"})
    await asyncio.sleep(0.5)
    st_evt = next((e for e in st_events if e[0] == "room_created"), None)
    assert st_evt, "ST did not receive room_created"
    room_code = st_evt[1]["room_code"]
    print(f"\n[PASS] 1.1: ST created room {room_code}")

    # 2. PlayerA joins
    await sio_pl.connect("http://localhost:5000", transports=["websocket"])
    await sio_pl.emit("join_room", {"room_code": room_code, "name": "PlayerA"})
    await asyncio.sleep(0.5)
    pl_evt = next((e for e in pl_events if e[0] == "joined"), None)
    assert pl_evt, "PlayerA did not receive joined"
    pl_pid = pl_evt[1]["player_id"]
    pl_token = pl_evt[1].get("player_token", "")  # 玩家 token(防作弊)
    print(f"[PASS] 1.2: PlayerA joined, pid={pl_pid}")

    # 3. PlayerB joins
    await sio_pl2.connect("http://localhost:5000", transports=["websocket"])
    await sio_pl2.emit("join_room", {"room_code": room_code, "name": "PlayerB"})
    await asyncio.sleep(0.5)
    print(f"[PASS] 1.3: PlayerB joined")

    # 4. ST sees all 3
    latest_st = [e for e in st_events if e[0] == "st_player_list"]
    names = [p["name"] for p in latest_st[-1][1]["players"]]
    assert "PlayerA" in names and "PlayerB" in names, f"ST sees: {names}"
    print(f"[PASS] 1.4: ST sees {names}")

    # 5. ST sees only 1 PlayerA, not 2
    pa_count = sum(1 for p in latest_st[-1][1]["players"] if p["name"] == "PlayerA")
    assert pa_count == 1, f"PlayerA appears {pa_count} times (should be 1)"
    print(f"[PASS] 1.5: PlayerA appears exactly once (no duplicate)")

    # 6. Bug regression: same sid joining again does NOT create duplicate
    pl_events.clear()
    await sio_pl.emit("join_room", {"room_code": room_code, "name": "PlayerA"})
    await asyncio.sleep(0.5)
    latest = [e for e in pl_events if e[0] == "joined"]
    assert latest, "Second join should still return joined event (as reconnect)"
    pa_count = sum(1 for p in latest_st[-1][1]["players"] if p["name"] == "PlayerA")
    assert pa_count == 1, f"After re-join, PlayerA appears {pa_count} times (should still be 1)"
    print(f"[PASS] 1.6: Re-join from same sid does NOT create duplicate")

    # 7. Bug regression: PlayerA disconnect + reconnect (simulating page refresh)
    print(f"\n[Test 2] Simulating page refresh for PlayerA")
    pl_events.clear()
    await sio_pl.disconnect()
    await asyncio.sleep(0.5)
    # ST should see PlayerA as offline
    latest_st = [e for e in st_events if e[0] == "st_player_list"]
    pa = next((p for p in latest_st[-1][1]["players"] if p["name"] == "PlayerA"), None)
    assert pa is not None, "PlayerA should still be in the room (just offline)"
    assert pa.get("connected") == False, f"PlayerA should be offline, got: {pa}"
    print(f"[PASS] 2.1: After disconnect, ST sees PlayerA as offline (still in list)")

    # Reconnect with new connection
    sio_pl2_again = socketio.AsyncClient()
    pl3_events = []
    @sio_pl2_again.on("joined")
    def _pl3_joined(d):
        pl3_events.append(("joined", d))
        print(f"[PL-RECONNECT] joined, reconnected={d.get('reconnected')}")

    @sio_pl2_again.on("player_list")
    def _pl3_list(d):
        pl3_events.append(("player_list", d))

    await sio_pl2_again.connect("http://localhost:5000", transports=["websocket"])
    await sio_pl2_again.emit("reconnect_room", {"room_code": room_code, "player_id": pl_pid, "player_token": pl_token})
    await asyncio.sleep(0.6)
    pl3_evt = next((e for e in pl3_events if e[0] == "joined"), None)
    assert pl3_evt, "Reconnect failed"
    assert pl3_evt[1].get("reconnected") == True, "Should have reconnected=True flag"
    print(f"[PASS] 2.2: Reconnect with same player_id succeeds, reconnected=True")

    # 8. After reconnect, ST sees PlayerA back online
    await asyncio.sleep(0.3)
    latest_st = [e for e in st_events if e[0] == "st_player_list"]
    pa = next((p for p in latest_st[-1][1]["players"] if p["name"] == "PlayerA"), None)
    assert pa is not None, "PlayerA should be in list"
    assert pa.get("connected") != False, f"PlayerA should be online again, got: {pa}"
    pa_count = sum(1 for p in latest_st[-1][1]["players"] if p["name"] == "PlayerA")
    assert pa_count == 1, f"PlayerA should still appear exactly once, got {pa_count}"
    print(f"[PASS] 2.3: ST sees PlayerA back online, still 1 instance")

    # 9. Bug regression: same-name reconnect (lobby→player auto-join)
    print(f"\n[Test 3] Simulating lobby redirect to player page (same name)")
    pl4_events = []
    sio_pl3 = socketio.AsyncClient()
    @sio_pl3.on("joined")
    def _pl3_joined2(d):
        pl4_events.append(("joined", d))
        print(f"[PL3] joined, reconnected={d.get('reconnected')}")

    @sio_pl3.on("player_list")
    def _pl3_list2(d):
        pl4_events.append(("player_list", d))

    await sio_pl3.connect("http://localhost:5000", transports=["websocket"])
    # Same scenario: user types "PlayerC" in lobby, server creates, redirects to /p/X?name=PlayerC,
    # player page emits join_room again
    await sio_pl3.emit("join_room", {"room_code": room_code, "name": "PlayerC"})
    await asyncio.sleep(0.4)
    pl3_first_evt = pl4_events[0]  # first joined
    pl3_pid = pl3_first_evt[1]["player_id"]
    print(f"[PASS] 3.1: PlayerC first join, pid={pl3_pid}")

    # Now player page reloads (simulating redirect), same sid, same name → should NOT create new player
    pl4_events.clear()
    await sio_pl3.emit("join_room", {"room_code": room_code, "name": "PlayerC"})
    await asyncio.sleep(0.4)
    pl3_second_evt = pl4_events[0]
    pl3_pid2 = pl3_second_evt[1]["player_id"]
    assert pl3_pid == pl3_pid2, f"Same sid re-join should return same pid, got {pl3_pid} vs {pl3_pid2}"
    print(f"[PASS] 3.2: Lobby→player redirect does NOT create duplicate, same pid={pl3_pid}")

    # 10. Verify ST sees only 1 PlayerC
    await asyncio.sleep(0.2)
    latest_st = [e for e in st_events if e[0] == "st_player_list"]
    pc_count = sum(1 for p in latest_st[-1][1]["players"] if p["name"] == "PlayerC")
    assert pc_count == 1, f"PlayerC appears {pc_count} times (should be 1)"
    print(f"[PASS] 3.3: ST sees exactly 1 PlayerC (no duplicate)")

    banner("ALL TESTS PASSED: 11/11")
    banner(f"Room code: {room_code}")

    await sio_pl3.disconnect()
    await sio_pl2_again.disconnect()
    await sio_pl2.disconnect()
    await sio_st.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
