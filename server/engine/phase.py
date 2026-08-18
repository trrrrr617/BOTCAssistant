"""游戏阶段枚举与转换规则。"""
from __future__ import annotations

from enum import Enum


class Phase(str, Enum):
    """游戏阶段。"""

    LOBBY = "lobby"                       # 大厅(等待玩家加入)
    SETUP = "setup"                       # 角色分发准备
    FIRST_NIGHT = "first_night"           # 首夜
    DAY_DISCUSSION = "day_discussion"     # 白天讨论(计时器跑,无提名可发起)
    DAY = "day"                           # 白天提名/投票阶段(ST 手动开启)
    NOMINATION = "nomination"             # 兼容旧枚举(未使用,保留)
    VOTING = "voting"                     # 兼容旧枚举(未使用,保留)
    EXECUTION = "execution"               # 兼容旧枚举(未使用,保留)
    NIGHT = "night"                       # 常规夜
    ENDED = "ended"                       # 结束


# 阶段合法转换图(单向)
_VALID_TRANSITIONS: dict[Phase, set[Phase]] = {
    Phase.LOBBY: {Phase.SETUP},
    Phase.SETUP: {Phase.FIRST_NIGHT},
    Phase.FIRST_NIGHT: {Phase.DAY_DISCUSSION},  # 首夜 → 白天讨论
    Phase.DAY_DISCUSSION: {Phase.DAY, Phase.NIGHT},  # 开始提名 / 直接入夜
    Phase.DAY: {Phase.NIGHT},  # 结束白天入夜(提名结算是 DAY 内部动作,不切换阶段)
    Phase.NIGHT: {Phase.DAY_DISCUSSION, Phase.ENDED},
    # ENDED 允许重开 → SETUP(同房间玩家身份重置)
    Phase.ENDED: {Phase.SETUP},
}


class PhaseTransitionError(RuntimeError):
    """非法阶段转换。"""


def can_transition(from_: Phase, to: Phase) -> bool:
    return to in _VALID_TRANSITIONS.get(from_, set())


def assert_transition(from_: Phase, to: Phase) -> None:
    if not can_transition(from_, to):
        raise PhaseTransitionError(
            f"非法阶段转换: {from_.value} -> {to.value}"
        )
