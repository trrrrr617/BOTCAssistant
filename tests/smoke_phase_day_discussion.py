"""Stage 4+: 白天讨论阶段(DAY_DISCUSSION)纯模块级测试。

核心流程:
  NIGHT → begin_day → DAY_DISCUSSION(计时器开跑,无提名)
  DAY_DISCUSSION → begin_nomination → DAY(开放提名/投票)
  DAY → end_day → NIGHT
  DAY_DISCUSSION → end_day → NIGHT(允许跳过提名直接入夜)
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import eventlet  # noqa
eventlet.monkey_patch()

from server.engine.game_state import GameState, Player, PlayerStatus, Phase, Nomination
from server.engine.phase import can_transition, assert_transition, PhaseTransitionError
from server.engine.state_machine import (
    begin_day, begin_nomination, end_day,
    start_nomination, cast_vote, end_nomination_phase, pass_nomination,
)


def _setup(phase=Phase.NIGHT, night=1, day=0):
    state = GameState(room_code="ABCD", phase=phase, night=night, day=day)
    state.players = [
        Player(id="st", name="ST", seat=0, is_storyteller=True),
        Player(id="p1", name="A", seat=1),
        Player(id="p2", name="B", seat=2),
        Player(id="p3", name="C", seat=3),
        Player(id="p4", name="D", seat=4),
        Player(id="p5", name="E", seat=5),
    ]
    return state


def _run():
    # A. 阶段转换图
    assert can_transition(Phase.NIGHT, Phase.DAY_DISCUSSION)
    assert can_transition(Phase.FIRST_NIGHT, Phase.DAY_DISCUSSION)
    assert can_transition(Phase.DAY_DISCUSSION, Phase.DAY)
    assert can_transition(Phase.DAY_DISCUSSION, Phase.NIGHT)
    assert can_transition(Phase.DAY, Phase.NIGHT)
    assert not can_transition(Phase.NIGHT, Phase.DAY), "NIGHT 不可直接跳 DAY"
    assert not can_transition(Phase.DAY, Phase.DAY_DISCUSSION), "DAY 不可回退到讨论"
    assert not can_transition(Phase.DAY_DISCUSSION, Phase.SETUP)
    print("[PASS] A. 阶段转换图正确")

    # B. NIGHT -> DAY_DISCUSSION(begin_day)
    state = _setup(phase=Phase.NIGHT, night=1)
    state = begin_day(state)
    assert state.phase == Phase.DAY_DISCUSSION
    assert state.day == 1
    assert state.chat_started_at is not None
    assert state.current_nominations == [], "新一天开始时提名应被清空"
    assert state.nominated_in_phase == set()
    print("[PASS] B. begin_day -> DAY_DISCUSSION (timer starts, noms cleared)")

    # C. DAY_DISCUSSION 阶段禁止提名
    try:
        start_nomination(state, "p1", "p2")
        raise AssertionError("should reject nominate in DAY_DISCUSSION")
    except ValueError as e:
        assert "当前阶段" in str(e) and "不允许提名" in str(e), str(e)
        print(f"[PASS] C. nominate rejected in DAY_DISCUSSION: {e}")

    # D. DAY_DISCUSSION 阶段禁止投票
    try:
        cast_vote(state, "p1", "n1", value=True)
        raise AssertionError("should reject vote in DAY_DISCUSSION")
    except ValueError as e:
        assert "当前阶段" in str(e), str(e)
        print(f"[PASS] D. vote rejected in DAY_DISCUSSION")

    # E. DAY_DISCUSSION -> DAY(begin_nomination)
    state = begin_nomination(state)
    assert state.phase == Phase.DAY
    assert state.day == 1  # 不变
    assert state.current_nominations == []  # begin_nomination 不应清空提名
    print("[PASS] E. begin_nomination -> DAY")

    # F. DAY 阶段允许提名和投票
    state = start_nomination(state, "p1", "p2")
    assert state.phase == Phase.DAY
    nom_id = state.current_nominations[0].id
    state = cast_vote(state, "p3", nom_id, value=True)
    assert state.current_nominations[0].votes[-1].value is True
    print("[PASS] F. nominate + vote work in DAY")

    # G. 结算后仍在 DAY(不是新阶段)
    state = end_nomination_phase(state)
    assert state.phase == Phase.DAY
    assert state.current_nominations[0].resolved is True
    print("[PASS] G. end_nomination_phase stays in DAY")

    # H. DAY -> NIGHT(end_day)
    state = end_day(state)
    assert state.phase == Phase.NIGHT
    assert state.night == 2
    print("[PASS] H. end_day -> NIGHT (with closed noms)")

    # I. DAY_DISCUSSION -> NIGHT(允许跳过提名)
    state = _setup(phase=Phase.NIGHT, night=5)
    state = begin_day(state)
    assert state.phase == Phase.DAY_DISCUSSION
    state = end_day(state)
    assert state.phase == Phase.NIGHT
    assert state.night == 6
    print("[PASS] I. end_day from DAY_DISCUSSION works (skip)")

    # J. begin_nomination 在非 DAY_DISCUSSION 阶段被拒绝
    for bad_phase in [Phase.LOBBY, Phase.SETUP, Phase.NIGHT, Phase.DAY]:
        state2 = _setup(phase=bad_phase)
        try:
            begin_nomination(state2)
            raise AssertionError(f"should reject from {bad_phase}")
        except PhaseTransitionError as e:
            print(f"[PASS] J.{bad_phase.value} begin_nomination rejected: {e}")

    # K. DAY_DISCUSSION 期间 nominated_in_phase 等阶段内状态保持空,
    #    即使后续 begin_nomination 也保持(begin_nomination 不重置)
    state = _setup(phase=Phase.NIGHT, night=1)
    state = begin_day(state)
    # ST 在讨论阶段决定开放提名,但目前还没人提名
    assert state.nominated_in_phase == set()
    state = begin_nomination(state)
    assert state.nominated_in_phase == set()  # 不变
    print("[PASS] K. begin_nomination preserves nomination phase state")

    # L. 连续多天的完整流程
    state = _setup(phase=Phase.NIGHT, night=1)
    # 第一天
    state = begin_day(state)
    assert state.phase == Phase.DAY_DISCUSSION
    state = begin_nomination(state)
    state = start_nomination(state, "p1", "p2")
    state = cast_vote(state, "p3", state.current_nominations[0].id, True)
    state = end_nomination_phase(state)
    state = end_day(state)
    assert state.phase == Phase.NIGHT
    assert state.night == 2
    # 第二天
    state = begin_day(state)
    assert state.day == 2
    assert state.phase == Phase.DAY_DISCUSSION
    print("[PASS] L. multi-day cycle (DAY_DISCUSSION -> DAY -> NIGHT -> DAY_DISCUSSION)")

    print("\n[OK] smoke_phase_day_discussion all tests passed")


if __name__ == "__main__":
    _run()
