"""Bug 修复回归测试:

1. 玩家刷新后必须收到 role_assigned(否则「你的身份」栏无法渲染)
2. st_change_role 必须在被变更玩家的 private_log 中出现
   且不泄露给其他玩家(不在 _PUBLIC_LOG_KINDS 中)
"""
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


def _make_clients(n_players=5):
    sio_st = socketio.AsyncClient()
    players = [socketio.AsyncClient() for _ in range(n_players)]
    st_events = []
    p_events = [[] for _ in range(n_players)]

    @sio_st.on("room_created")
    def _(d): st_events.append(("room_created", d))
    @sio_st.on("st_state_update")
    def _(d): st_events.append(("st_state_update", d))
    @sio_st.on("error")
    def _(d): st_events.append(("error", d))

    for i, sio in enumerate(players):
        sio.on("joined", lambda d, i=i: p_events[i].append(("joined", d)))
        sio.on("role_assigned", lambda d, i=i: p_events[i].append(("role_assigned", d)))
        sio.on("state_update", lambda d, i=i: p_events[i].append(("state_update", d)))
        sio.on("player_state", lambda d, i=i: p_events[i].append(("player_state", d)))
        sio.on("error", lambda d, i=i: p_events[i].append(("error", d)))

    return sio_st, players, st_events, p_events


async def _setup_room(n_players=5):
    sio_st, players, st_events, p_events = _make_clients(n_players)
    await sio_st.connect("http://localhost:5000", transports=["websocket"])
    await sio_st.emit("create_room", {"name": "ST_test"})
    await asyncio.sleep(0.3)
    rc = next((e for e in st_events if e[0] == "room_created"), None)
    assert rc, "ST didn't get room_created"
    room_code = rc[1]["room_code"]
    p_ids = []
    p_tokens = []
    for i, sio in enumerate(players):
        await sio.connect("http://localhost:5000", transports=["websocket"])
        await sio.emit("join_room", {"room_code": room_code, "name": f"p{i+1}"})
        await asyncio.sleep(0.15)
        j = next((e for e in p_events[i] if e[0] == "joined"), None)
        assert j, f"p{i+1} didn't join"
        p_ids.append(j[1]["player_id"])
        p_tokens.append(j[1].get("player_token", ""))
    await sio_st.emit("start_game", {})
    await asyncio.sleep(0.4)
    return sio_st, players, st_events, p_events, room_code, p_ids, p_tokens


async def _disconnect_all(sio_st, players):
    for sio in players:
        try: await sio.disconnect()
        except Exception: pass
    try: await sio_st.disconnect()
    except Exception: pass


async def scenario_role_after_reconnect():
    """Bug 1 修复:玩家刷新(reconnect_room)后必须收到 role_assigned。"""
    banner("Bug 1: player reconnect re-sends role_assigned")
    sio_st, players, st_events, p_events, room_code, p_ids, p_tokens = await _setup_room(5)

    # 第一轮:确认 5 个玩家都收到了 role_assigned
    first_round = {}
    for i, p_ev in enumerate(p_events):
        ra = [e for e in p_ev if e[0] == "role_assigned"]
        assert ra, f"p{i+1} should have role_assigned on initial join"
        first_round[p_ids[i]] = ra[-1][1]
    print(f"[setup] 5 players received initial role_assigned")

    # 模拟刷新:p1 断开再重连
    p1_id = p_ids[0]
    p1_token = p_tokens[0]
    p1 = players[0]
    p_events[0].clear()  # 清空事件
    await p1.disconnect()
    await asyncio.sleep(0.2)
    p1_new = socketio.AsyncClient()
    p1_events_new = []
    p1_new.on("joined", lambda d: p1_events_new.append(("joined", d)))
    p1_new.on("role_assigned", lambda d: p1_events_new.append(("role_assigned", d)))
    p1_new.on("state_update", lambda d: p1_events_new.append(("state_update", d)))
    p1_new.on("error", lambda d: p1_events_new.append(("error", d)))
    await p1_new.connect("http://localhost:5000", transports=["websocket"])
    await p1_new.emit("reconnect_room", {"room_code": room_code, "player_id": p1_id, "player_token": p1_token})
    await asyncio.sleep(0.5)

    # 验证:p1 重连后收到 joined 和 role_assigned
    j = next((e for e in p1_events_new if e[0] == "joined"), None)
    assert j and j[1].get("reconnected") is True, f"p1 should reconnect; got {p1_events_new}"
    ra = next((e for e in p1_events_new if e[0] == "role_assigned"), None)
    assert ra, f"p1 reconnect should trigger role_assigned; got events {[e[0] for e in p1_events_new]}"
    assert ra[1]["true_role"] == first_round[p1_id]["true_role"], \
        f"role should be preserved across reconnect; got {ra[1]['true_role']} vs {first_round[p1_id]['true_role']}"
    print(f"[PASS] p1 reconnected and received role_assigned: role={ra[1]['true_role']}")

    try: await p1_new.disconnect()
    except Exception: pass
    await _disconnect_all(sio_st, players[1:])
    print("[OK] Bug 1 scenario passed.")


