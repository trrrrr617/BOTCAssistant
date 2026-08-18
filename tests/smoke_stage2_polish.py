"""四个修复的回归测试:

1. 游戏从首夜开始(phase=first_night,day=0,night=0),ST 必须 begin_day 才能进 DAY 1
2. st_change_role 日志使用中文角色名
3. (前端 CSS,无 socket 测试 — 通过手动验证)
4. (前端 JS,无 socket 测试 — 通过手动验证)
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


async def _setup_room_until_first_night(n_players=5):
    """建房间,5 玩家加入,开始游戏停在 first_night。"""
    sio_st, players, st_events, p_events = _make_clients(n_players)
    await sio_st.connect("http://localhost:5000", transports=["websocket"])
    await sio_st.emit("create_room", {"name": "ST_test"})
    await asyncio.sleep(0.3)
    rc = next((e for e in st_events if e[0] == "room_created"), None)
    assert rc, "ST didn't get room_created"
    room_code = rc[1]["room_code"]
    p_ids = []
    for i, sio in enumerate(players):
        await sio.connect("http://localhost:5000", transports=["websocket"])
        await sio.emit("join_room", {"room_code": room_code, "name": f"p{i+1}"})
        await asyncio.sleep(0.15)
        j = next((e for e in p_events[i] if e[0] == "joined"), None)
        assert j, f"p{i+1} didn't join"
        p_ids.append(j[1]["player_id"])
    st_events.clear()
    await sio_st.emit("start_game", {})
    await asyncio.sleep(0.4)
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    assert state["phase"] == "first_night", f"after start_game, phase should be first_night, got {state['phase']}"
    return sio_st, players, st_events, p_events, room_code, p_ids


async def _disconnect_all(sio_st, players):
    for sio in players:
        try: await sio.disconnect()
        except Exception: pass
    try: await sio_st.disconnect()
    except Exception: pass


async def scenario_game_starts_at_night():
    """修复 1:游戏从首夜开始,ST 需 begin_day 进入 DAY 1。"""
    banner("Fix 1: Game starts at first_night, begin_day -> day 1")
    sio_st, players, st_events, p_events, room_code, p_ids = await _setup_room_until_first_night(5)

    # 验证:首夜状态
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    assert state["phase"] == "first_night", f"phase should be first_night, got {state['phase']}"
    assert state["day"] == 0, f"day should be 0, got {state['day']}"
    assert state["night"] == 0, f"night should be 0, got {state['night']}"
    # 计时器应未启动
    assert state["chat_started_at"] is None, f"chat_started_at should be None at night, got {state['chat_started_at']}"
    print(f"[PASS] After start_game: phase=first_night, day=0, night=0, no chat timer")

    # 验证:首夜阶段,玩家不能提名(因为还没到 DAY)
    p_events[0].clear()
    await players[0].emit("nominate", {"target_id": p_ids[1]})
    await asyncio.sleep(0.3)
    errs = [e for e in p_events[0] if e[0] == "error"]
    assert errs and "不允许提名" in errs[-1][1].get("message", ""), \
        f"nominate in first_night should fail; got {p_events[0]}"
    print(f"[PASS] nominate in first_night rejected: {errs[-1][1]['message']}")

    # 验证:ST 调 begin_day 进入 DAY 1
    st_events.clear()
    await sio_st.emit("begin_day", {})
    await asyncio.sleep(0.4)
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    assert state["phase"] == "day_discussion", f"phase should be day_discussion, got {state['phase']}"
    assert state["day"] == 1, f"day should be 1, got {state['day']}"
    assert state["chat_started_at"] is not None, "chat_started_at should be set after begin_day"
    print(f"[PASS] After begin_day: phase=day_discussion, day=1, chat timer running")

    await _disconnect_all(sio_st, players)
    print("[OK] Fix 1 scenario passed.")


async def scenario_role_log_chinese():
    """修复 2:st_change_role 日志使用中文角色名。"""
    banner("Fix 2: st_change_role log uses Chinese role names")
    sio_st, players, st_events, p_events, room_code, p_ids = await _setup_room_until_first_night(5)
    await asyncio.sleep(0.2)  # 让 player_state 推完

    target_id = p_ids[0]
    await sio_st.emit("st_change_role", {"player_id": target_id, "new_role": "cerenovus"})
    await asyncio.sleep(0.4)

    # ST state.log 应包含中文角色名
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    change_logs = [e for e in state["log"] if e["kind"] == "st_change_role"]
    assert change_logs, f"ST state.log should include st_change_role; got kinds {[e['kind'] for e in state['log']]}"
    log_text = change_logs[-1]["text"]
    assert "灵言师" in log_text, f"log text should contain Chinese role name '灵言师'; got '{log_text}'"
    assert "cerenovus" not in log_text.lower(), f"log text should NOT contain English ID; got '{log_text}'"
    print(f"[PASS] ST log: '{log_text}'")

    # 被变更玩家 private_log 也用中文
    p0_player_state = [e for e in p_events[0] if e[0] == "player_state"]
    assert p0_player_state, "p1 should receive player_state after st_change_role"
    private_log = p0_player_state[-1][1].get("private_log", [])
    p_change = [e for e in private_log if e.get("kind") == "st_change_role"]
    assert p_change, f"p1 private_log should contain st_change_role; got {[e.get('kind') for e in private_log]}"
    p_log_text = p_change[-1]["text"]
    assert "灵言师" in p_log_text, f"p1 private log should contain Chinese role name; got '{p_log_text}'"
    print(f"[PASS] p1 private_log: '{p_log_text}'")

    # 验证多种角色的中文映射
    await sio_st.emit("st_change_role", {"player_id": target_id, "new_role": "mountain_man"})
    await asyncio.sleep(0.3)
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    change_logs = [e for e in state["log"] if e["kind"] == "st_change_role"]
    last_log_text = change_logs[-1]["text"]
    assert "巡山人" in last_log_text, f"log should contain '巡山人' (mountain_man); got '{last_log_text}'"
    print(f"[PASS] mountain_man -> '巡山人': '{last_log_text}'")

    await _disconnect_all(sio_st, players)
    print("[OK] Fix 2 scenario passed.")


async def main():
    await scenario_game_starts_at_night()
    await scenario_role_log_chinese()
    banner("POLISH FIXES: ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())