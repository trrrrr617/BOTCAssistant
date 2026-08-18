"""Stage 4+: Lobby / Ended 阶段座位交换测试 + 玩家列表按 seat 排序测试。"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import eventlet  # noqa
eventlet.monkey_patch()

from server.engine.game_state import GameState, Player, PlayerStatus, Phase
from server.engine.state_machine import (
    request_swap, accept_swap, decline_swap, cancel_swap, st_swap_seats,
)
from server.room.room import Room
from server.room.player import RuntimePlayer


def _setup(phase=Phase.LOBBY):
    state = GameState(room_code="ABCD", phase=phase)
    state.players = [
        Player(id="st", name="ST", seat=0, is_storyteller=True),
        Player(id="p1", name="A", seat=1),
        Player(id="p2", name="B", seat=2),
        Player(id="p3", name="C", seat=3),
        Player(id="p4", name="D", seat=4),
    ]
    return state


def _seat(state, pid):
    return next(p for p in state.players if p.id == pid).seat


def _run():
    # A. 玩家发起申请
    state = _setup()
    state = request_swap(state, "p1", "p2")
    assert state.pending_swap is not None
    assert state.pending_swap.from_id == "p1"
    assert state.pending_swap.to_id == "p2"
    assert state.pending_swap.from_name == "A"
    assert state.pending_swap.to_name == "B"
    print("[PASS] A. request_swap from A to B")

    # B. 只能被申请人接受
    try:
        accept_swap(state, "p1")  # 申请人不能接受自己的
        raise AssertionError
    except ValueError as e:
        assert "只有被申请的玩家能接受" in str(e), str(e)
    try:
        accept_swap(state, "p3")  # 第三方不能
        raise AssertionError
    except ValueError as e:
        assert "只有被申请的玩家能接受" in str(e), str(e)
    print("[PASS] B. only target can accept")

    # C. 被申请人接受 → 座位交换
    state = accept_swap(state, "p2")
    assert state.pending_swap is None
    assert _seat(state, "p1") == 2
    assert _seat(state, "p2") == 1
    print("[PASS] C. accept_swap swaps seats")

    # D. 拒绝路径
    state = request_swap(state, "p1", "p3")
    state = decline_swap(state, "p3")
    assert state.pending_swap is None
    print("[PASS] D. decline_swap clears pending_swap")

    # E. 申请人取消
    state = request_swap(state, "p1", "p4")
    state = cancel_swap(state, "p1")
    assert state.pending_swap is None
    print("[PASS] E. cancel_swap by applicant")

    # F. ST 取消(即便不是申请人)
    state = request_swap(state, "p1", "p2")
    st_player_id = next(p.id for p in state.players if p.is_storyteller)
    state = cancel_swap(state, st_player_id, is_st=True)
    assert state.pending_swap is None
    print("[PASS] F. cancel_swap by ST (not applicant)")

    # G. ST 强制交换(直接执行)
    # 此时(经过 C 后)p1.seat=2, p4.seat=4 → 交换后 p1.seat=4, p4.seat=2
    state = st_swap_seats(state, "p1", "p4")
    assert _seat(state, "p1") == 4
    assert _seat(state, "p4") == 2
    print("[PASS] G. st_swap_seats forces swap")

    # H. ST 强制交换同时清掉 pending_swap
    # 此时(经过 G 后)p1.seat=4, p2.seat=1 → st_swap(p1,p2) 后 p1.seat=1, p2.seat=4
    state = request_swap(state, "p1", "p2")
    state = st_swap_seats(state, "p1", "p2")
    assert state.pending_swap is None
    assert _seat(state, "p1") == 1
    assert _seat(state, "p2") == 4
    print("[PASS] H. st_swap clears pending_swap")

    # I. 禁止:与 ST 交换
    try:
        request_swap(state, "p1", "st")
        raise AssertionError
    except ValueError as e:
        assert "说书人不参与" in str(e), str(e)
    print("[PASS] I. cannot swap with ST")

    # J. 禁止:非 lobby 阶段
    state2 = GameState(room_code="EFGH", phase=Phase.DAY, day=1)
    state2.players = [Player(id="p1", name="A", seat=1), Player(id="p2", name="B", seat=2)]
    try:
        request_swap(state2, "p1", "p2")
        raise AssertionError
    except ValueError as e:
        assert "不能交换" in str(e) and "lobby" in str(e).lower() or "大厅" in str(e), str(e)
    print("[PASS] J. non-lobby phase rejected")

    # K. 同时只允许一个 pending_swap
    state = _setup()
    state = request_swap(state, "p1", "p2")
    try:
        request_swap(state, "p3", "p4")
        raise AssertionError
    except ValueError as e:
        assert "已有进行中" in str(e), str(e)
    print("[PASS] K. only one pending_swap at a time")

    # L. 禁止:与自己交换
    state = cancel_swap(state, "p1")
    try:
        request_swap(state, "p1", "p1")
        raise AssertionError
    except ValueError as e:
        assert "不能与自己" in str(e), str(e)
    print("[PASS] L. cannot swap with self")

    # M. cancel_swap 时非申请人/非 ST 拒绝
    state = request_swap(state, "p1", "p2")
    try:
        cancel_swap(state, "p3", is_st=False)
        raise AssertionError
    except ValueError as e:
        assert "申请发起人或说书人" in str(e), str(e)
    print("[PASS] M. non-applicant non-ST cannot cancel")

    # N. 无 pending_swap 时 accept/decline/cancel 拒绝
    state = cancel_swap(state, "p1")
    for op_name, op in [("accept", lambda s: accept_swap(s, "p2")),
                        ("decline", lambda s: decline_swap(s, "p2")),
                        ("cancel", lambda s: cancel_swap(s, "p1"))]:
        try:
            op(state)
            raise AssertionError(f"{op_name} should reject without pending_swap")
        except ValueError as e:
            assert "没有进行中的交换申请" in str(e), str(e)
    print("[PASS] N. accept/decline/cancel without pending_swap rejected")

    # O. swap_decline 后 pending_swap 清除,可以发起新的
    state = request_swap(state, "p1", "p2")
    state = decline_swap(state, "p2")
    state = request_swap(state, "p3", "p4")
    assert state.pending_swap.from_id == "p3"
    print("[PASS] O. decline then re-request works")

    # ---- 修复 1:玩家列表按 seat 排序 ----
    state = _setup()
    room = Room(code="ABCD")
    room.state = state
    # 故意按加入顺序添加,但 seat 跟加入顺序不一致
    rps = [
        RuntimePlayer(player=next(p for p in state.players if p.id == "p3"),
                       sid="s_p3"),
        RuntimePlayer(player=next(p for p in state.players if p.id == "p1"),
                       sid="s_p1"),
        RuntimePlayer(player=next(p for p in state.players if p.id == "st"),
                       sid="s_st"),
        RuntimePlayer(player=next(p for p in state.players if p.id == "p2"),
                       sid="s_p2"),
        RuntimePlayer(player=next(p for p in state.players if p.id == "p4"),
                       sid="s_p4"),
    ]
    for rp in rps:
        room.runtime_players[rp.id] = rp
    pub = room.list_players_public()
    # ST 在前 + 玩家按 seat 升序:p1(1), p2(2), p3(3), p4(4)
    ids = [p["id"] for p in pub]
    assert ids == ["st", "p1", "p2", "p3", "p4"], f"got {ids}"
    print("[PASS] P. list_players_public sorts ST first + players by seat")

    # 交换后顺序跟着变
    state = accept_swap(request_swap(state, "p1", "p4"), "p4")
    # p1.seat=4, p4.seat=1 → 顺序应变为 st, p4, p2, p3, p1
    room.state = state
    room.refresh_from_state()  # 让 runtime_players.player 引用更新
    pub = room.list_players_public()
    ids = [p["id"] for p in pub]
    assert ids == ["st", "p4", "p2", "p3", "p1"], f"got {ids}"
    print("[PASS] Q. after swap, player order reflects new seats")

    # ---- 修复 2:ended 阶段也允许交换 ----
    state2 = _setup(phase=Phase.ENDED)
    state2 = request_swap(state2, "p1", "p2")
    assert state2.pending_swap is not None
    state2 = accept_swap(state2, "p2")
    assert _seat(state2, "p1") == 2
    assert _seat(state2, "p2") == 1
    print("[PASS] R. swap works in ENDED phase (between games)")

    # st_swap 在 ended 也能用
    state2 = st_swap_seats(state2, "p3", "p4")
    assert _seat(state2, "p3") == 4
    assert _seat(state2, "p4") == 3
    print("[PASS] S. st_swap also works in ENDED phase")

    # 游戏中(day)依然拒绝
    state3 = _setup(phase=Phase.DAY)
    state3.players[0].seat = 0  # 保留 ST
    state3.phase = Phase.DAY
    try:
        request_swap(state3, "p1", "p2")
        raise AssertionError("should reject DAY phase")
    except ValueError as e:
        assert "不能交换座位" in str(e), str(e)
    print("[PASS] T. swap still rejected during DAY")

    print("\n[OK] smoke_swap_seats all tests passed")


if __name__ == "__main__":
    _run()
