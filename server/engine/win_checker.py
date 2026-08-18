"""胜负判定规则工具。

当前主流程不自动调用此模块,游戏胜负由说书人手动宣布；保留本模块供规则参考和未来可选模式使用。

阶段 1 使用简化规则:
- 恶魔死亡 -> 善良获胜
- 恶魔存活 且 邪恶存活人数 >= 善良存活人数 -> 邪恶获胜

阵营通过 state.script.roles 查找,不再依赖固定 RoleId 枚举。

特殊角色:无神论者(Atheist)
- BOTC 规则:无神论者在场时,ST 可以打破任意一条其他游戏规则
- 实现:在 check_winner 里直接返回 (None, "")——不自动判定胜负
- 由 ST 手动决定何时结束游戏(ST 可以照常调用 end_game 事件)
- 仅当「真实身份」(true_role)是 atheist 时才触发,Drunk 伪装成 atheist 不算
"""
from __future__ import annotations

from typing import Optional

from server.engine.game_state import Alignment, GameState, Player, PlayerStatus


def _is_evil(p: Player, state: GameState) -> bool:
    if p.true_role is None:
        return False
    team = state.script.get_role_team(p.true_role) if state.script else "fabled"
    return team in ("minion", "demon")


def _role_team(p: Player, state: GameState) -> str:
    """返回角色阵营字符串(townsfolk/outsider/minion/demon/fabled)。"""
    if p.true_role is None or state.script is None:
        return "fabled"
    return state.script.get_role_team(p.true_role)


def _atheist_in_play(state: GameState) -> bool:
    """无神论者是否在本局游戏中(无论死活,Drunk 伪装的不算)。

    BOTC 规则延伸:无神论者在场会导致场上没有恶魔,所以本局全程都没有可触发的
    自动结束条件(标准胜负判定都不成立)。即使真正的无神论者中途死亡,游戏也
    不会自动结束——因为场上始终没有恶魔,胜利条件无法满足,需要 ST 手动
    决定何时结束(典型:无神论者被处决 = 好人胜)。
    """
    for p in state.players:
        if p.is_storyteller:
            continue
        if p.true_role == "atheist":
            return True
    return False


def check_winner(state: GameState) -> tuple[Optional[Alignment], str]:
    """返回 (winner, reason)。无胜者则 (None, "")。"""
    # 规则 0: 无神论者在场 → 不自动结束,由 ST 决定
    if _atheist_in_play(state):
        return (None, "")

    alive_players = [p for p in state.players if p.status == PlayerStatus.ALIVE and not p.is_storyteller]
    if not alive_players:
        # 所有人死了(极端情况) -> 邪恶胜
        return (Alignment.EVIL, "所有玩家均死亡")

    demons_alive = [p for p in alive_players if _role_team(p, state) == "demon"]
    good_alive = [p for p in alive_players if _role_team(p, state) in ("townsfolk", "outsider")]
    evil_alive = [p for p in alive_players if _role_team(p, state) in ("minion", "demon")]

    # 规则 1: 恶魔全死 -> 善良胜
    if not demons_alive:
        return (Alignment.GOOD, "所有恶魔已死亡")

    # 规则 2: 存活 <= 2 人且场上仍有恶魔 -> 邪恶胜
    if len(alive_players) <= 2:
        return (Alignment.EVIL, f"仅剩 {len(alive_players)} 人存活,恶魔仍在场上")

    return (None, "")