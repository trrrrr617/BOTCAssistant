"""Stage 1 bugfix regression: ST refresh recovers full state + log."""
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
    sio_st = socketio.AsyncClient()
    players = [socketio.AsyncClient() for _ in range(5)]
    p_events = [[] for _ in range(5)]
    st_events = []

    @sio_st.on("room_created")
    def _(d): st_events.append(("room_created", d))
    @sio_st.on("st_state_update")
    def _(d): st_events.append(("st_state_update", d))
    @sio_st.on("st_player_list")
    def _(d): st_events.append(("st_player_list", d))
    @sio_st.on("error")
    def _(d): st_events.append(("error", d))

    for i, sio in enumerate(players):
        sio.on("joined", lambda d, i=i: p_events[i].append(("joined", d)))
        sio.on("role_assigned", lambda d, i=i: p_events[i].append(("role_assigned", d)))
        sio.on("state_update", lambda d, i=i: p_events[i].append(("state_update", d)))

    # 1. ST creates room
    await sio_st.connect("http://localhost:5000", transports=["websocket"])
    await sio_st.emit("create_room", {"name": "ST_test"})
    await asyncio.sleep(0.3)
    st_evt = next((e for e in st_events if e[0] == "room_created"), None)
    assert st_evt
    room_code = st_evt[1]["room_code"]
    st_pid = st_evt[1]["player_id"]
    st_token = st_evt[1].get("st_token")  # ← stage 4+ 鉴权用
    print(f"[PASS] ST created room {room_code} (token={st_token!r})")

    # 2. 5 players join (minimum to start game)
    p_ids = []
    for i, sio in enumerate(players):
        await sio.connect("http://localhost:5000", transports=["websocket"])
        await sio.emit("join_room", {"room_code": room_code, "name": f"p{i+1}"})
        await asyncio.sleep(0.15)
        j = next((e for e in p_events[i] if e[0] == "joined"), None)
        assert j, f"p{i+1} didn't join"
        p_ids.append(j[1]["player_id"])
    print(f"[PASS] 5 players joined")

    # 3. ST starts game
    st_events.clear()
    await sio_st.emit("start_game", {})
    await asyncio.sleep(0.7)
    st_state = [e for e in st_events if e[0] == "st_state_update"]
    if not st_state:
        print(f"  DEBUG st_events after start_game: {[(e[0], str(e[1])[:60]) for e in st_events]}")
    assert st_state, "no st_state_update after start_game"
    state = st_state[-1][1]
    assert state["phase"] == "day"
    log_after_start = state.get("log", [])
    assert any("游戏开始" in e["text"] for e in log_after_start), f"missing game_start log: {log_after_start}"
    print(f"[PASS] Game started, log has {len(log_after_start)} entries")

    # 4. p1 nominates p2, votes pass, end nomination phase
    p2_id = p_ids[1]  # 提名第 2 个玩家
    await players[0].emit("nominate", {"target_id": p2_id})
    await asyncio.sleep(0.3)
    # 5 个玩家投票(4 yes / 1 no)
    # 先获取 nomination_id
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    nom_id = state["current_nominations"][0]["id"]
    votes = [True, False, True, True, True]
    for i, v in enumerate(votes):
        await players[i].emit("vote", {"value": v, "nomination_id": nom_id})
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.3)
    st_events.clear()
    await sio_st.emit("end_nomination_phase", {})
    await asyncio.sleep(0.4)
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    log_after_close = state.get("log", [])
    assert any("提名" in e["text"] for e in log_after_close)
    assert any("处决" in e["text"] for e in log_after_close)
    print(f"[PASS] Nomination closed, log has {len(log_after_close)} entries")

    # 5. ST simulates page refresh: disconnect + reconnect with new connection
    print("\n[Test refresh] ST disconnects & reconnects...")
    st_events.clear()
    st_sid_before = sio_st.sid
    await sio_st.disconnect()
    await asyncio.sleep(0.3)

    sio_st2 = socketio.AsyncClient()
    st2_events = []
    @sio_st2.on("room_created")
    def _(d): st2_events.append(("room_created", d))
    @sio_st2.on("st_state_update")
    def _(d): st2_events.append(("st_state_update", d))

    await sio_st2.connect("http://localhost:5000", transports=["websocket"])
    await sio_st2.emit("reconnect_room", {"room_code": room_code, "player_id": st_pid, "st_token": st_token})
    await asyncio.sleep(0.4)

    st2_evt = next((e for e in st2_events if e[0] == "room_created"), None)
    assert st2_evt and st2_evt[1].get("reconnected") == True, f"reconnect failed: {st2_evt}"
    print(f"[PASS] ST reconnected, new sid={sio_st2.sid} (was {st_sid_before})")

    st2_state = next((e for e in st2_events if e[0] == "st_state_update"), None)
    assert st2_state, "ST didn't get st_state_update after reconnect"
    state = st2_state[1]
    # 注意:phase 可能是 day(游戏未结束)/ ended(已分胜负)—— 取决于本局实际结果
    # 关键验证:刷新后能正确恢复当前阶段(而不是回到 lobby)
    assert state["phase"] in ("day", "night", "ended"), f"unexpected phase: {state['phase']}"
    log_after_refresh = state.get("log", [])
    # 日志必须包含历史所有条目(这是修复的核心点)
    expected_kinds = {"game_start", "nomination_start", "execution"}
    actual_kinds = {e["kind"] for e in log_after_refresh}
    missing = expected_kinds - actual_kinds
    assert not missing, f"log missing kinds: {missing} (got {actual_kinds})"
    print(f"[PASS] ST refresh recovers phase={state['phase']}, log has {len(log_after_refresh)} entries (kinds: {actual_kinds})")

    # 6. ST 刷新后仍可操作(若游戏已结束,改为验证 game_over 信息)
    if state["phase"] == "ended":
        assert state.get("winner"), "ended state should have winner"
        print(f"[PASS] ST refresh recovered ended state: winner={state['winner']} · {state.get('win_reason', '')}")
    else:
        st2_events.clear()
        await sio_st2.emit("end_day", {})
        await asyncio.sleep(0.4)
        new_state = next((e for e in st2_events if e[0] == "st_state_update"), None)
        assert new_state, "ST couldn't end_day after refresh"
        assert new_state[1]["phase"] == "night", f"expected night, got {new_state[1]['phase']}"
        assert any("夜幕" in e["text"] for e in new_state[1]["log"]), "log should have night_start entry"
        print(f"[PASS] ST can still control after refresh (end_day -> night, log appended)")

    banner("STAGE 1 BUGFIX: ALL CHECKS PASSED")
    banner(f"Room: {room_code} · Log entries recovered: {len(log_after_refresh)}")

    try:
        await sio_st2.disconnect()
    except Exception:
        pass
    for sio in players:
        try:
            await sio.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
