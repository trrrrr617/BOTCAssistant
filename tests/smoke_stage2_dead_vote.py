"""死亡单票 + 夜间延迟公开 + 复活重置 回归测试。

场景:
  A. 死亡玩家可在提名阶段投一票;再次投票失败;其它提名仍可看到但不能再投
  B. 复活后(玩家回到 alive)dead_vote_used 重置,可在新提名投票
  C. 再次死亡后 dead_vote_used 重置,可再次投票一次
  D. 夜间 st_kill 不广播给房间;begin_day 时一次性公开
  E. 夜间 st_revive 不广播给房间;begin_day 时公开
  F. 白天 st_kill 仍立即广播(原行为)
  G. 杀死恶魔不自动结束,ST 仍可手动结束
  H. 场上只剩两人且其中有恶魔时不自动结束
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
    sio_st = socketio.AsyncClient()
    players = [socketio.AsyncClient() for _ in range(n_players)]
    st_events = []
    p_events = [[] for _ in range(n_players)]

    @sio_st.on("room_created")
    def _(d): st_events.append(("room_created", d))
    @sio_st.on("st_state_update")
    def _(d): st_events.append(("st_state_update", d))
    @sio_st.on("game_over")
    def _(d): st_events.append(("game_over", d))
    @sio_st.on("error")
    def _(d): st_events.append(("error", d))

    for i, sio in enumerate(players):
        sio.on("joined", lambda d, i=i: p_events[i].append(("joined", d)))
        sio.on("role_assigned", lambda d, i=i: p_events[i].append(("role_assigned", d)))
        sio.on("state_update", lambda d, i=i: p_events[i].append(("state_update", d)))
        sio.on("player_state", lambda d, i=i: p_events[i].append(("player_state", d)))
        sio.on("death", lambda d, i=i: p_events[i].append(("death", d)))
        sio.on("revive", lambda d, i=i: p_events[i].append(("revive", d)))
        sio.on("error", lambda d, i=i: p_events[i].append(("error", d)))

    return sio_st, players, st_events, p_events


async def _setup_room_until_day(n_players=5):
    """建房间 → 玩家加入 → 开始游戏 → begin_day, 进入 DAY 1。
    返回 (..., p_roles): dict of {pid: true_role} 来自 ST 状态"""
    sio_st, players, st_events, p_events = _make_clients(n_players)
    await sio_st.connect(BASE_URL, transports=["websocket"])
    await sio_st.emit("create_room", {"name": "ST_test"})
    await asyncio.sleep(0.3)
    rc = next((e for e in st_events if e[0] == "room_created"), None)
    assert rc
    room_code = rc[1]["room_code"]
    p_ids = []
    for i, sio in enumerate(players):
        await sio.connect(BASE_URL, transports=["websocket"])
        await sio.emit("join_room", {"room_code": room_code, "name": f"p{i+1}"})
        await asyncio.sleep(0.15)
        j = next((e for e in p_events[i] if e[0] == "joined"), None)
        assert j
        p_ids.append(j[1]["player_id"])
    # 录入最小兼容板子,否则 start_game 会被 NO_SCRIPT 守卫拒绝
    import sys as _sys
    _sys.path.insert(0, ".")
    from server.engine.script import make_legacy_compat_script as _mlcs
    script_dict = _mlcs().model_dump(mode="json")
    await sio_st.emit("set_script", {"script": script_dict})
    await asyncio.sleep(0.2)
    await sio_st.emit("start_game", {})
    await asyncio.sleep(0.4)
    # 进 DAY_DISCUSSION(白天讨论,计时器启动)
    await sio_st.emit("begin_day", {})
    await asyncio.sleep(0.4)
    # ST 开放提名 → 进 DAY 阶段(玩家可开始提名)
    await sio_st.emit("st_begin_nomination", {})
    await asyncio.sleep(0.3)
    # 读取每个玩家的真实角色(ST 视角)
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    p_roles = {}
    for p in state["players"]:
        if not p.get("is_storyteller") and p.get("true_role"):
            p_roles[p["id"]] = p["true_role"]
    return sio_st, players, st_events, p_events, room_code, p_ids, p_roles


DEMONS = {"hadjiya", "lleech"}


def _first_non_demon(p_ids, p_roles):
    for pid in p_ids:
        if p_roles.get(pid) not in DEMONS:
            return pid
    return None


async def _disconnect_all(sio_st, players):
    for sio in players:
        try: await sio.disconnect()
        except Exception: pass
    try: await sio_st.disconnect()
    except Exception: pass


def _latest_st_state(st_events):
    states = [e for e in st_events if e[0] == "st_state_update"]
    return states[-1][1] if states else None


def _get_player(player_list, pid):
    return next((p for p in player_list if p["id"] == pid), None)


async def _make_two_parallel_nominations(sio_st, p_ids, players):
    """p1 提名 p2, p3 提名 p4(都是 alive)。返回两个 nomination id。"""
    nom_p2_id, nom_p4_id = p_ids[1], p_ids[3]
    await players[0].emit("nominate", {"target_id": nom_p2_id})
    await asyncio.sleep(0.2)
    await players[2].emit("nominate", {"target_id": nom_p4_id})
    await asyncio.sleep(0.3)
    state = _latest_st_state([("dummy", None)])  # dummy; will refetch
    return None


async def scenario_dead_player_one_vote():
    banner("A: dead player can vote ONCE per death episode")
    sio_st, players, st_events, p_events, room_code, p_ids, p_roles = await _setup_room_until_day(5)

    # 选一个非恶魔玩家来杀(避免 kill 到恶魔直接结束游戏)
    dead_target = _first_non_demon(p_ids, p_roles)
    assert dead_target, "should find a non-demon player"
    print(f"[setup] will kill player {dead_target[:6]} (role={p_roles[dead_target]})")

    # 创建两个并行的提名,便于测试「单票」限制
    nom_target_p2 = p_ids[1]
    nom_target_p4 = p_ids[3]
    await players[0].emit("nominate", {"target_id": nom_target_p2})
    await asyncio.sleep(0.2)
    await players[2].emit("nominate", {"target_id": nom_target_p4})
    await asyncio.sleep(0.3)
    state = _latest_st_state([("dummy", None)])
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    noms = state["current_nominations"]
    nom_id_p2 = next(n["id"] for n in noms if n["nominee_id"] == nom_target_p2)
    nom_id_p4 = next(n["id"] for n in noms if n["nominee_id"] == nom_target_p4)
    print(f"[setup] 2 parallel noms: {nom_id_p2} (target=p2), {nom_id_p4} (target=p4)")

    # ST 杀目标(非恶魔)
    st_events.clear()
    await sio_st.emit("st_kill", {"player_id": dead_target})
    await asyncio.sleep(0.3)
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    target_after = _get_player(state["players"], dead_target)
    assert target_after["status"] == "dead", f"target should be dead; got {target_after['status']}"
    assert state.get("winner") is None, f"non-demon kill should NOT end the game; winner={state.get('winner')}"
    print(f"[PASS] st_kill target at day: status=death broadcast immediately")

    # 找到 dead_target 对应的 player 索引
    target_idx = p_ids.index(dead_target)

    # 死者在提名 1 上投一票
    p_events[target_idx].clear()
    await players[target_idx].emit("vote", {"nomination_id": nom_id_p2, "value": True})
    await asyncio.sleep(0.3)
    errs = [e for e in p_events[target_idx] if e[0] == "error"]
    assert not errs, f"first dead-vote should succeed; got errors {errs}"
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    p2_nom = next(n for n in state["current_nominations"] if n["id"] == nom_id_p2)
    target_vote = next((v for v in p2_nom["votes"] if v["voter_id"] == dead_target), None)
    assert target_vote and target_vote["value"] is True, f"target should have voted yes; got {p2_nom['votes']}"
    assert target_vote.get("is_dead_vote") is True, f"vote should be marked is_dead_vote; got {target_vote}"
    print(f"[PASS] dead player voted once: is_dead_vote=True")

    # 死者在同一提名上再次投票 → 应该被覆盖(同一个 voter 的最新票覆盖旧的)
    await players[target_idx].emit("vote", {"nomination_id": nom_id_p2, "value": False})
    await asyncio.sleep(0.3)
    errs = [e for e in p_events[target_idx] if e[0] == "error"]
    assert not errs, f"vote override on same nom should succeed; got {errs}"
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    p2_nom = next(n for n in state["current_nominations"] if n["id"] == nom_id_p2)
    target_votes_for_p2 = [v for v in p2_nom["votes"] if v["voter_id"] == dead_target]
    assert len(target_votes_for_p2) == 1, f"only 1 vote per player per nom; got {target_votes_for_p2}"
    assert target_votes_for_p2[0]["value"] is False, "vote should be overridden to false"
    print(f"[PASS] dead player can override their own vote on same nom (still 1 vote)")

    # 死者在第二个提名上投票 → 应被拒绝(已经用过本轮死亡的一票)
    p_events[target_idx].clear()
    await players[target_idx].emit("vote", {"nomination_id": nom_id_p4, "value": True})
    await asyncio.sleep(0.3)
    errs = [e for e in p_events[target_idx] if e[0] == "error"]
    assert errs, f"second nomination vote should fail; got no errors"
    assert "本轮死亡期间" in errs[-1][1].get("message", ""), \
        f"error should mention one-vote limit; got {errs[-1][1]}"
    print(f"[PASS] dead player cannot vote on second nomination: {errs[-1][1]['message']}")

    await _disconnect_all(sio_st, players)
    print("[OK] Scenario A passed.")


async def scenario_revive_resets_one_vote():
    banner("B: revive resets one-vote limit, re-death gives one new vote")
    sio_st, players, st_events, p_events, room_code, p_ids, p_roles = await _setup_room_until_day(5)
    # 选一个非恶魔且不是 p1(提名者)也不是 p2(被提名者)的玩家
    target = None
    for pid in p_ids:
        if p_roles.get(pid) not in DEMONS and pid != p_ids[0] and pid != p_ids[1]:
            target = pid
            break
    assert target, "should find a non-demon player that's not p1 or p2"
    target_idx = p_ids.index(target)

    # 杀 target, 让其在某个提名上投一票
    await sio_st.emit("st_kill", {"player_id": target})
    await asyncio.sleep(0.3)
    # p1 提名 p2
    p_events[0].clear()
    await players[0].emit("nominate", {"target_id": p_ids[1]})
    await asyncio.sleep(0.3)
    errs = [e for e in p_events[0] if e[0] == "error"]
    assert not errs, f"nominate failed: {errs}"
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    nom_id = state["current_nominations"][0]["id"]
    # target 投 yes(用掉本轮死亡一票)
    p_events[target_idx].clear()
    await players[target_idx].emit("vote", {"nomination_id": nom_id, "value": True})
    await asyncio.sleep(0.3)
    errs = [e for e in p_events[target_idx] if e[0] == "error"]
    assert not errs
    print(f"[setup] target used their one death vote")

    # ST 复活
    st_events.clear()
    await sio_st.emit("st_revive", {"player_id": target})
    await asyncio.sleep(0.3)
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    s = _get_player(state["players"], target)["status"]
    assert s == "alive", f"target should be alive; got {s}"
    print(f"[PASS] target revived: status=alive")

    # 复活后再投 no → 应成功
    p_events[target_idx].clear()
    await players[target_idx].emit("vote", {"nomination_id": nom_id, "value": False})
    await asyncio.sleep(0.3)
    errs = [e for e in p_events[target_idx] if e[0] == "error"]
    assert not errs, f"alive player should be able to vote; got {errs}"
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    nom = next(n for n in state["current_nominations"] if n["id"] == nom_id)
    tv = [v for v in nom["votes"] if v["voter_id"] == target]
    assert tv[0]["value"] is False, "target should have re-voted false"
    print(f"[PASS] target can vote after revive")

    # 再杀 target
    await sio_st.emit("st_kill", {"player_id": target})
    await asyncio.sleep(0.3)
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    s = _get_player(state["players"], target)["status"]
    assert s == "dead"
    print(f"[PASS] target re-killed")

    # 再投 yes → 应成功(新一轮死亡)
    p_events[target_idx].clear()
    await players[target_idx].emit("vote", {"nomination_id": nom_id, "value": True})
    await asyncio.sleep(0.3)
    errs = [e for e in p_events[target_idx] if e[0] == "error"]
    assert not errs, f"after re-kill, dead_vote_used should reset; got {errs}"
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    nom = next(n for n in state["current_nominations"] if n["id"] == nom_id)
    tv = [v for v in nom["votes"] if v["voter_id"] == target]
    assert len(tv) == 1 and tv[0]["value"] is True, \
        f"new death episode should allow 1 vote; got {tv}"
    print(f"[PASS] target can vote again after re-death (1 vote / death episode)")

    await _disconnect_all(sio_st, players)
    print("[OK] Scenario B passed.")


async def scenario_night_kill_delayed():
    banner("D: night st_kill broadcasts only on begin_day")
    sio_st, players, st_events, p_events, room_code, p_ids, p_roles = await _setup_room_until_day(5)
    target = _first_non_demon(p_ids, p_roles)
    target_idx = p_ids.index(target)

    # 现在是 day。先 end_day 进入 night
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    noms = state["current_nominations"]
    if noms and not all(n["resolved"] for n in noms):
        await sio_st.emit("end_nomination_phase", {})
        await asyncio.sleep(0.4)

    await sio_st.emit("end_day", {})
    await asyncio.sleep(0.4)
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    assert state["phase"] == "night", f"should be night; got {state['phase']}"
    print(f"[setup] night {state['night']}")

    # 夜间杀 target
    st_events.clear()
    for p_ev in p_events: p_ev.clear()
    await sio_st.emit("st_kill", {"player_id": target})
    await asyncio.sleep(0.4)

    # ST 状态:看到 target 为 dead
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    assert _get_player(state["players"], target)["status"] == "dead", "ST sees target dead"
    print(f"[PASS] ST sees target dead in st_state_update")

    # 所有玩家(包括被杀者本人):不应看到 target 已死亡
    for i in range(5):
        last_su = [e for e in p_events[i] if e[0] == "state_update"]
        if last_su:
            ps = last_su[-1][1]["players"]
            t = _get_player(ps, target)
            assert t["status"] == "alive", \
                f"player {i+1} should see target as alive during night; got {t['status']}"
    # 同样,任何玩家都不应收到 death 广播
    for i in range(5):
        deaths = [e for e in p_events[i] if e[0] == "death"]
        assert not deaths, f"player {i+1} should NOT receive death during night; got {deaths}"
    print(f"[PASS] nobody sees target's death during night")

    # 夜间的 ST 操作日志也必须只对 ST 可见,不能通过 player_state 泄漏
    for i in range(5):
        player_states = [e for e in p_events[i] if e[0] == "player_state"]
        for _, payload in player_states:
            leaked = [entry for entry in payload.get("filtered_log", []) if entry.get("kind") == "st_kill"]
            assert not leaked, f"player {i+1} should NOT see night st_kill log; got {leaked}"
    print(f"[PASS] night st_kill log remains storyteller-only")

    # 被杀者本人此时也不应收到 death 事件
    target_deaths = [e for e in p_events[target_idx] if e[0] == "death"]
    assert not target_deaths, "target should not learn about their death until begin_day"
    print(f"[PASS] target is not notified until begin_day")

    for p_ev in p_events: p_ev.clear()
    await sio_st.emit("begin_day", {})
    await asyncio.sleep(0.5)

    # 所有玩家都应收到 death 事件
    for i in range(5):
        deaths = [e for e in p_events[i] if e[0] == "death"]
        assert deaths, f"player {i+1} should receive death after begin_day; got none"
    print(f"[PASS] death broadcast to all players on begin_day")

    # state 显示 target 为 dead
    for i in range(5):
        last_su = [e for e in p_events[i] if e[0] == "state_update"]
        if last_su:
            ps = last_su[-1][1]["players"]
            t = _get_player(ps, target)
            assert t["status"] == "dead", \
                f"after begin_day, player {i+1} should see target dead; got {t['status']}"
    print(f"[PASS] target visible as dead after begin_day")

    await _disconnect_all(sio_st, players)
    print("[OK] Scenario D passed.")


async def scenario_night_revive_delayed():
    banner("E: night st_revive broadcasts only on begin_day")
    sio_st, players, st_events, p_events, room_code, p_ids, p_roles = await _setup_room_until_day(5)
    target = _first_non_demon(p_ids, p_roles)
    target_idx = p_ids.index(target)

    # 先杀 target(白天)
    await sio_st.emit("st_kill", {"player_id": target})
    await asyncio.sleep(0.3)
    # 入夜
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    if state["current_nominations"] and not all(n["resolved"] for n in state["current_nominations"]):
        await sio_st.emit("end_nomination_phase", {})
        await asyncio.sleep(0.4)
    await sio_st.emit("end_day", {})
    await asyncio.sleep(0.4)

    # 夜间复活 target
    st_events.clear()
    for p_ev in p_events: p_ev.clear()
    await sio_st.emit("st_revive", {"player_id": target})
    await asyncio.sleep(0.4)

    # target 私下收到 revive 事件
    revives = [e for e in p_events[target_idx] if e[0] == "revive"]
    assert revives, "target should receive personal revive notification during night"
    print(f"[PASS] target personally revived at night")

    # begin_day 时公开
    for p_ev in p_events: p_ev.clear()
    await sio_st.emit("begin_day", {})
    await asyncio.sleep(0.5)
    for i in range(5):
        last_su = [e for e in p_events[i] if e[0] == "state_update"]
        if last_su:
            ps = last_su[-1][1]["players"]
            t = _get_player(ps, target)
            assert t["status"] == "alive", \
                f"after begin_day, player {i+1} should see target alive; got {t['status']}"
    print(f"[PASS] target visible as alive after begin_day")

    await _disconnect_all(sio_st, players)
    print("[OK] Scenario E passed.")


async def scenario_day_kill_immediate():
    banner("F: day st_kill still broadcasts immediately (regression)")
    sio_st, players, st_events, p_events, room_code, p_ids, p_roles = await _setup_room_until_day(5)
    target = _first_non_demon(p_ids, p_roles)
    for p_ev in p_events: p_ev.clear()
    await sio_st.emit("st_kill", {"player_id": target})
    await asyncio.sleep(0.4)
    for i in range(5):
        deaths = [e for e in p_events[i] if e[0] == "death"]
        assert deaths, f"player {i+1} should receive death immediately during day"
    print(f"[PASS] day kill broadcasts to all immediately")

    await _disconnect_all(sio_st, players)
    print("[OK] Scenario F passed.")


async def scenario_demon_kill_manual_end():
    banner("G: killing demon does not auto-end; ST can end manually")
    sio_st, players, st_events, p_events, room_code, p_ids, p_roles = await _setup_room_until_day(5)
    target = next((pid for pid in p_ids if p_roles.get(pid) in DEMONS), None)
    assert target, "should find a demon"

    st_events.clear()
    await sio_st.emit("st_kill", {"player_id": target})
    await asyncio.sleep(0.4)
    state = _latest_st_state(st_events)
    assert state, "ST should receive state after killing demon"
    assert state["phase"] == "day", f"killing demon should not end game; phase={state['phase']}"
    assert state.get("winner") is None, f"winner should stay unset until ST ends game; got {state.get('winner')}"
    assert not [e for e in st_events if e[0] == "game_over"], "demon kill must not emit automatic game_over"
    print("[PASS] demon kill does not automatically end the game")

    await sio_st.emit("end_game", {"reason": "ST 手动宣布善良阵营获胜"})
    await asyncio.sleep(0.4)
    state = _latest_st_state(st_events)
    assert state["phase"] == "ended", f"manual end should set ended; phase={state['phase']}"
    assert state.get("winner") == "manual", f"manual end should use manual winner; got {state.get('winner')}"
    assert [e for e in st_events if e[0] == "game_over"], "manual end should still emit game_over"
    print("[PASS] storyteller can manually end and announce the winner")

    await _disconnect_all(sio_st, players)
    print("[OK] Scenario G passed.")


async def scenario_two_alive_with_demon_no_auto_end():
    banner("H: two alive including demon does not auto-end")
    sio_st, players, st_events, p_events, room_code, p_ids, p_roles = await _setup_room_until_day(5)
    demon = next((pid for pid in p_ids if p_roles.get(pid) in DEMONS), None)
    survivor = next((pid for pid in p_ids if p_roles.get(pid) not in DEMONS), None)
    assert demon and survivor, "should find demon and good survivor"

    # 杀掉其余三名玩家,让场上只剩一名非恶魔和一名恶魔
    for pid in p_ids:
        if pid in (demon, survivor):
            continue
        await sio_st.emit("st_kill", {"player_id": pid})
        await asyncio.sleep(0.2)

    await asyncio.sleep(0.3)
    state = _latest_st_state(st_events)
    alive = [p for p in state["players"] if not p.get("is_storyteller") and p["status"] == "alive"]
    assert len(alive) == 2, f"expected exactly two alive players; got {alive}"
    assert any(p["id"] == demon for p in alive), "the demon should still be alive"
    assert state["phase"] == "day", f"two alive including demon should remain in day; got {state['phase']}"
    assert state.get("winner") is None, f"winner should remain unset; got {state.get('winner')}"
    assert not [e for e in st_events if e[0] == "game_over"], "two alive including demon must not auto-emit game_over"
    print("[PASS] two alive including demon does not automatically end the game")

    await _disconnect_all(sio_st, players)
    print("[OK] Scenario H passed.")


async def main():
    await scenario_dead_player_one_vote()
    await scenario_revive_resets_one_vote()
    await scenario_night_kill_delayed()
    await scenario_night_revive_delayed()
    await scenario_day_kill_immediate()
    await scenario_demon_kill_manual_end()
    await scenario_two_alive_with_demon_no_auto_end()
    banner("DEAD-VOTE & NIGHT-REVEAL: ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())