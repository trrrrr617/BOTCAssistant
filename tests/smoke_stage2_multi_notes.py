"""多条批注 + Bug 修复回归测试。

场景:
  A. Bug 修复:ST 编辑批注必须传 player_id(此处模拟前端逻辑,验证后端)
  B. st_set_notes:ST 可以添加多条批注、编辑单条、删除单条
  C. player_set_notes:玩家可以对同一目标写多条批注
  D. 权限隔离:非 ST 不能调 st_set_notes;非 owner 不能调 player_set_notes
  E. reset_game 后批注清空
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


def _make_clients(n_players=3):
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


async def _setup_room(n_players=3):
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
        assert j
        p_ids.append(j[1]["player_id"])
    await sio_st.emit("start_game", {})
    await asyncio.sleep(0.4)
    return sio_st, players, st_events, p_events, room_code, p_ids


async def _disconnect_all(sio_st, players):
    for sio in players:
        try: await sio.disconnect()
        except Exception: pass
    try: await sio_st.disconnect()
    except Exception: pass


def _get_latest_st_state(st_events):
    states = [e for e in st_events if e[0] == "st_state_update"]
    return states[-1][1] if states else None


def _get_player(player_list, pid):
    return next((p for p in player_list if p["id"] == pid), None)


async def scenario_st_multi_notes():
    banner("A/B: ST adds, edits, deletes multiple notes")
    sio_st, players, st_events, p_events, room_code, p_ids = await _setup_room(3)
    target_id = p_ids[0]

    # 1. 添加第一条批注
    await sio_st.emit("st_set_notes", {"player_id": target_id, "notes": [
        {"id": "n1", "text": "第一条"},
    ]})
    await asyncio.sleep(0.3)
    state = _get_latest_st_state(st_events)
    p = _get_player(state["players"], target_id)
    assert len(p["st_notes"]) == 1 and p["st_notes"][0]["text"] == "第一条", \
        f"expected 1 note; got {p['st_notes']}"
    print(f"[PASS] add note 1: {p['st_notes']}")

    # 2. 添加第二条(整列表替换,保留 id)
    await sio_st.emit("st_set_notes", {"player_id": target_id, "notes": [
        {"id": "n1", "text": "第一条"},
        {"id": "n2", "text": "第二条"},
    ]})
    await asyncio.sleep(0.3)
    state = _get_latest_st_state(st_events)
    p = _get_player(state["players"], target_id)
    assert len(p["st_notes"]) == 2, f"expected 2 notes; got {p['st_notes']}"
    texts = sorted(n["text"] for n in p["st_notes"])
    assert texts == ["第一条", "第二条"], f"unexpected texts: {texts}"
    print(f"[PASS] add note 2: {p['st_notes']}")

    # 3. 编辑 n2(替换 text)
    await sio_st.emit("st_set_notes", {"player_id": target_id, "notes": [
        {"id": "n1", "text": "第一条"},
        {"id": "n2", "text": "第二条(已修改)"},
    ]})
    await asyncio.sleep(0.3)
    state = _get_latest_st_state(st_events)
    p = _get_player(state["players"], target_id)
    n2 = next((n for n in p["st_notes"] if n["id"] == "n2"), None)
    assert n2 and n2["text"] == "第二条(已修改)", f"n2 should be edited; got {n2}"
    print(f"[PASS] edit n2: {n2}")

    # 4. 删除 n1(整列表只剩 n2)
    await sio_st.emit("st_set_notes", {"player_id": target_id, "notes": [
        {"id": "n2", "text": "第二条(已修改)"},
    ]})
    await asyncio.sleep(0.3)
    state = _get_latest_st_state(st_events)
    p = _get_player(state["players"], target_id)
    assert len(p["st_notes"]) == 1 and p["st_notes"][0]["id"] == "n2", \
        f"expected only n2; got {p['st_notes']}"
    print(f"[PASS] delete n1: {p['st_notes']}")

    # 5. 空文本应被服务端跳过
    await sio_st.emit("st_set_notes", {"player_id": target_id, "notes": [
        {"id": "n3", "text": "  "},  # 全空白
        {"id": "n4", "text": "有效"},
    ]})
    await asyncio.sleep(0.3)
    state = _get_latest_st_state(st_events)
    p = _get_player(state["players"], target_id)
    assert len(p["st_notes"]) == 1 and p["st_notes"][0]["id"] == "n4", \
        f"empty text should be skipped; got {p['st_notes']}"
    print(f"[PASS] empty text skipped")

    # 6. 缺少 player_id 应失败
    st_events.clear()
    await sio_st.emit("st_set_notes", {"notes": [{"text": "x"}]})
    await asyncio.sleep(0.3)
    errs = [e for e in st_events if e[0] == "error" and e[1].get("code") == "INVALID_INPUT"]
    assert errs, f"missing player_id should error; got {st_events}"
    print(f"[PASS] missing player_id rejected")

    await _disconnect_all(sio_st, players)
    print("[OK] Scenario A/B passed.")


async def scenario_player_multi_notes():
    banner("C: player writes multiple notes about one target")
    sio_st, players, st_events, p_events, room_code, p_ids = await _setup_room(3)
    author_id = p_ids[0]
    target_id = p_ids[1]

    # 等初始 player_state 推送
    await asyncio.sleep(0.2)
    p_events[0].clear()

    # 1. 玩家 1 写第一条关于玩家 2 的批注
    await players[0].emit("player_set_notes", {"target_id": target_id, "notes": [
        {"id": "a1", "text": "他好像在撒谎"},
    ]})
    await asyncio.sleep(0.3)
    ps = [e for e in p_events[0] if e[0] == "player_state"]
    assert ps, f"player1 should receive player_state; got {p_events[0]}"
    notes = ps[-1][1]["player_notes"].get(target_id) or []
    assert len(notes) == 1 and notes[0]["text"] == "他好像在撒谎", f"got {notes}"
    print(f"[PASS] player1 wrote note 1 about p2: {notes}")

    # 2. 加第二条
    await players[0].emit("player_set_notes", {"target_id": target_id, "notes": [
        {"id": "a1", "text": "他好像在撒谎"},
        {"id": "a2", "text": "而且手指动作多"},
    ]})
    await asyncio.sleep(0.3)
    ps = [e for e in p_events[0] if e[0] == "player_state"]
    notes = ps[-1][1]["player_notes"].get(target_id) or []
    assert len(notes) == 2, f"expected 2 notes; got {notes}"
    print(f"[PASS] player1 wrote note 2: {notes}")

    # 3. 验证:玩家 2 看不到玩家 1 的批注(隐私)
    p_events[1].clear()
    # 触发玩家 2 的 player_state 推送(通过简单状态变化触发)
    await sio_st.emit("st_add_log", {"text": "测试日志"})
    await asyncio.sleep(0.3)
    p2_ps = [e for e in p_events[1] if e[0] == "player_state"]
    if p2_ps:
        p2_notes = p2_ps[-1][1]["player_notes"]
        assert target_id not in p2_notes or len(p2_notes.get(target_id, [])) == 0, \
            f"player2 should NOT see player1's notes about them; got {p2_notes}"
        print(f"[PASS] privacy: p2 does NOT see p1's notes")

    # 4. 给不存在的 target 应失败
    p_events[0].clear()
    fake_target = "nonexistent_id"
    await players[0].emit("player_set_notes", {"target_id": fake_target, "notes": [
        {"id": "x", "text": "x"},
    ]})
    await asyncio.sleep(0.3)
    errs = [e for e in p_events[0] if e[0] == "error"]
    assert errs, f"invalid target should error; got {p_events[0]}"
    print(f"[PASS] invalid target rejected: {errs[-1][1]}")

    await _disconnect_all(sio_st, players)
    print("[OK] Scenario C passed.")


async def scenario_permission_checks():
    banner("D: permission checks (non-ST and non-owner)")
    sio_st, players, st_events, p_events, room_code, p_ids = await _setup_room(3)
    target_id = p_ids[0]

    # 1. 玩家调 st_set_notes 应被拒绝
    p_events[0].clear()
    await players[0].emit("st_set_notes", {"player_id": target_id, "notes": [
        {"text": "hack"},
    ]})
    await asyncio.sleep(0.3)
    errs = [e for e in p_events[0] if e[0] == "error" and e[1].get("code") == "NOT_STORYTELLER"]
    assert errs, f"non-ST should be rejected; got {p_events[0]}"
    print(f"[PASS] player st_set_notes rejected: {errs[-1][1]}")

    # 2. ST 调 player_set_notes 应被拒绝
    st_events.clear()
    await sio_st.emit("player_set_notes", {"target_id": p_ids[1], "notes": [
        {"text": "st trying"},
    ]})
    await asyncio.sleep(0.3)
    errs = [e for e in st_events if e[0] == "error" and e[1].get("code") == "NOT_PLAYER"]
    assert errs, f"ST player_set_notes should be rejected; got {st_events}"
    print(f"[PASS] ST player_set_notes rejected: {errs[-1][1]}")

    await _disconnect_all(sio_st, players)
    print("[OK] Scenario D passed.")


async def scenario_reset_clears_notes():
    banner("E: reset_game clears all notes")
    # reset_game 需要 5-15 玩家
    sio_st, players, st_events, p_events, room_code, p_ids = await _setup_room(5)
    target_id = p_ids[0]

    # 写 ST 批注和玩家批注
    await sio_st.emit("st_set_notes", {"player_id": target_id, "notes": [
        {"id": "x", "text": "ST note"},
    ]})
    await asyncio.sleep(0.3)
    await players[1].emit("player_set_notes", {"target_id": target_id, "notes": [
        {"id": "y", "text": "Player note"},
    ]})
    await asyncio.sleep(0.3)

    # 强制结束 + reset
    await sio_st.emit("end_game", {"reason": "test"})
    await asyncio.sleep(0.3)
    await sio_st.emit("reset_game", {})
    await asyncio.sleep(0.4)

    # 验证所有批注清空
    state = _get_latest_st_state(st_events)
    for p in state["players"]:
        if p["is_storyteller"]: continue
        assert p["st_notes"] == [], f"{p['name']} st_notes should be empty; got {p['st_notes']}"
    # 验证玩家 1 的 player_notes 也清空
    await asyncio.sleep(0.2)
    p1_ps = [e for e in p_events[1] if e[0] == "player_state"]
    if p1_ps:
        assert p1_ps[-1][1].get("player_notes") == {}, \
            f"player1 player_notes should be cleared; got {p1_ps[-1][1]['player_notes']}"
    print(f"[PASS] all notes cleared after reset_game")

    await _disconnect_all(sio_st, players)
    print("[OK] Scenario E passed.")


async def main():
    await scenario_st_multi_notes()
    await scenario_player_multi_notes()
    await scenario_permission_checks()
    await scenario_reset_clears_notes()
    banner("MULTI-NOTES: ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())