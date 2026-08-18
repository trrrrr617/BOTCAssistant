"""角色分发:根据人数从 23 角色池随机抽取。

参考需求文档 5-15 人配比表。阶段 1 不处理
`+1 outsider` / `+damsel` / `[-1 outsider]` 等配比修正标记,
角色行为钩子由阶段 2 的 `distribution_modifier` 实现。
"""
from __future__ import annotations

import random
from typing import TypedDict

from server.engine.game_state import RoleId


# ---- 配比表(根据需求文档)----
class RoleCounts(TypedDict):
    townsfolk: int
    outsider: int
    minion: int
    demon: int


_DISTRIBUTION_TABLE: dict[int, RoleCounts] = {
    5:  {"townsfolk": 3, "outsider": 0, "minion": 1, "demon": 1},
    6:  {"townsfolk": 3, "outsider": 1, "minion": 1, "demon": 1},
    7:  {"townsfolk": 5, "outsider": 0, "minion": 1, "demon": 1},
    8:  {"townsfolk": 5, "outsider": 1, "minion": 1, "demon": 1},
    9:  {"townsfolk": 5, "outsider": 2, "minion": 1, "demon": 1},
    10: {"townsfolk": 7, "outsider": 0, "minion": 2, "demon": 1},
    11: {"townsfolk": 7, "outsider": 1, "minion": 2, "demon": 1},
    12: {"townsfolk": 7, "outsider": 2, "minion": 2, "demon": 1},
    13: {"townsfolk": 9, "outsider": 0, "minion": 3, "demon": 1},
    14: {"townsfolk": 9, "outsider": 1, "minion": 3, "demon": 1},
    15: {"townsfolk": 9, "outsider": 2, "minion": 3, "demon": 1},
}


def get_distribution_counts(n_players: int) -> RoleCounts:
    """根据玩家数返回 4 类角色的人数。"""
    if n_players < 5 or n_players > 15:
        raise ValueError(f"玩家数必须在 5-15 之间,得到 {n_players}")
    return _DISTRIBUTION_TABLE[n_players]


# ---- 角色池(夜半狂欢剧本的 23 个角色)----
TOWNSFOLK_POOL: list[RoleId] = [
    RoleId.NOBLE,
    RoleId.SNAKE_CHARMER,
    RoleId.BALLOONIST,
    RoleId.MOUNTAIN_MAN,
    RoleId.ENGINEER,
    RoleId.FISHERMAN,
    RoleId.PROFESSOR,
    RoleId.SCHOLAR,
    RoleId.AMNESIAC,
    RoleId.FARMER,
    RoleId.CANNIBAL,
    RoleId.POPPY_GROWER,
    RoleId.ATHEIST,
]
OUTSIDER_POOL: list[RoleId] = [
    RoleId.DRUNK,
    RoleId.BARBER,
    RoleId.DAMSEL,
    RoleId.GOLEM,
]
MINION_POOL: list[RoleId] = [
    RoleId.POISONER,
    RoleId.LUNATIC,
    RoleId.CERENOVUS,
    RoleId.HAG,
]
DEMON_POOL: list[RoleId] = [
    RoleId.HADJIYA,
    RoleId.LLEECH,
]


class DistributionResult(TypedDict):
    townsfolk: list[RoleId]
    outsider: list[RoleId]
    minion: list[RoleId]
    demon: RoleId


def distribute_roles(n_players: int, *, rng: random.Random | None = None) -> DistributionResult:
    """随机抽取 n_players 数量的角色分布。"""
    rng = rng or random.Random()
    counts = get_distribution_counts(n_players)
    return {
        "townsfolk": rng.sample(TOWNSFOLK_POOL, counts["townsfolk"]),
        "outsider":  rng.sample(OUTSIDER_POOL, counts["outsider"]),
        "minion":    rng.sample(MINION_POOL, counts["minion"]),
        "demon":     rng.choice(DEMON_POOL),
    }


def flat_role_list(dist: DistributionResult) -> list[RoleId]:
    """扁平化所有角色为一个可洗牌的列表(恶魔只 1 个)。"""
    return list(dist["townsfolk"]) + list(dist["outsider"]) + list(dist["minion"]) + [dist["demon"]]