async def scenario_change_role_in_private_log():
    """Bug 2 修复:st_change_role 必须在被变更玩家 private_log 中出现,且不泄露。"""
    banner("Bug 2: st_change_role logged to affected player's private_log")
    sio_st, players, st_events, p_events, room_code, p_ids, _ = await _setup_room(5)

    # 等第一轮 state_update 触发 player_state 推送
    await asyncio.sleep(0.2)

    target_idx = 0  # p1
    other_idx = 1   # p2(应看不到日志)
    target_id = p_ids[target_idx]

    # ST 改 p1 的身份
    p_events[target_idx].clear()
    p_events[other_idx].clear()
    await sio_st.emit("st_change_role", {"player_id": target_id, "new_role": "poisoner"})
    await asyncio.sleep(0.4)

    # 1. 被变更玩家(p1)应收到 role_assigned 与 player_state(private_log 应包含 st_change_role)
    target_player_state = [e for e in p_events[target_idx] if e[0] == "player_state"]
    assert target_player_state, "p1 should receive player_state after change"
    last_ps = target_player_state[-1][1]
    private_log = last_ps.get("private_log", [])
    change_entries = [e for e in private_log if e.get("kind") == "st_change_role"]
    assert change_entries, \
        f"p1's private_log should contain st_change_role entry; got kinds {[e.get('kind') for e in private_log]}"
    print(f"[PASS] p1 private_log contains st_change_role: '{change_entries[-1]['text']}'")

    # 2. ST 看到完整 state.log(含 st_change_role)
    st_state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    st_log_kinds = [e["kind"] for e in st_state["log"]]
    assert "st_change_role" in st_log_kinds, f"ST state.log should include st_change_role; got {st_log_kinds}"
    print(f"[PASS] ST state.log includes st_change_role")

    # 3. 其它玩家(p2)的 filtered_log 应不含 st_change_role
    other_player_state = [e for e in p_events[other_idx] if e[0] == "player_state"]
    assert other_player_state, "p2 should receive player_state"
    other_ps = other_player_state[-1][1]
    other_filtered_kinds = [e.get("kind") for e in other_ps.get("filtered_log", [])]
    assert "st_change_role" not in other_filtered_kinds, \
        f"p2 filtered_log should NOT contain st_change_role (info leak); got {other_filtered_kinds}"
    other_private_kinds = [e.get("kind") for e in other_ps.get("private_log", [])]
    assert "st_change_role" not in other_private_kinds, \
        f"p2 private_log should NOT contain p1's st_change_role; got {other_private_kinds}"
    print(f"[PASS] p2 (other player) does not see role change log (no leak)")

    # 4. ST state 中被变更玩家应显示 poisoner
    target_after = next((p for p in st_state["players"] if p["id"] == target_id), None)
    assert target_after is not None
    assert target_after["true_role"] == "poisoner", f"p1 true_role should be poisoner, got {target_after['true_role']}"
    print(f"[PASS] ST sees p1.true_role = poisoner")

    await _disconnect_all(sio_st, players)
    print("[OK] Bug 2 scenario passed.")


async def main():
    await scenario_role_after_reconnect()
    await scenario_change_role_in_private_log()
    banner("BUG REGRESSIONS: ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())