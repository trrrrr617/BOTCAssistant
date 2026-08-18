"""Stage 4+: 死亡玩家投票限制(覆盖还原规则)回归测试。

核心规则:
  - dead_vote_used 追踪"当前真正计入结算的 YES 票数",不是历史总次数。
  - 投 YES:消耗一次额度(dead_vote_used = True);若 dead_vote_used 已为 True 且不是
    在同一提名上覆盖自己之前的 YES,则拒绝(防止给多个提名同时投 YES)。
  - 投 NO:不消耗额度;若覆盖的是自己之前在同一提名上的 YES,则把 dead_vote_used
    还原为 False(因为那个 YES 已不计入结算,等于那次"消耗"白给了)。
  - 活人玩家:无限制。
  - dead_vote_used 由 st_kill_player 在每次新死亡时重置。

效果:死亡玩家虽然可以"反复操作"(YES A -> NO A -> YES B),但同一时间只能有一个
"真正计入结算"的 YES,等价于"死亡角色只能给一个被提名者投赞成票"的官方规则。
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import eventlet  # noqa
eventlet.monkey_patch()

from server.engine.game_state import GameState, Player, PlayerStatus, Phase, Nomination
from server.engine.state_machine import cast_vote


def _setup():
    players = [
        Player(id="st", name="ST", seat=0, is_storyteller=True),
        Player(id="p1", name="A", seat=1),
        Player(id="p2", name="B", seat=2),
        Player(id="p3", name="C", seat=3),
        Player(id="p4", name="D", seat=4),
        Player(id="p5", name="E", seat=5, status=PlayerStatus.DEAD),
    ]
    state = GameState(room_code="ABCD", phase=Phase.DAY, day=1, players=players)
    state.current_nominations = [
        Nomination(id="n1", nominator_id="p1", nominee_id="p2"),
        Nomination(id="n2", nominator_id="p3", nominee_id="p4"),
    ]
    return state, players


def _vote_of(state, nom_id, voter_id):
    nom = next(n for n in state.current_nominations if n.id == nom_id)
    return next((v for v in nom.votes if v.voter_id == voter_id), None)


def _p5(state):
    """cast_vote 返回深拷贝,需按 id 重新拿最新引用。"""
    return next(p for p in state.players if p.id == "p5")


def _run():
    # ---------- 场景 A:死投反对永远不消耗 ----------
    state, _ = _setup()
    state = cast_vote(state, "p5", "n1", value=False)
    assert _p5(state).dead_vote_used is False
    state = cast_vote(state, "p5", "n2", value=False)
    assert _p5(state).dead_vote_used is False
    print("[PASS] A. dead NO on any nom: never consume")

    # ---------- 场景 B:死投赞成消耗,再投另一个赞成被拒 ----------
    state = cast_vote(state, "p5", "n1", value=True)
    assert _p5(state).dead_vote_used is True
    assert _vote_of(state, "n1", "p5").value is True
    try:
        cast_vote(state, "p5", "n2", value=True)
        raise AssertionError("should reject second YES")
    except ValueError as e:
        assert "本轮死亡期间" in str(e), str(e)
    print("[PASS] B. dead YES on A then YES on B: rejected")

    # ---------- 场景 C(关键):YES 改 NO 覆盖 → 还原额度 ----------
    state = cast_vote(state, "p5", "n1", value=False)
    assert _p5(state).dead_vote_used is False, "覆盖 NO 时应还原 dead_vote_used"
    assert _vote_of(state, "n1", "p5").value is False
    print("[PASS] C. dead YES -> NO on same nom: dead_vote_used RESETS to False")

    # ---------- 场景 D:还原后可以投另一个 YES ----------
    state = cast_vote(state, "p5", "n2", value=True)
    assert _p5(state).dead_vote_used is True
    assert _vote_of(state, "n2", "p5").value is True
    print("[PASS] D. after reset, dead can YES on a different nom")

    # ---------- 场景 E:同提名覆盖 YES 不算新消耗 ----------
    state = cast_vote(state, "p5", "n2", value=True)
    assert _p5(state).dead_vote_used is True  # 没变,仍是 True
    print("[PASS] E. dead re-YES on same nom: no double consume")

    # ---------- 场景 F:NO 改 YES 消耗 ----------
    # 先清场:重置 nom1 为 NO
    state = cast_vote(state, "p5", "n2", value=False)
    assert _p5(state).dead_vote_used is False  # 覆盖 YES 还原
    # 现在死投赞成 nom1
    state = cast_vote(state, "p5", "n1", value=True)
    assert _p5(state).dead_vote_used is True
    print("[PASS] F. dead NO -> YES: consume")

    # ---------- 场景 G:活人不受限制 ----------
    state2, _ = _setup()
    state2 = cast_vote(state2, "p1", "n1", value=True)
    state2 = cast_vote(state2, "p1", "n2", value=True)
    print("[PASS] G. alive player: no dead_vote_used limit")

    # ---------- 场景 H:反复横跳 YES/NO 永远只算最后一个 YES ----------
    state3, _ = _setup()
    state3 = cast_vote(state3, "p5", "n1", value=True)   # YES n1, dead_vote_used=True
    state3 = cast_vote(state3, "p5", "n1", value=False)  # NO n1, 还原
    state3 = cast_vote(state3, "p5", "n2", value=True)   # YES n2, 消耗
    assert _p5(state3).dead_vote_used is True
    # 此时 YES n2 仍计入结算,所以投 YES n1 仍被拒
    try:
        cast_vote(state3, "p5", "n1", value=True)
        raise AssertionError("should reject")
    except ValueError:
        pass
    # 还原 n2 后才能 YES n1
    state3 = cast_vote(state3, "p5", "n2", value=False)
    assert _p5(state3).dead_vote_used is False
    state3 = cast_vote(state3, "p5", "n1", value=True)
    assert _p5(state3).dead_vote_used is True
    print("[PASS] H. flip-flop only last YES counts toward dead_vote_used")

    # ---------- 场景 I:复活后限制解除 ----------
    state4, _ = _setup()
    _p5(state4).status = PlayerStatus.ALIVE
    state4 = cast_vote(state4, "p5", "n1", value=True)
    state4 = cast_vote(state4, "p5", "n2", value=True)
    assert _vote_of(state4, "n1", "p5").value is True
    assert _vote_of(state4, "n2", "p5").value is True
    print("[PASS] I. alive (revived) player: no limit")

    # ---------- 场景 J:再次死亡后由 st_kill_player 重置,可重新投 ----------
    _p5(state4).status = PlayerStatus.DEAD
    _p5(state4).dead_vote_used = False  # 模拟 st_kill_player 的重置
    state4 = cast_vote(state4, "p5", "n1", value=True)
    assert _p5(state4).dead_vote_used is True
    print("[PASS] J. after re-kill (dead_vote_used reset by st_kill_player): can YES again")

    print("\n[OK] smoke_dead_vote_no_consume all tests passed")


if __name__ == "__main__":
    _run()
