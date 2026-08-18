"""角色系统 - 阶段 2 详细实现待补。阶段 1 仅使用分发模块。"""
from __future__ import annotations

from server.roles.distribution import (
    distribute_roles,
    get_distribution_counts,
    TOWNSFOLK_POOL,
    OUTSIDER_POOL,
    MINION_POOL,
    DEMON_POOL,
)

__all__ = [
    "distribute_roles",
    "get_distribution_counts",
    "TOWNSFOLK_POOL",
    "OUTSIDER_POOL",
    "MINION_POOL",
    "DEMON_POOL",
]
