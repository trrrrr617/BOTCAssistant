"""Stage 2 smoke: 关闭房间 + 游戏结束后重新开始。

测试场景 A:close_room
  1. ST 创建房间,5 玩家加入
  2. ST 强制结束游戏 → phase=ended
  3. ST 触发 close_room
  4. 验证:所有玩家收到 room_closed
  5. 验证:房间对象已被销毁(后续 join_room 返回 ROOM_NOT_FOUND)

测试场景 B:reset_game
  1. ST 创建房间,5 玩家加入
  2. ST 强制结束游戏 → phase=ended
  3. ST 触发 reset_game
  4. 验证:phase=day,day=1,所有玩家 alive
  5. 验证:每个玩家收到 role_assigned(true_role 重新分配)
  6. 验证:之前的真名/座位保留
  7. 验证:投票/提名/批注 全部清空
  8. 验证:在非 ENDED 阶段触发 reset_game 应失败

测试场景 C:非说书人触发 close_room 应被拒绝。
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


BASE_URL = os.getenv("BOTC_TEST_URL", "http://localhost:5000")


def banner(text):
    print()
    print("=" * 60)
    print(text)
    print("=" * 60)


def _make_clients(n_players=5):
    """返回 (sio_st, players, st_events, p_events)。事件在 emit 前注册。"""
    sio_st = socketio.AsyncClient()
    players = [socketio.AsyncClient() for _ in range(n_players)]
    st_events = []
    p_events = [[] for _ in range(n_players)]

    @sio_st.on("room_created")
    def _(d): st_events.append(("room_created", d))
    @sio_st.on("st_state_update")
    def _(d): st_events.append(("st_state_update", d))
    @sio_st.on("st_player_list")
    def _(d): st_events.append(("st_player_list", d))
    @sio_st.on("game_over")
    def _(d): st_events.append(("game_over", d))
    @sio_st.on("game_reset")
    def _(d): st_events.append(("game_reset", d))
    @sio_st.on("room_closed")
    def _(d): st_events.append(("room_closed", d))
    @sio_st.on("room_closed_ack")
    def _(d): st_events.append(("room_closed_ack", d))
    @sio_st.on("error")
    def _(d): st_events.append(("error", d))

    for i, sio in enumerate(players):
        sio.on("joined", lambda d, i=i: p_events[i].append(("joined", d)))
        sio.on("role_assigned", lambda d, i=i: p_events[i].append(("role_assigned", d)))
        sio.on("state_update", lambda d, i=i: p_events[i].append(("state_update", d)))
        sio.on("room_closed", lambda d, i=i: p_events[i].append(("room_closed", d)))
        sio.on("game_reset", lambda d, i=i: p_events[i].append(("game_reset", d)))
        sio.on("error", lambda d, i=i: p_events[i].append(("error", d)))

    return sio_st, players, st_events, p_events


async def _setup_room(n_players=5):
    """完整建立房间并启动游戏。返回 (sio_st, players, st_events, p_events, room_code, p_ids)。"""
    sio_st, players, st_events, p_events = _make_clients(n_players)
    await sio_st.connect(BASE_URL, transports=["websocket"])
    await sio_st.emit("create_room", {"name": "ST_test"})
    await asyncio.sleep(0.3)
    rc = next((e for e in st_events if e[0] == "room_created"), None)
    assert rc, "ST didn't get room_created"
    room_code = rc[1]["room_code"]
    p_ids = []
    for i, sio in enumerate(players):
        await sio.connect(BASE_URL, transports=["websocket"])
        await sio.emit("join_room", {"room_code": room_code, "name": f"p{i+1}"})
        await asyncio.sleep(0.15)
        j = next((e for e in p_events[i] if e[0] == "joined"), None)
        assert j, f"p{i+1} didn't join"
        p_ids.append(j[1]["player_id"])
    # 录入板子(stage 4 之后 start_game 强依赖 state.script)
    # 注:这里 import 放在函数体内,避免模块顶层导入破坏 eventlet monkey_patch 计数
    import sys as _sys
    _sys.path.insert(0, ".")
    from server.engine.script import make_legacy_compat_script as _mlcs
    script_dict = _mlcs().model_dump(mode="json")
    await sio_st.emit("set_script", {"script": script_dict})
    await asyncio.sleep(0.2)
    # 开局
    await sio_st.emit("start_game", {})
    await asyncio.sleep(0.4)
    return sio_st, players, st_events, p_events, room_code, p_ids


async def _disconnect_all(sio_st, players):
    for sio in players:
        try: await sio.disconnect()
        except Exception: pass
    try: await sio_st.disconnect()
    except Exception: pass


async def scenario_close_room():
    banner("Scenario A: close_room")
    sio_st, players, st_events, p_events, room_code, p_ids = await _setup_room(5)
    print(f"[setup] Room {room_code} with 5 players")

    # 1. 强制结束游戏
    st_events.clear()
    await sio_st.emit("end_game", {"reason": "测试"})
    await asyncio.sleep(0.4)
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    assert state["phase"] == "ended", f"phase should be ended, got {state['phase']}"
    assert state["winner"] == "manual", f"winner should be manual, got {state['winner']}"
    print(f"[PASS] end_game: phase=ended, winner=manual")

    # 2. ST 触发 close_room
    st_events.clear()
    for p_ev in p_events: p_ev.clear()
    await sio_st.emit("close_room", {"reason": "测试关闭"})
    await asyncio.sleep(0.5)

    # 3. 验证 ST 收到 room_closed_ack
    acks = [e for e in st_events if e[0] == "room_closed_ack"]
    assert acks, "ST should receive room_closed_ack"
    print(f"[PASS] ST received room_closed_ack: {acks[0][1]}")

    # 4. 验证 ST 也收到 room_closed (广播)
    closed_st = [e for e in st_events if e[0] == "room_closed"]
    assert closed_st, "ST should receive room_closed broadcast"
    print(f"[PASS] ST received room_closed broadcast: {closed_st[0][1]}")

    # 5. 验证每个玩家收到 room_closed
    for i, p_ev in enumerate(p_events):
        rc = [e for e in p_ev if e[0] == "room_closed"]
        assert rc, f"p{i+1} should receive room_closed"
        print(f"[PASS] p{i+1} received room_closed: {rc[-1][1]}")

    # 6. 验证房间已被销毁:尝试 join 应返回 ROOM_NOT_FOUND
    new_player = socketio.AsyncClient()
    new_player_events = []
    new_player.on("error", lambda d: new_player_events.append(("error", d)))
    new_player.on("joined", lambda d: new_player_events.append(("joined", d)))
    await new_player.connect(BASE_URL, transports=["websocket"])
    await new_player.emit("join_room", {"room_code": room_code, "name": "ghost"})
    await asyncio.sleep(0.3)
    err = [e for e in new_player_events if e[0] == "error" and e[1].get("code") == "ROOM_NOT_FOUND"]
    assert err, f"Joining destroyed room should error; got {new_player_events}"
    print(f"[PASS] Room destroyed: new join returns ROOM_NOT_FOUND")
    try: await new_player.disconnect()
    except Exception: pass

    await _disconnect_all(sio_st, players)
    print("[OK] Scenario A passed.")


async def scenario_reset_game():
    banner("Scenario B: reset_game")
    sio_st, players, st_events, p_events, room_code, p_ids = await _setup_room(5)
    print(f"[setup] Room {room_code} with 5 players")

    # 抓取第一轮的角色,以便后续比对「不同人可能拿到不同身份」
    first_roles = {}
    for i, p_ev in enumerate(p_events):
        ra = next((e for e in p_ev if e[0] == "role_assigned"), None)
        assert ra, f"p{i+1} should have received role_assigned in round 1"
        first_roles[p_ids[i]] = ra[1]["true_role"]
    print(f"[info] Round 1 roles: {first_roles}")

    # 1. 强制结束游戏
    st_events.clear()
    await sio_st.emit("end_game", {"reason": "测试"})
    await asyncio.sleep(0.4)
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    assert state["phase"] == "ended"
    print(f"[PASS] end_game: phase=ended")

    # 2. ST 触发 reset_game
    st_events.clear()
    for p_ev in p_events: p_ev.clear()
    await sio_st.emit("reset_game", {})
    await asyncio.sleep(0.6)

    # 3. ST 收到 game_reset
    gr = [e for e in st_events if e[0] == "game_reset"]
    assert gr, f"ST should receive game_reset; got st_events={[e[0] for e in st_events]}"
    assert gr[-1][1]["day"] == 0, f"new day should be 0 (game starts at first_night), got {gr[-1][1]['day']}"
    assert gr[-1][1]["night"] == 0, f"new night should be 0, got {gr[-1][1]['night']}"
    print(f"[PASS] ST received game_reset: {gr[-1][1]}")

    # 4. ST 最新 state:phase=first_night(游戏从首夜开始),day=0, players 全 alive
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    assert state["phase"] == "first_night", f"phase should be first_night after reset, got {state['phase']}"
    assert state["day"] == 0, f"day should be 0, got {state['day']}"
    assert state["night"] == 0, f"night should be 0, got {state['night']}"
    assert state["winner"] is None, f"winner should be cleared, got {state['winner']}"
    assert state["win_reason"] == "", f"win_reason should be cleared"
    assert state["current_nominations"] == [], "current_nominations should be cleared"
    for p in state["players"]:
        if p["is_storyteller"]: continue
        assert p["status"] == "alive", f"{p['name']} should be alive, got {p['status']}"
        assert p["true_role"] is not None, f"{p['name']} should have new true_role"
    print(f"[PASS] State after reset: phase=first_night day=0 night=0 winner=None all alive")

    # 5. 每个玩家收到 game_reset + 新的 role_assigned
    for i, p_ev in enumerate(p_events):
        gr_p = [e for e in p_ev if e[0] == "game_reset"]
        ra_p = [e for e in p_ev if e[0] == "role_assigned"]
        assert gr_p, f"p{i+1} should receive game_reset"
        assert ra_p, f"p{i+1} should receive new role_assigned"
        new_role = ra_p[-1][1]["true_role"]
        assert new_role, f"p{i+1} new role should be non-empty"
    print(f"[PASS] All players received game_reset + role_assigned")

    # 6. 玩家座位/名字保留(从 state.players 中比对)
    state_after = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    for p_id in p_ids:
        new_p = next((p for p in state_after["players"] if p["id"] == p_id), None)
        assert new_p is not None, f"player {p_id} should still exist"
    print(f"[PASS] Player ids preserved across reset")

    # 7. 提名/批注 全部清空
    assert state_after["log"] is not None and len(state_after["log"]) >= 1, "should have at least the game_start log"
    last_log = state_after["log"][-1]
    assert last_log["kind"] == "game_start", f"latest log should be game_start, got {last_log}"
    # 各玩家的 st_notes 已清空(玩家自己没设过,但应该为空列表)
    for p in state_after["players"]:
        if p["is_storyteller"]: continue
        assert p.get("st_notes", []) == [], f"{p['name']} st_notes should be cleared"
        assert p["is_poisoned"] == False
        assert p["is_drunk"] == False
    print(f"[PASS] Player notes / status flags all cleared")

    # 8. 在非 ENDED 阶段触发 reset_game 应失败(此时是 first_night)
    st_events.clear()
    await sio_st.emit("reset_game", {})
    await asyncio.sleep(0.4)
    errs = [e for e in st_events if e[0] == "error" and e[1].get("code") == "WRONG_PHASE"]
    assert errs, f"reset_game in non-ended phase should error with WRONG_PHASE; got {[e[1] for e in st_events if e[0] == 'error']}"
    print(f"[PASS] reset_game rejected in non-ended phase: {errs[-1][1]}")

    await _disconnect_all(sio_st, players)
    print("[OK] Scenario B passed.")


async def scenario_close_room_no_st_privilege():
    """额外:非说书人触发 close_room 应被拒绝。"""
    banner("Scenario C: non-ST close_room should fail")
    sio_st, players, st_events, p_events, room_code, p_ids = await _setup_room(5)
    p_events[0].clear()
    await players[0].emit("close_room", {})
    await asyncio.sleep(0.3)
    errs = [e for e in p_events[0] if e[0] == "error" and e[1].get("code") == "NOT_STORYTELLER"]
    assert errs, f"player close_room should error; got {p_events[0]}"
    print(f"[PASS] Non-ST close_room rejected: {errs[-1][1]}")
    await _disconnect_all(sio_st, players)


async def main():
    # 注:连跑多个 scenario 时,eventlet/socketio 客户端连接状态会互相污染
    # (server 端会出现 "Invalid session" 警告,导致新 client 的 connect 挂起)。
    # 每个 scenario 间留 1.5s 让所有 socket 完全释放,3 个场景独立可跑。
    await scenario_close_room()
    await asyncio.sleep(1.5)
    await scenario_reset_game()
    await asyncio.sleep(1.5)
    await scenario_close_room_no_st_privilege()
    banner("STAGE 2: ALL 3 E2E CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())