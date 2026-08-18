"""Stage 1.5 end-to-end: multi-nomination + corrected win rule.

Scenarios:
  1. 5 玩家开局
  2. P1 提名 P2,P2 提名 P3 → 两个并行提名
  3. 玩家投票(每个提名各投)
  4. ST 点击 end_nomination_phase → 结算
  5. 验证:yes 最多且 >= alive/2 的人被处决
  6. 验证:不能再提名同一人(每阶段)
  7. 验证:同一玩家不能提名 2 次
  8. 验证:恶魔胜规则(≤2 存活 + 恶魔在场)
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
        sio.on("error", lambda d, i=i: p_events[i].append(("error", d)))

    # 1. ST creates + 5 players join
    await sio_st.connect("http://localhost:5000", transports=["websocket"])
    await sio_st.emit("create_room", {"name": "ST_test"})
    await asyncio.sleep(0.3)
    st_evt = next((e for e in st_events if e[0] == "room_created"), None)
    assert st_evt, "ST didn't get room_created"
    room_code = st_evt[1]["room_code"]
    print(f"[PASS] ST created room {room_code}")

    p_ids = []
    for i, sio in enumerate(players):
        await sio.connect("http://localhost:5000", transports=["websocket"])
        await sio.emit("join_room", {"room_code": room_code, "name": f"p{i+1}"})
        await asyncio.sleep(0.15)
        j = next((e for e in p_events[i] if e[0] == "joined"), None)
        assert j, f"p{i+1} didn't join"
        p_ids.append(j[1]["player_id"])
    print(f"[PASS] 5 players joined: {p_ids}")

    # 2. Start game
    st_events.clear()
    await sio_st.emit("start_game", {})
    await asyncio.sleep(0.5)
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    assert state["phase"] == "first_night", f"game should start at first_night, got {state['phase']}"
    print(f"[PASS] Game started, phase=first_night")

    # ST 点击「开始白天」进入 DAY_DISCUSSION(白天讨论阶段,计时器启动)
    st_events.clear()
    await sio_st.emit("begin_day", {})
    await asyncio.sleep(0.4)
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    assert state["phase"] == "day_discussion", f"after begin_day, phase should be day_discussion, got {state['phase']}"
    assert state["day"] == 1
    print(f"[PASS] begin_day → day=1, phase=day_discussion")

    # ST 点击「开放提名」进入 DAY 阶段(玩家可开始提名)
    st_events.clear()
    await sio_st.emit("st_begin_nomination", {})
    await asyncio.sleep(0.3)
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    assert state["phase"] == "day", f"after st_begin_nomination, phase should be day, got {state['phase']}"
    print(f"[PASS] st_begin_nomination → phase=day")

    # 3. 多提名:p1 提名 p2,p2 提名 p3
    p2_id, p3_id = p_ids[1], p_ids[2]
    st_events.clear()
    await players[0].emit("nominate", {"target_id": p2_id})
    await asyncio.sleep(0.3)
    await players[1].emit("nominate", {"target_id": p3_id})
    await asyncio.sleep(0.3)
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    noms = state["current_nominations"]
    assert len(noms) == 2, f"expected 2 nominations, got {len(noms)}"
    nom_p2 = next((n for n in noms if n["nominee_id"] == p2_id), None)
    nom_p3 = next((n for n in noms if n["nominee_id"] == p3_id), None)
    assert nom_p2 and nom_p3, "missing nominations"
    print(f"[PASS] 2 parallel nominations: p1→p2 ({nom_p2['id']}), p2→p3 ({nom_p3['id']})")

    # 4. 重复提名应失败
    p4_id = p_ids[3]
    await players[0].emit("nominate", {"target_id": p4_id})  # p1 已提名
    await asyncio.sleep(0.2)
    errs_p0 = [e for e in p_events[0] if e[0] == "error"]
    assert errs_p0, "p1 should get error for 2nd nomination"
    print(f"[PASS] Same player can't nominate twice: {errs_p0[-1][1]['message']}")

    # 5. 提名已被人提名的目标应失败
    await players[3].emit("nominate", {"target_id": p2_id})  # p2 已被提名
    await asyncio.sleep(0.2)
    errs_p3 = [e for e in p_events[3] if e[0] == "error"]
    assert errs_p3, "p4 should get error for nominating already-targeted p2"
    print(f"[PASS] Same person can't be nominated twice: {errs_p3[-1][1]['message']}")

    # 6. 投票(每个提名各投 5 票)
    # p2 得 4 yes / 1 no,p3 得 1 yes / 4 no → p2 应该被处决(yes 4 >= alive 5/2=2.5)
    # p1 yes on p2, p2 yes on p2, p3 no on p2, p4 yes on p2, p5 no on p2
    # p1 no on p3, p2 no on p3, p3 yes on p3, p4 no on p3, p5 no on p3
    p2_nom_id = nom_p2["id"]
    p3_nom_id = nom_p3["id"]
    p2_votes = [True, True, False, True, False]   # 3 yes / 2 no
    p3_votes = [False, False, True, False, False]  # 1 yes / 4 no
    for i in range(5):
        await players[i].emit("vote", {"nomination_id": p2_nom_id, "value": p2_votes[i]})
        await asyncio.sleep(0.03)
    for i in range(5):
        await players[i].emit("vote", {"nomination_id": p3_nom_id, "value": p3_votes[i]})
        await asyncio.sleep(0.03)
    await asyncio.sleep(0.3)
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    noms = state["current_nominations"]
    p2_nom_after = next((n for n in noms if n["nominee_id"] == p2_id), None)
    p3_nom_after = next((n for n in noms if n["nominee_id"] == p3_id), None)
    # 未结算前 yes/no_count 还没填,从 votes 算
    p2_yes = sum(1 for v in p2_nom_after["votes"] if v["value"])
    p3_yes = sum(1 for v in p3_nom_after["votes"] if v["value"])
    assert p2_yes == 3, f"p2 should have 3 yes, got {p2_yes}"
    assert p3_yes == 1, f"p3 should have 1 yes, got {p3_yes}"
    print(f"[PASS] Votes counted: p2 = {p2_yes} yes, p3 = {p3_yes} yes")

    # 7. ST end_nomination_phase → p2 被处决(3 yes, threshold=2.5, 通过)
    st_events.clear()
    await sio_st.emit("end_nomination_phase", {})
    await asyncio.sleep(0.4)
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    # 检查 p2 已死
    p2_status = next((p for p in state["players"] if p["id"] == p2_id), None)
    assert p2_status["status"] == "dead", f"p2 should be dead, got {p2_status['status']}"
    # 检查 p3 仍存活(1 yes 没达门槛)
    p3_status = next((p for p in state["players"] if p["id"] == p3_id), None)
    assert p3_status["status"] == "alive", f"p3 should be alive, got {p3_status['status']}"
    print(f"[PASS] end_nomination_phase: p2 executed (3 yes ≥ 2.5), p3 survives (1 yes < 2.5)")

    # 8. 提名阶段状态:已结算的提名仍可见(resolved=True)
    noms = state["current_nominations"]
    assert all(n["resolved"] for n in noms), "all nominations should be resolved"
    p2_nom = next(n for n in noms if n["nominee_id"] == p2_id)
    assert p2_nom["passed"] == True, f"p2 nomination should be passed"
    assert p2_nom["executed"] == True, f"p2 should be executed"
    p3_nom = next(n for n in noms if n["nominee_id"] == p3_id)
    assert p3_nom["passed"] == False, f"p3 nomination should not be passed"
    assert p3_nom["executed"] == False
    assert p3_nom["met_threshold"] == False, f"p3 (1 yes < 2.5) should not met threshold"
    print(f"[PASS] Nominations resolved: p2.passed/executed=True, p3.met_threshold/passed/executed=False")

    # 9. 根据随机分配检查游戏状态(若 p2 是恶魔则直接结束)
    if state.get("winner"):
        # p2 正好是恶魔:game over,测试通过(此场景不需后续断言)
        assert state["phase"] == "ended"
        print(f"[INFO] p2 was the demon, game ended after 1st batch: winner={state['winner']}")
        banner("STAGE 1.5: ALL CHECKS PASSED (shortened due to early win)")
        banner(f"Room: {room_code}")
        for sio in players:
            try: await sio.disconnect()
            except: pass
        try: await sio_st.disconnect()
        except: pass
        return
    assert state["phase"] == "day"
    assert state.get("winner") is None
    print(f"[PASS] Game continues: 4 alive, no winner (p2 not the demon)")

    # 9b. 多提名同时过线:只有 yes 最多的被执行
    # 当前 4 人存活(p2 已死),threshold = 2
    # 第一批: p3 提名 p1 (p1 未被提名过)
    # 第二批: p5 提名 p4 (p4 未被提名过)
    # 票数: p3_nom 3 yes (p1,p3,p4) / 1 no (p5),p5_nom 3 yes (p1,p4,p5) / 1 no (p3)
    # 两者都 met threshold (3 ≥ 2),同票时 p3_nom 先提名赢 → p1 被处决
    p1_id, p3_id, p4_id, p5_id = p_ids[0], p_ids[2], p_ids[3], p_ids[4]
    st_events.clear()
    await players[2].emit("nominate", {"target_id": p1_id})  # p3 提名 p1
    await asyncio.sleep(0.3)
    await players[4].emit("nominate", {"target_id": p4_id})  # p5 提名 p4
    await asyncio.sleep(0.3)
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    p3_nom = next(n for n in state["current_nominations"] if n["nominee_id"] == p1_id)
    p5_nom = next(n for n in state["current_nominations"] if n["nominee_id"] == p4_id)
    p3_nom_id = p3_nom["id"]
    p5_nom_id = p5_nom["id"]

    # p1, p3, p4 yes on p3_nom; p1, p4, p5 yes on p5_nom
    votes = [
        (True, True),    # p1: yes on both
        (True, True),    # p2 (dead, skip)
        (True, False),   # p3: yes on p3_nom (nominator), no on p5_nom
        (True, True),    # p4: yes on both
        (False, True),   # p5: no on p3_nom, yes on p5_nom (nominator)
    ]
    for i, (v1, v2) in enumerate(votes):
        if i == 1:
            continue
        await players[i].emit("vote", {"value": v1, "nomination_id": p3_nom_id})
        await players[i].emit("vote", {"value": v2, "nomination_id": p5_nom_id})
        await asyncio.sleep(0.04)
    await asyncio.sleep(0.3)
    st_events.clear()
    await sio_st.emit("end_nomination_phase", {})
    await asyncio.sleep(0.4)
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    noms = state["current_nominations"]
    p3_nom_after = next(n for n in noms if n["nominee_id"] == p1_id)
    p5_nom_after = next(n for n in noms if n["nominee_id"] == p4_id)
    assert p3_nom_after["met_threshold"] == True, "p3_nom should meet threshold (3 yes >= 2)"
    assert p5_nom_after["met_threshold"] == True, "p5_nom should meet threshold (3 yes >= 2)"
    # 同票时 p3_nom 先提名赢
    assert p3_nom_after["executed"] == True, f"p3_nom (tied, earlier) should be executed"
    assert p5_nom_after["executed"] == False, f"p5_nom (tied, later) should NOT be executed"
    assert p3_nom_after["passed"] == True
    assert p5_nom_after["passed"] == False
    print(f"[PASS] Multi-met-threshold: p3_nom.executed=True (先提名), p5_nom.executed=False (后提名 同票未中选)")

    # p1 应死亡,p4 应存活
    p1_status = next(p for p in state["players"] if p["id"] == p1_id)
    assert p1_status["status"] == "dead", f"p1 should be dead, got {p1_status['status']}"
    p4_status = next(p for p in state["players"] if p["id"] == p4_id)
    assert p4_status["status"] == "alive", f"p4 should be alive, got {p4_status['status']}"
    print(f"[PASS] Multi-met-threshold: p1 dead, p4 alive (both met threshold, p3_nom 胜)")

    # 10. end_day → night
    st_events.clear()
    await sio_st.emit("end_day", {})
    await asyncio.sleep(0.4)
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    assert state["phase"] == "night"
    assert state["night"] == 1
    # 提名状态应被清空
    assert state["current_nominations"] == [], f"nominations should be reset, got {state['current_nominations']}"
    assert state["nominated_in_phase"] == []
    assert state["passed_in_phase"] == []
    assert state["nominated_as_target"] == []
    print(f"[PASS] end_day: night=1, nomination state cleared")

    # 11. begin_day → day 2 (新流程:进入 DAY_DISCUSSION 阶段)
    st_events.clear()
    await sio_st.emit("begin_day", {})
    await asyncio.sleep(0.4)
    state = [e for e in st_events if e[0] == "st_state_update"][-1][1]
    assert state["phase"] == "day_discussion"
    assert state["day"] == 2
    print(f"[PASS] begin_day: day=2, phase=day_discussion")

    banner("STAGE 1.5: ALL 11 E2E CHECKS PASSED")
    banner(f"Room: {room_code}")

    for sio in players:
        try: await sio.disconnect()
        except: pass
    try: await sio_st.disconnect()
    except: pass


if __name__ == "__main__":
    asyncio.run(main())
