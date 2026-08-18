"""状态机:负责阶段推进的核心业务逻辑。

阶段 1 流程:
  LOBBY → SETUP → FIRST_NIGHT → DAY ↔ NIGHT
  DAY →(手动结束提名阶段)→ 处理提名(可能处决)→ NIGHT
  由说书人手动宣布胜负并结束游戏

提名阶段规则(血染钟楼标准):
  - 一个阶段可以有多次提名,并行进行
  - 每名玩家最多提名 1 人
  - 每人最多被提名 1 次
  - 每名玩家对每个有效提名各投一票
  - ST 手动点击「结束提名阶段」统一计票
  - 结算:在 yes 票数 >= alive/2 的提名中,yes 票数最多者处决(平局先提名的赢)
"""
from __future__ import annotations

import random
import time
import uuid
from typing import Optional

from server.engine.game_state import (
    GameState,
    Nomination,
    Note,
    PendingSwap,
    Phase,
    Player,
    PlayerStatus,
    RoleId,
    Vote,
    role_display_name,
)
from server.engine.phase import assert_transition
from server.engine.script import Script, make_legacy_compat_script


# ---- 日志辅助 ----

def _log(
    state: GameState,
    text: str,
    kind: str = "",
    *,
    visibility: str | None = None,
) -> GameState:
    """在 state.log 追加一条记录。"""
    if state.log is None:
        state.log = []
    entry = {"ts": time.time(), "text": text, "kind": kind}
    if visibility:
        entry["visibility"] = visibility
    state.log.append(entry)
    return state


def _reset_nomination_phase(state: GameState) -> None:
    """阶段结束时清空提名相关集合(不通过 deep copy,直接清空 state 的字段)。"""
    state.current_nominations = []
    state.nominated_in_phase = set()
    state.nominated_as_target = set()
    state.passed_in_phase = set()


# ---- 角色分发 ----

# 标准 BOTC 分布表(无 modifier 时):n_players -> (T, O, M, D)
_BASE_DISTRIBUTION: dict[int, tuple[int, int, int, int]] = {
    5:  (3, 0, 1, 1),
    6:  (3, 1, 1, 1),
    7:  (5, 0, 1, 1),
    8:  (5, 1, 1, 1),
    9:  (5, 2, 1, 1),
    10: (7, 0, 2, 1),
    11: (7, 1, 2, 1),
    12: (7, 2, 2, 1),
    13: (9, 0, 2, 1),
    14: (9, 1, 2, 1),
    15: (9, 2, 2, 1),
}


def compute_distribution(n_players: int, script: Script) -> dict[str, int]:
    """返回基础配比(modifier 不在这里应用,只按 n_players 查表)。

    Modifier(outsider_mod / minion_mod / demon_mod)是在「持有该 modifier 的角色
    实际被抽中」时才生效,这条规则由 pick_roles 在抽签阶段负责——而不是把所有
    角色定义的 modifier 累加后再选人。否则会出现:即使某个带 modifier 的角色
    根本未被选中,它的 modifier 也会污染全场的配比,极端情况下会把恶魔/爪牙
    数量推到 0,导致场上没有邪恶角色。
    """
    if n_players not in _BASE_DISTRIBUTION:
        raise ValueError(f"玩家数 {n_players} 不在 5-15 范围")
    base_t, base_o, base_m, base_d = _BASE_DISTRIBUTION[n_players]
    return {"townsfolk": base_t, "outsider": base_o, "minion": base_m, "demon": base_d}


class RerollNeeded(Exception):
    """assign_roles 内部:整局无可行解时抛出,触发外层重随。"""


def _pick_n_from_team(
    team: str,
    n: int,
    roles_by_id: dict[str, ScriptRole],
    in_play: set[str],
    rng: random.Random,
) -> list[str]:
    """从指定阵营随机抽 n 个角色(排除已在场的)。池不足直接抛错。"""
    pool = [r for r in roles_by_id.values() if r.team == team and r.id not in in_play]
    if len(pool) < n:
        raise ValueError(
            f"角色池不足:{team} 阵营需要 {n} 个,池子只剩 {len(pool)} 个。"
            f"请补全脚本(modifier / requires 触发的阵营必须有候选)。"
        )
    rng.shuffle(pool)
    return [r.id for r in pool[:n]]


def _required_by_others(in_play: set[str], roles_by_id: dict[str, ScriptRole]) -> set[str]:
    """返回「被当前 in-play 角色 requires 的所有 ID」集合(这些角色不可被剔除)。"""
    reqs: set[str] = set()
    for rid in in_play:
        r = roles_by_id.get(rid)
        if r:
            reqs.update(r.requires)
    return reqs


def _has_own_modifier(rid: str, roles_by_id: dict[str, ScriptRole]) -> bool:
    """角色自身是否带 modifier(被剔除时优先保留带 modifier 的)。"""
    r = roles_by_id[rid]
    return (r.outsider_mod + r.minion_mod + r.demon_mod) != 0


def pick_roles(script: Script, n_players: int, rng: random.Random, max_iter: int = 20) -> list[str]:
    """通用角色抽取算法(ST 提议的 v2 抽象)。

    设计原则:
      - 4 个阵营(T/O/M/D)完全平行,任何 role 都可以带 outsider_mod/minion_mod/demon_mod
      - **T 是调节剂**:`T = N - O - M - D`(不需要单独的 townsfolk_mod)
      - 任何 role 都可以 requires 其他角色,任何 role 都可以 replace_with
      - 未来加新角色(恶魔-1、爪牙+N、酒鬼-外来者)无需改算法,只需加新 role

    算法:
      Phase 1: 按基础配比抽非 T(O/M/D),然后用「调节剂」公式算出 T 数,再抽 T
      Phase 2: 迭代直到稳定
        (a) requires:被抽中角色 requires 的 ID 强制加入
        (b) 重新计算 target(O = base_o + Σoutsider_mod, 同理 M/D;T = N - O - M - D)
        (c) 调整非 T 阵营(可补可减,例如 demon_mod=-1 会触发削减)
        (d) 调整 T(根据「调节剂」公式)
    """
    if n_players not in _BASE_DISTRIBUTION:
        raise ValueError(f"玩家数 {n_players} 不在 5-15 范围")
    base_t, base_o, base_m, base_d = _BASE_DISTRIBUTION[n_players]
    roles_by_id = {r.id: r for r in script.roles}

    def compute_target(picked: dict[str, list[str]], in_play: set[str]) -> dict[str, int]:
        """根据当前 picked 计算各阵营目标数。T 由 N - 其他三者 推导。"""
        bonus_o = sum(roles_by_id[rid].outsider_mod for rid in in_play if rid in roles_by_id)
        bonus_m = sum(roles_by_id[rid].minion_mod   for rid in in_play if rid in roles_by_id)
        bonus_d = sum(roles_by_id[rid].demon_mod    for rid in in_play if rid in roles_by_id)
        o = max(0, base_o + bonus_o)
        m = max(0, base_m + bonus_m)
        d = max(0, base_d + bonus_d)
        t = max(0, n_players - o - m - d)  # T 是调节剂
        return {"townsfolk": t, "outsider": o, "minion": m, "demon": d}

    # Phase 1: 抽 base 非 T + 推算 T
    picked: dict[str, list[str]] = {team: [] for team in ("townsfolk", "outsider", "minion", "demon")}
    in_play: set[str] = set()

    for team, n_pick in (("outsider", base_o), ("minion", base_m), ("demon", base_d)):
        picked[team] = _pick_n_from_team(team, n_pick, roles_by_id, in_play, rng)
        in_play.update(picked[team])

    target = compute_target(picked, in_play)
    picked["townsfolk"] = _pick_n_from_team(
        "townsfolk", target["townsfolk"], roles_by_id, in_play, rng
    )
    in_play.update(picked["townsfolk"])

    # Phase 2: 迭代
    for _ in range(max_iter):
        prev_in_play = set(in_play)

        # (a) requires 链
        for rid in list(in_play):
            r = roles_by_id.get(rid)
            if r is None:
                continue
            for req_id in r.requires:
                if req_id in in_play:
                    continue
                req_r = roles_by_id.get(req_id)
                if req_r is None:
                    raise ValueError(
                        f"角色 {rid} 的 requires 指向不存在的角色: {req_id}"
                    )
                if len(in_play) > n_players + 10:
                    raise ValueError(
                        f"角色 {rid} 的 requires 链可能存在循环,已添加 {len(in_play)} 角色仍不收敛"
                    )
                picked[req_r.team].append(req_id)
                in_play.add(req_id)

        # (b) 重新计算 target
        target = compute_target(picked, in_play)

        # (c) 调整非 T 阵营(支持削减,例如 demon_mod=-1 把 demon 减到 0)
        for team in ("outsider", "minion", "demon"):
            diff = target[team] - len(picked[team])
            if diff > 0:
                new_ids = _pick_n_from_team(team, diff, roles_by_id, in_play, rng)
                picked[team].extend(new_ids)
                in_play.update(new_ids)
            elif diff < 0:
                excess = -diff
                reqs = _required_by_others(in_play, roles_by_id)
                removable = [
                    rid for rid in picked[team]
                    if rid not in reqs and not _has_own_modifier(rid, roles_by_id)
                ]
                if len(removable) < excess:
                    # 分析为什么减不掉,给出可操作的错误信息
                    locked_by_requires = [rid for rid in picked[team] if rid in reqs]
                    has_modifier = [rid for rid in picked[team] if _has_own_modifier(rid, roles_by_id)]
                    reasons = []
                    if locked_by_requires:
                        reasons.append(f"被 requires 锁住:{locked_by_requires}")
                    if has_modifier:
                        reasons.append(f"自身带 modifier:{has_modifier}")
                    raise ValueError(
                        f"无法把 {team} 从 {len(picked[team])} 减到目标 {target[team]}:"
                        f"需要削减 {excess} 个但非必要角色只剩 {len(removable)} 个。"
                        f"原因:{'; '.join(reasons) or '未知'}。"
                        f"请检查脚本:可能某角色的 modifier 与另一角色的 requires 冲突。"
                    )
                rng.shuffle(removable)
                for rid in removable[:excess]:
                    picked[team].remove(rid)
                    in_play.discard(rid)

        # (d) 调整 T(调节剂:总数减其他三者)
        diff_t = target["townsfolk"] - len(picked["townsfolk"])
        if diff_t > 0:
            new_ids = _pick_n_from_team("townsfolk", diff_t, roles_by_id, in_play, rng)
            picked["townsfolk"].extend(new_ids)
            in_play.update(new_ids)
        elif diff_t < 0:
            excess = -diff_t
            reqs = _required_by_others(in_play, roles_by_id)
            removable = [
                rid for rid in picked["townsfolk"]
                if rid not in reqs and not _has_own_modifier(rid, roles_by_id)
            ]
            if len(removable) < excess:
                locked_by_requires = [rid for rid in picked["townsfolk"] if rid in reqs]
                has_modifier = [rid for rid in picked["townsfolk"] if _has_own_modifier(rid, roles_by_id)]
                reasons = []
                if locked_by_requires:
                    reasons.append(f"被 requires 锁住:{locked_by_requires}")
                if has_modifier:
                    reasons.append(f"自身带 modifier:{has_modifier}")
                raise ValueError(
                    f"无法把 townsfolk 从 {len(picked['townsfolk'])} 减到目标 {target['townsfolk']}:"
                    f"需要削减 {excess} 个但非必要角色只剩 {len(removable)} 个。"
                    f"原因:{'; '.join(reasons) or '未知'}。"
                )
            rng.shuffle(removable)
            for rid in removable[:excess]:
                picked["townsfolk"].remove(rid)
                in_play.discard(rid)

        # 收敛
        if in_play == prev_in_play:
            break

    if len(in_play) != n_players:
        raise ValueError(
            f"无法凑出 {n_players} 人,实际 {len(in_play)}"
        )

    flat: list[str] = []
    for cat in ("outsider", "minion", "demon", "townsfolk"):
        flat.extend(picked[cat])
    rng.shuffle(flat)
    return flat


def pick_roles_with_retry(
    script: Script,
    n_players: int,
    *,
    seed: Optional[int] = None,
    max_retries: int = 20,
) -> tuple[list[str], int]:
    """pick_roles 的自动重试版本:遇到合法冲突(requires/modifier 互斥)自动换 seed 重试。

    当脚本同时有:
      - T 角色带 outsider_mod=+1,要求 N 个 outsider
      - 另一个 T 角色带 outsider_mod=-10,要求 0 outsider
      - 还要有某 T 角色 requires 一个 outsider
    之类的冲突,普通 pick_roles 会直接抛 ValueError。
    这个 wrapper 换 seed 重新抽(随机种子不同,可能避开冲突),max_retries 次都失败才报错。

    Returns: (角色 ID 列表, 最终用到的 seed)
    """
    last_err: Optional[ValueError] = None
    for attempt in range(max_retries):
        attempt_seed = (seed + attempt) if seed is not None else None
        try:
            roles = pick_roles(script, n_players, random.Random(attempt_seed))
            return roles, attempt_seed if attempt_seed is not None else attempt
        except ValueError as e:
            last_err = e
    raise ValueError(
        f"已重试 {max_retries} 次仍遇到合法冲突,可能是脚本设计问题(不是随机问题)。\n"
        f"最后错误:{last_err}"
    )


def _pick_apparent_for_replace(
    role_def: ScriptRole,
    script: Script,
    true_roles_in_play: set[str],
    rng: random.Random,
) -> str:
    """为带 replace_with 的角色选 apparent_role。

    策略(ST 的方案 A 简化版):
      1) 从 role_def.replace_with 列表里选不在 true_roles_in_play 的(随机一个)
         — 同时排除 fabled 角色(传奇永远不在场,不能作为 apparent)
      2) 列表里所有可用角色都已出场 → 抛 RerollNeeded 让外层整局重随
         (不 fallback 到 replace_with 之外的角色,因为「替换为」是导入时 ST 显式声明的)
    """
    roles_by_id = {r.id: r for r in script.roles}
    candidates = [
        x for x in role_def.replace_with
        if x not in true_roles_in_play
        and (x not in roles_by_id or roles_by_id[x].team != "fabled")
    ]
    if candidates:
        return rng.choice(candidates)
    raise RerollNeeded(
        f"角色 {role_def.id} 的 replace_with={role_def.replace_with} 全部在场,需重随"
    )


def _compute_demon_disguises(
    state: GameState,
    script: Script,
    rng: random.Random,
) -> list[str]:
    """计算「恶魔的伪装」:开局后随机抽 N 个不在场的善良阵营角色。

    选取规则(全员共享一份,ST change_role 后不变):
      1) team ∈ {townsfolk, outsider}(善良阵营)
      2) replace_with 必须为空 —— 否则邪恶玩家用此身份时会露馅
         (例如酒鬼会替换为 balloonist,真正的 balloonist 并不会自己出场,
         邪恶玩家假装 balloonist 时没人替他挡刀)
      3) 不在 (true_roles ∪ apparent_roles) —— 已被任何人"占用"的角色不能再伪装
         (apparent_role 也要算在场:例如酒鬼变成气球驾驶员,气球驾驶员视为在场)

    N = (恶魔数 + 爪牙数) + 1

    候选不足 → 抛 ValueError(让 ST 重新配板)
    """
    roles_by_id = {r.id: r for r in script.roles}
    real_players = [p for p in state.players if not p.is_storyteller]

    # 在场集合:true_role ∪ apparent_role(参考用户说明:酒鬼→气球驾驶员视为气球驾驶员在场)
    in_play: set[str] = set()
    for p in real_players:
        if p.true_role:
            in_play.add(p.true_role)
        if p.apparent_role:
            in_play.add(p.apparent_role)

    # 候选:善良阵营 + replace_with 为空 + 不在场
    candidates = [
        r.id for r in script.roles
        if r.team in ("townsfolk", "outsider")
        and not r.replace_with
        and r.id not in in_play
    ]

    # 恶魔 + 爪牙总数(基于 true_role 计数,apparent_role 不算 — 我们关心真实的邪恶玩家数)
    evil_count = sum(
        1 for p in real_players
        if p.true_role and roles_by_id.get(p.true_role, None)
        and roles_by_id[p.true_role].team in ("demon", "minion")
    )
    n_needed = evil_count + 1

    if len(candidates) < n_needed:
        raise ValueError(
            f"恶魔的伪装候选不足:需要 {n_needed} 个(恶魔+爪牙+1),"
            f"但板子只剩 {len(candidates)} 个合法角色。"
            f"请补全脚本中的镇民/外来者,或减少带 replace_with 的角色。"
        )

    rng.shuffle(candidates)
    return candidates[:n_needed]


def assign_roles(state: GameState, *, seed: Optional[int] = None, max_retries: int = 10) -> GameState:
    """SETUP 阶段调用:根据当前 Script 随机分发角色。

    state.script 为 None 时,使用兼容默认板子(make_legacy_compat_script)。

    流程(用户提议的循环验证思路):
      1. pick_roles 迭代满足 base + modifier + requires
      2. 给每个玩家分 true_role
      3. 对带 replace_with 的角色,从「不在场」中选 apparent_role
         - 优先 replace_with 列表
         - 都已被占 → fallback 到全脚本不在场
         - 实在没空闲 → 整局重随(retry 直到成功或达 max_retries)

    标记:replace_with 的角色会写 is_replaced=True,ST 控制台显示「实际为 · 占位」红字
    """
    script = state.script or make_legacy_compat_script()
    n = len([p for p in state.players if not p.is_storyteller])

    for attempt in range(max_retries):
        attempt_seed = (seed + attempt) if seed is not None else None
        try:
            return _assign_roles_once(state, script, n, seed=attempt_seed)
        except RerollNeeded as e:
            if attempt == max_retries - 1:
                raise ValueError(f"已重随 {max_retries} 次仍找不到有效配置: {e}")
            continue
    raise ValueError("unreachable")


def _assign_roles_once(state: GameState, script: Script, n: int, *, seed: Optional[int]) -> GameState:
    state = state.model_copy(deep=True)
    if n < 5 or n > 15:
        raise ValueError(f"玩家数必须在 5-15 之间,当前 {n}")
    # 用 pick_roles_with_retry 替代裸 pick_roles:遇到合法冲突自动换 seed 重试
    role_list, _ = pick_roles_with_retry(script, n, seed=seed, max_retries=20)
    rng = random.Random(seed)  # 用同一个 seed 给 apparent_role 选,保持可复现

    real_players = [p for p in state.players if not p.is_storyteller]
    if len(real_players) < n:
        raise ValueError(f"真人玩家 {len(real_players)} 少于 {n}")

    # 第一遍:发 true_role
    for i, player in enumerate(real_players):
        if i >= len(role_list):
            continue
        player.true_role = role_list[i]
        player.apparent_role = role_list[i]

    # 记录真实在场的角色集合(用于 replace_with 选「不在场」)
    true_roles_in_play: set[str] = set(p.true_role for p in real_players if p.true_role)

    # 第二遍:对带 replace_with 的角色,分配 apparent_role
    for player in real_players:
        if player.true_role is None:
            continue
        role_def = next((r for r in script.roles if r.id == player.true_role), None)
        if not role_def or not role_def.replace_with:
            continue
        # 选一个不在 true_roles_in_play 的 apparent_role(优先 replace_with 列表)
        apparent = _pick_apparent_for_replace(role_def, script, true_roles_in_play, rng)
        player.apparent_role = apparent
        # 注意:apparent_role 不加入 true_roles_in_play,因为这只是「玩家以为的身份」,
        # 不会影响后续 replace_with 的判断(否则会形成假连锁)

    # 第三遍:计算「恶魔的伪装」列表(全员共享,开局后固定)
    # 必须在 replace_with 算完之后才能确定 in_play 集合
    state.demon_disguises = _compute_demon_disguises(state, script, rng)

    return state


# ---- 阶段推进 ----

def start_game(state: GameState) -> GameState:
    """ST 点击「开始游戏」:LOBBY → SETUP → FIRST_NIGHT(不停留,直接进入)。

    阶段 1 没有角色行动,但保留 FIRST_NIGHT 阶段以反映真实血染钟楼流程——
    说书人点击「开始游戏」后,游戏停留在首夜,等待 ST 处理完首夜(本阶段为空操作)
    后,点击「开始白天」进入 DAY 1。
    """
    state = state.model_copy(deep=True)
    assert_transition(state.phase, Phase.SETUP)
    state.phase = Phase.SETUP
    state = assign_roles(state)

    assert_transition(state.phase, Phase.FIRST_NIGHT)
    state.phase = Phase.FIRST_NIGHT
    # night 在这里不算入"已发生的夜晚"——end_day 第一次执行时 +1 才进入 night=1
    # 这样语义是:night=N 表示"第 N 个夜晚正在发生"
    # 首夜保持 night=0(尚未正式计为夜)
    _log(state, "游戏开始 · 身份已发放 · 首夜", "game_start")
    return state


def end_day(state: GameState) -> GameState:
    """ST 结束白天聊天:DAY → NIGHT(无提名或所有提名已结算)。"""
    state = state.model_copy(deep=True)
    assert_transition(state.phase, Phase.NIGHT)
    state.phase = Phase.NIGHT
    state.night += 1
    _reset_nomination_phase(state)
    state.chat_started_at = None
    _log(state, f"夜幕降临 · 第 {state.night} 夜开始", "night_start")
    return state


def begin_day(state: GameState) -> GameState:
    """ST 结束夜晚: NIGHT/FIRST_NIGHT → DAY_DISCUSSION(白天讨论)。

    计时器立即启动,但**不开放提名/投票**(避免一开局就被秒提名)。
    ST 之后可手动点「开始提名」切换到 DAY 阶段。
    """
    state = state.model_copy(deep=True)
    assert_transition(state.phase, Phase.DAY_DISCUSSION)
    state.phase = Phase.DAY_DISCUSSION
    state.day += 1
    state.chat_started_at = time.time()
    _reset_nomination_phase(state)
    _log(state, f"第 {state.day} 天开始 · 白天讨论", "day_start")
    return state


def begin_nomination(state: GameState) -> GameState:
    """ST 手动开始提名阶段: DAY_DISCUSSION → DAY。

    仅是阶段切换,不动 current_nominations / nominated_in_phase 等提名状态
    (避免 ST 点了又点后清空正在进行的提名)。
    """
    state = state.model_copy(deep=True)
    assert_transition(state.phase, Phase.DAY)
    state.phase = Phase.DAY
    _log(state, "🗳 ST 开放提名", "st_begin_nomination")
    return state


# ---- 提名 / 投票 / 结算 ----

def start_nomination(state: GameState, nominator_id: str, nominee_id: str) -> GameState:
    """玩家发起提名:
      - 每名玩家在本阶段最多提名 1 次
      - 每人最多被提名 1 次
      - 已 pass 的玩家不能再提名
    """
    state = state.model_copy(deep=True)
    if state.phase != Phase.DAY:
        raise ValueError(f"当前阶段 {state.phase.value} 不允许提名")

    if nominator_id in state.nominated_in_phase:
        raise ValueError("你已经提名过了,每阶段只能提名 1 人")
    if nominator_id in state.passed_in_phase:
        raise ValueError("你已经 pass 了,无法再提名")

    if nominee_id in state.nominated_as_target:
        raise ValueError("该玩家已被提名,每人每阶段只能被提名 1 次")

    nominator = state.find_player(nominator_id)
    nominee = state.find_player(nominee_id)
    if nominator is None or nominee is None:
        raise ValueError("玩家不存在")
    if nominator.status != PlayerStatus.ALIVE:
        raise ValueError("死亡玩家不能提名")
    if nominee.status != PlayerStatus.ALIVE:
        raise ValueError("不能提名已死亡的玩家")
    if nominator_id == nominee_id:
        raise ValueError("不能提名自己")

    nom = Nomination(
        id=uuid.uuid4().hex[:8],
        nominator_id=nominator_id,
        nominee_id=nominee_id,
        votes=[],
    )
    state.current_nominations.append(nom)
    state.nominated_in_phase.add(nominator_id)
    state.nominated_as_target.add(nominee_id)
    state.nomination_index += 1
    _log(state, f"{nominator.name} 提名 {nominee.name}", "nomination_start")
    return state


def pass_nomination(state: GameState, player_id: str) -> GameState:
    """玩家主动 pass(本阶段跳过提名)。已提名过的玩家不能再 pass。"""
    state = state.model_copy(deep=True)
    if state.phase != Phase.DAY:
        raise ValueError(f"当前阶段 {state.phase.value} 不允许 pass")
    if player_id in state.nominated_in_phase:
        raise ValueError("你已经提名了,无需 pass")
    if player_id in state.passed_in_phase:
        raise ValueError("你已经 pass 过了")

    player = state.find_player(player_id)
    if player is None:
        raise ValueError("玩家不存在")
    if player.status != PlayerStatus.ALIVE:
        raise ValueError("死亡玩家不能 pass")

    state.passed_in_phase.add(player_id)
    _log(state, f"{player.name} pass", "pass")
    return state


def cast_vote(state: GameState, voter_id: str, nomination_id: str, value: bool) -> GameState:
    """对指定提名投票(覆盖式)。

    死亡玩家的限制语义:
      - dead_vote_used 追踪的是"当前真正计入结算的赞成票数",不是历史总投票次数。
      - 投 YES:消耗一次额度(dead_vote_used = True);若 dead_vote_used 已为 True 且不是
        在同一提名上覆盖自己之前的 YES,则拒绝(防止把一票 YES 拆给多个提名)
      - 投 NO:不消耗额度;若覆盖的是自己之前在同一提名上的 YES,则把 dead_vote_used
        还原为 False(因为那个 YES 已经不计入结算,等于那次"消耗"白给了)
      - 活人玩家:无限制
      - dead_vote_used 由 st_kill_player 在每次新死亡时重置
    """
    state = state.model_copy(deep=True)
    if state.phase != Phase.DAY:
        raise ValueError(f"当前阶段 {state.phase.value} 不允许投票")

    nom = next((n for n in state.current_nominations if n.id == nomination_id), None)
    if nom is None:
        raise ValueError("提名不存在或已结算")
    if nom.resolved:
        raise ValueError("提名已结算")

    voter = state.find_player(voter_id)
    if voter is None:
        raise ValueError("投票人不存在")

    is_dead_voter = voter.status != PlayerStatus.ALIVE

    # 找死亡玩家在同一提名上的现有票(用于判断"覆盖")
    existing_vote = next(
        (v for v in nom.votes if v.voter_id == voter_id),
        None,
    )

    if is_dead_voter:
        if value:
            # 投 YES:
            #   - 若当前 dead_vote_used 已为 True,且不是覆盖自己同提名的 YES,则拒绝
            #     (说明之前已经在别的提名"实质地"投了 YES,本次不能再来一次)
            #   - 覆盖同提名的旧 YES 不算新消耗
            if voter.dead_vote_used and not (existing_vote and existing_vote.value):
                raise ValueError("你已在本轮死亡期间投过赞成票(且仍在计入结算),无法再投其它赞成票(投反对不限)")
            voter.dead_vote_used = True
        else:
            # 投 NO:
            #   - 不消耗额度
            #   - 但若覆盖的是自己之前的 YES,等于"那次消耗白给了",还原 dead_vote_used
            if existing_vote and existing_vote.value:
                voter.dead_vote_used = False

    # 覆盖之前的投票(同一玩家对同一提名的最新一次有效)
    nom.votes = [v for v in nom.votes if v.voter_id != voter_id]
    nom.votes.append(
        Vote(
            voter_id=voter_id,
            target_id=nom.nominee_id,
            value=value,
            is_dead_vote=is_dead_voter,
        )
    )
    return state


def end_nomination_phase(state: GameState) -> GameState:
    """ST 手动结束提名阶段:统一计票,处决 yes 最多且 >= alive/2 的人(若有)。"""
    state = state.model_copy(deep=True)
    if state.phase != Phase.DAY:
        raise ValueError(f"当前阶段 {state.phase.value} 不允许 end_nomination_phase")

    alive_players = [p for p in state.players if p.status == PlayerStatus.ALIVE and not p.is_storyteller]
    if not alive_players:
        return state
    alive_count = len(alive_players)
    threshold = alive_count / 2  # 达到 alive/2 票才有效

    # 第一遍:给所有提名计算票数并标记 met_threshold
    for nom in state.current_nominations:
        nom.closed = True
        nom.resolved = True
        yes = sum(1 for v in nom.votes if v.value)
        no = sum(1 for v in nom.votes if not v.value)
        nom.yes_count = yes
        nom.no_count = no
        nom.met_threshold = yes >= threshold and yes > 0
        nom.reason = f"赞成 {yes} 反对 {no}"

        # 为每条提名补一条详细日志:谁提名谁,赞成票都有谁
        nominator = state.find_player(nom.nominator_id)
        nominee = state.find_player(nom.nominee_id)
        nominator_name = nominator.name if nominator else "?"
        nominee_name = nominee.name if nominee else "?"
        yes_names = [
            state.find_player(v.voter_id).name
            for v in nom.votes
            if v.value and state.find_player(v.voter_id)
        ]
        no_names = [
            state.find_player(v.voter_id).name
            for v in nom.votes
            if not v.value and state.find_player(v.voter_id)
        ]
        yes_str = "、".join(yes_names) if yes_names else "无"
        no_str = "、".join(no_names) if no_names else "无"
        _log(
            state,
            f"{nominator_name} 提名 {nominee_name} · 赞成({yes}): {yes_str} · 反对({no}): {no_str}",
            "nomination_result",
        )

    # 第二遍:在 met_threshold 的提名中选 yes 最多的(平局取先提名的)
    best = None
    for nom in state.current_nominations:
        if nom.met_threshold and (best is None or nom.yes_count > best.yes_count):
            best = nom

    # 第三遍:标记 executed
    for nom in state.current_nominations:
        nom.executed = (nom is best)
        nom.passed = nom.executed  # 兼容旧字段

    if best is not None:
        nominee = state.find_player(best.nominee_id)
        if nominee is not None:
            nominee.status = PlayerStatus.DEAD
            _log(
                state,
                f"提名阶段结束 · {nominee.name} 被处决 (yes {best.yes_count}/{alive_count})",
                "execution",
            )
    else:
        if state.current_nominations:
            _log(
                state,
                f"提名阶段结束 · 无人达到 {alive_count/2:g} 票门槛,无人出局",
                "nomination_failed",
            )
        else:
            _log(state, "提名阶段结束 · 无人提名,无人出局", "nomination_failed")

    # 不重置 current_nominations,等 ST 推进到夜晚或下一天
    return state


# ---- 胜负判定辅助 ----

def check_and_finalize(state: GameState) -> GameState:
    """兼容旧调用,但胜负由说书人手动宣布,不再自动结束游戏。"""
    return state.model_copy(deep=True)


# ---- 说书人超级权限操作 ----

def st_kill_player(state: GameState, player_id: str) -> GameState:
    """ST 强制杀死一名玩家。重置该玩家的 dead_vote_used,允许新一轮单票。"""
    state = state.model_copy(deep=True)
    player = state.find_player(player_id)
    if player is None:
        raise ValueError("玩家不存在")
    if player.is_storyteller:
        raise ValueError("不能杀死说书人")
    player.status = PlayerStatus.DEAD
    player.dead_vote_used = False
    visibility = "night_st_only" if state.phase in (Phase.NIGHT, Phase.FIRST_NIGHT) else None
    _log(state, f"✝ ST 杀死了 {player.name}", "st_kill", visibility=visibility)
    return state


def st_revive_player(state: GameState, player_id: str) -> GameState:
    """ST 强制复活一名玩家。"""
    state = state.model_copy(deep=True)
    player = state.find_player(player_id)
    if player is None:
        raise ValueError("玩家不存在")
    if player.is_storyteller:
        raise ValueError("说书人不需要复活")
    player.status = PlayerStatus.ALIVE
    visibility = "night_st_only" if state.phase in (Phase.NIGHT, Phase.FIRST_NIGHT) else None
    _log(state, f"✦ ST 复活了 {player.name}", "st_revive", visibility=visibility)
    return state


def st_set_drunk(state: GameState, player_id: str, value: bool) -> GameState:
    """ST 设置玩家醉酒状态。"""
    state = state.model_copy(deep=True)
    player = state.find_player(player_id)
    if player is None:
        raise ValueError("玩家不存在")
    player.is_drunk = value
    label = "醉酒" if value else "解除醉酒"
    _log(state, f"🍷 ST 将 {player.name} 设为{label}", "st_status")
    return state


def st_set_poisoned(state: GameState, player_id: str, value: bool) -> GameState:
    """ST 设置玩家中毒状态。"""
    state = state.model_copy(deep=True)
    player = state.find_player(player_id)
    if player is None:
        raise ValueError("玩家不存在")
    player.is_poisoned = value
    label = "中毒" if value else "解除中毒"
    _log(state, f"☠ ST 将 {player.name} 设为{label}", "st_status")
    return state


def st_change_role(state: GameState, player_id: str, new_role: RoleId) -> GameState:
    """ST 强制变更某玩家的真实身份与表观身份。

    日志写入两处:
      - state.log:ST 通过完整 state.log 看到本次操作
      - target.private_log:仅被变更玩家在自己的私人日志中看到(其他玩家不会泄露)
    """
    state = state.model_copy(deep=True)
    player = state.find_player(player_id)
    if player is None:
        raise ValueError("玩家不存在")
    if player.is_storyteller:
        raise ValueError("不能变更说书人身份")
    # 传 state.script 让 role_display_name 能查自定义角色 ID 的中文名
    old_role_cn = role_display_name(player.true_role, script=state.script) if player.true_role else "无"
    new_role_cn = role_display_name(new_role, script=state.script)
    player.true_role = new_role
    player.apparent_role = new_role
    _log(state, f"🔄 ST 将 {player.name} 的身份从 {old_role_cn} 变更为 {new_role_cn}", "st_change_role")
    # 同时写入被变更玩家的私人日志(玩家在玩家页日志里能看到,其它玩家不可见)
    player.private_log.append({
        "ts": time.time(),
        "text": f"🔄 说书人将你的身份从 {old_role_cn} 变更为 {new_role_cn}",
        "kind": "st_change_role",
    })
    return state


def st_toggle_fabled(state: GameState, role_id: str, on: bool) -> GameState:
    """ST 切换某个传奇角色的在场/离场状态。

    校验:
      - role_id 必须在当前 script 的角色列表中
      - 该角色的 team 必须是 "fabled"
      - on=True 时加入 fabled_in_play;on=False 时移除

    日志:
      - 公开日志(玩家可见,kind: fabled_join / fabled_leave)
      - 文案:"📜 传奇角色【角色名】上场/离场",**不包含 notes**(能力说明在玩家页面「在场传奇」卡片里查看)
    """
    state = state.model_copy(deep=True)
    script = state.script
    if script is None:
        raise ValueError("尚未录入板子,无法操控传奇角色")
    role_def = next((r for r in script.roles if r.id == role_id), None)
    if role_def is None:
        raise ValueError(f"角色 {role_id} 不在当前板子中")
    if role_def.team != "fabled":
        raise ValueError(
            f"角色 {role_id}({role_def.name or role_id}) 不是传奇阵营,"
            f"无法通过本接口操控"
        )

    role_cn = role_def.name or role_id
    if on:
        if role_id in state.fabled_in_play:
            # 已经在场 — 幂等返回,不发日志避免噪音
            return state
        state.fabled_in_play.add(role_id)
        _log(state, f"📜 传奇角色【{role_cn}】上场了", "fabled_join")
    else:
        if role_id not in state.fabled_in_play:
            # 已经不在场 — 幂等返回
            return state
        state.fabled_in_play.discard(role_id)
        _log(state, f"📜 传奇角色【{role_cn}】离场", "fabled_leave")
    return state


def st_set_notes(state: GameState, player_id: str, notes_data: list[dict]) -> GameState:
    """ST 为某玩家设置多条自定义批注。传入的是 [{id?, text}] 列表,
    整个列表覆盖替换(用于增/删/改后客户端同步)。

    每条 Note 由客户端生成或保留原 ID;服务端补 created_at / updated_at。
    """
    state = state.model_copy(deep=True)
    player = state.find_player(player_id)
    if player is None:
        raise ValueError("玩家不存在")
    if player.is_storyteller:
        raise ValueError("不能说书人添加批注给说书人")

    now = time.time()
    new_notes: list[Note] = []
    for raw in notes_data:
        if not isinstance(raw, dict):
            continue
        text = (raw.get("text") or "").strip()
        if not text:
            continue  # 跳过空文本
        nid = raw.get("id") or uuid.uuid4().hex[:8]
        existing = next((n for n in player.st_notes if n.id == nid), None)
        if existing is not None:
            new_note = Note(
                id=nid,
                text=text,
                created_at=existing.created_at,
                updated_at=now if text != existing.text else existing.updated_at,
            )
        else:
            new_note = Note(id=nid, text=text, created_at=now)
        new_notes.append(new_note)

    # 同步日志:只在「有变化」时记录,避免噪音
    old_texts = sorted(n.text for n in player.st_notes)
    new_texts = sorted(n.text for n in new_notes)
    if old_texts != new_texts:
        if new_notes:
            added = len(new_notes) - len(player.st_notes)
            if added > 0:
                _log(state, f"📝 ST 为 {player.name} 添加了 {added} 条批注", "st_note")
            else:
                _log(state, f"📝 ST 更新了 {player.name} 的批注", "st_note")
        else:
            _log(state, f"📝 ST 清空了 {player.name} 的批注", "st_note")
    player.st_notes = new_notes
    return state


_LOG_VISIBILITY = ("st_only", "public", "private_to_player")


def st_add_log(
    state: GameState,
    text: str,
    visibility: str = "st_only",
    target_id: Optional[str] = None,
) -> GameState:
    """ST 手动追加一条活动日志,带可见范围:
      - st_only(默认):仅 ST 可见
      - public:所有玩家可见
      - private_to_player:仅特定玩家可见(需要 target_id)
    每条日志会在文本前标注可见范围前缀。
    """
    state = state.model_copy(deep=True)
    visibility = visibility or "st_only"
    if visibility not in _LOG_VISIBILITY:
        raise ValueError(f"无效可见范围: {visibility}")
    if not text or not text.strip():
        raise ValueError("日志内容不能为空")

    target_name = None
    if visibility == "private_to_player":
        target = state.find_player(target_id) if target_id else None
        if target is None:
            raise ValueError("目标玩家不存在")
        target_name = target.name

    prefix_map = {
        "st_only": "🔒 ST",
        "public": "📢 公开",
        "private_to_player": f"👤→{target_name}",
    }
    prefix = prefix_map[visibility]
    full_text = f"📌 [{prefix}] {text.strip()}"

    # kind:public 走 _PUBLIC_LOG_KINDS;其它只在 state.log 出现
    kind = "st_manual_log_public" if visibility == "public" else "st_manual_log"
    entry = {
        "ts": time.time(),
        "text": full_text,
        "kind": kind,
        "visibility": visibility,
    }
    if target_id:
        entry["target_id"] = target_id
    # 仅写入 state.log,玩家侧通过 _player_state_payload 中的 visibility 过滤
    # 即可获得该条目(不要同时 append 到 target.private_log,否则客户端会显示两条)
    state.log.append(entry)
    return state


# ---- 重开(同一房间,玩家不变) ----

def reset_game_for_rematch(state: GameState, *, seed: Optional[int] = None) -> GameState:
    """游戏结束后说书人发起重开:保留玩家列表(座位/姓名/说书人身份),
    重置所有游戏数据(身份/状态/提名/夜晚/批注/日志),重新分配角色。

    调用条件:state.phase == Phase.ENDED
    """
    state = state.model_copy(deep=True)
    if state.phase != Phase.ENDED:
        raise ValueError(f"当前阶段 {state.phase.value} 不允许重开(仅 ended 阶段)")

    real_players = [p for p in state.players if not p.is_storyteller]
    if len(real_players) < 5 or len(real_players) > 15:
        raise ValueError(f"玩家数必须在 5-15 之间,当前 {len(real_players)}")

    # 重置每个玩家的游戏数据(保留 id / name / seat / is_storyteller / notes)
    for p in state.players:
        p.status = PlayerStatus.ALIVE
        p.true_role = None
        p.apparent_role = None
        p.effective_role = None
        p.is_poisoned = False
        p.is_drunk = False
        p.has_used_ability = {}
        p.dead_vote_used = False
        p.st_notes = []
        p.player_notes = {}
        p.private_log = []
        # notes 字段(角色相关)一并清空
        p.notes = {}

    # 重新分配身份:复用 assign_roles(state) 以支持 Script.mod 与 replace_with(酒鬼)
    # state.script 还在(下面才清),所以这里会按当前 Script 的配比与酒鬼机制分发
    state = assign_roles(state, seed=seed)

    # 重置回合计数与全局状态
    state.day = 0
    state.night = 0
    state.winner = None
    state.win_reason = ""
    state.pending_info = []
    state.night_queue = []
    state.night_actions = []
    state.current_nominations = []
    state.nominated_in_phase = set()
    state.nominated_as_target = set()
    state.passed_in_phase = set()
    state.nomination_index = 0
    state.chat_started_at = None  # 首夜没有聊天计时
    state.chat_duration_sec = 300
    state.atheist_in_play = False
    state.atheist_rules_break_pending = False
    state.damsel_in_play = False
    state.damsel_player_id = None
    state.poppy_grower_alive = True
    state.spirit_of_ivory_used = False
    state.pending_deaths = []
    # 重开时清空传奇角色在场状态(传奇与初始默认一致:全部不在场)
    state.fabled_in_play = set()
    # 注意:不重置 state.script!保留原板子让:
    #   1. ST 控制台能继续显示正确的角色中文名(_roleNameOf 依赖 lastState.script)
    #   2. 新一局角色按相同板子抽取(可能 ST 想再玩一局一样的)
    # 如果 ST 想换板子,可以手动调 set_script 覆盖

    # 同 start_game:停留在首夜,由 ST 决定何时进入 DAY 1
    assert_transition(state.phase, Phase.SETUP)
    state.phase = Phase.SETUP
    assert_transition(state.phase, Phase.FIRST_NIGHT)
    state.phase = Phase.FIRST_NIGHT

    state.log = [{"ts": time.time(), "text": "游戏重开 · 身份已重新分发 · 首夜", "kind": "game_start"}]
    return state


# ---- 玩家私人日志与批注 ----

def player_add_log(state: GameState, player_id: str, text: str) -> GameState:
    """玩家追加一条私人日志。"""
    state = state.model_copy(deep=True)
    player = state.find_player(player_id)
    if player is None:
        raise ValueError("玩家不存在")
    player.private_log.append({"ts": time.time(), "text": text, "kind": "player_private"})
    return state


def player_send_to_st(state: GameState, player_id: str, text: str) -> GameState:
    """玩家发送一条消息给说书人。

    仅 ST 与发送者本人可见(发送者可在自己的日志中看到自己发的内容)。
    用于玩家私下提问、分享思路等场景。
    """
    state = state.model_copy(deep=True)
    player = state.find_player(player_id)
    if player is None:
        raise ValueError("玩家不存在")
    if player.is_storyteller:
        raise ValueError("说书人不需要发送给自己")
    if not text or not text.strip():
        raise ValueError("消息内容不能为空")

    text = text.strip()
    entry = {
        "ts": time.time(),
        "text": f"📨 [{player.name}] {text}",
        "kind": "player_to_st",
        "visibility": "private_to_st",
        "sender_id": player_id,
    }
    # 只写一份到 state.log,通过 _player_state_payload 过滤规则
    # 让 ST(st_state_update 看全部)和发送者(sender_id == player_id)都能看到。
    state.log.append(entry)
    return state


def player_set_notes(
    state: GameState,
    player_id: str,
    target_id: str,
    notes_data: list[dict],
) -> GameState:
    """玩家设置对另一玩家的多条私人批注。整列表覆盖替换。

    每条 Note 由客户端生成或保留原 ID;服务端补 created_at / updated_at。
    """
    state = state.model_copy(deep=True)
    player = state.find_player(player_id)
    if player is None:
        raise ValueError("玩家不存在")
    if state.find_player(target_id) is None:
        raise ValueError("目标玩家不存在")
    if player_id == target_id:
        raise ValueError("不能给自己写批注")

    now = time.time()
    new_notes: list[Note] = []
    existing_list = player.player_notes.get(target_id, [])
    for raw in notes_data:
        if not isinstance(raw, dict):
            continue
        text = (raw.get("text") or "").strip()
        if not text:
            continue
        nid = raw.get("id") or uuid.uuid4().hex[:8]
        existing = next((n for n in existing_list if n.id == nid), None)
        if existing is not None:
            new_note = Note(
                id=nid,
                text=text,
                created_at=existing.created_at,
                updated_at=now if text != existing.text else existing.updated_at,
            )
        else:
            new_note = Note(id=nid, text=text, created_at=now)
        new_notes.append(new_note)

    if new_notes:
        player.player_notes[target_id] = new_notes
    else:
        player.player_notes.pop(target_id, None)
    return state


# ---- Lobby 阶段:座位交换 ----

def _check_swap_eligible(state: GameState, a_id: str, b_id: str) -> tuple[Player, Player]:
    """校验两个玩家可以交换座位(同在 lobby,都不是 ST)。

    返回 (player_a, player_b)。
    失败抛 ValueError。
    """
    if state.phase not in (Phase.LOBBY, Phase.ENDED):
        raise ValueError(f"当前阶段 {state.phase.value} 不能交换座位(仅大厅或已结束阶段允许)")
    if a_id == b_id:
        raise ValueError("不能与自己交换")
    pa = state.find_player(a_id)
    pb = state.find_player(b_id)
    if pa is None:
        raise ValueError(f"玩家 {a_id} 不存在")
    if pb is None:
        raise ValueError(f"玩家 {b_id} 不存在")
    if pa.is_storyteller or pb.is_storyteller:
        raise ValueError("说书人不参与座位交换")
    return pa, pb


def request_swap(state: GameState, from_id: str, to_id: str) -> GameState:
    """玩家发起交换申请:from_id → to_id。

    校验:
      - 当前阶段是 LOBBY
      - from_id != to_id
      - 双方都不是 ST
      - 当前没有 pending_swap(同时只能有一个在途申请)
    """
    state = state.model_copy(deep=True)
    pa, pb = _check_swap_eligible(state, from_id, to_id)
    if state.pending_swap is not None:
        raise ValueError("已有进行中的交换申请,请先等待对方回应")
    state.pending_swap = PendingSwap(
        from_id=from_id,
        to_id=to_id,
        from_name=pa.name,
        to_name=pb.name,
    )
    _log(state, f"⇄ {pa.name} 向 {pb.name} 发起了座位交换申请", "swap_request")
    return state


def accept_swap(state: GameState, player_id: str) -> GameState:
    """被申请人接受交换。

    校验:
      - 当前阶段是 LOBBY
      - state.pending_swap 存在
      - player_id == pending_swap.to_id
    """
    state = state.model_copy(deep=True)
    if state.phase not in (Phase.LOBBY, Phase.ENDED):
        raise ValueError(f"当前阶段 {state.phase.value} 不能交换座位")
    if state.pending_swap is None:
        raise ValueError("当前没有进行中的交换申请")
    if state.pending_swap.to_id != player_id:
        raise ValueError("只有被申请的玩家能接受交换")

    # 校验双方仍存在(可能有人退出导致 from/to 失效)
    pa, pb = _check_swap_eligible(
        state, state.pending_swap.from_id, state.pending_swap.to_id
    )
    # 交换 seat
    pa.seat, pb.seat = pb.seat, pa.seat
    _log(state, f"⇄ 座位交换完成:{pa.name} ↔ {pb.name}", "swap_done")
    state.pending_swap = None
    return state


def decline_swap(state: GameState, player_id: str) -> GameState:
    """被申请人拒绝交换。

    校验:
      - 当前阶段是 LOBBY
      - state.pending_swap 存在
      - player_id == pending_swap.to_id(只能拒绝给自己的申请)
    """
    state = state.model_copy(deep=True)
    if state.phase not in (Phase.LOBBY, Phase.ENDED):
        raise ValueError(f"当前阶段 {state.phase.value} 不能操作交换")
    if state.pending_swap is None:
        raise ValueError("当前没有进行中的交换申请")
    if state.pending_swap.to_id != player_id:
        raise ValueError("只有被申请的玩家能拒绝交换")
    _log(state, f"⇄ {state.pending_swap.to_name} 拒绝了交换申请", "swap_decline")
    state.pending_swap = None
    return state


def cancel_swap(state: GameState, by_id: str, *, is_st: bool = False) -> GameState:
    """取消在途交换申请。申请人自己 / ST 都可以取消。"""
    state = state.model_copy(deep=True)
    if state.phase not in (Phase.LOBBY, Phase.ENDED):
        raise ValueError(f"当前阶段 {state.phase.value} 不能操作交换")
    if state.pending_swap is None:
        raise ValueError("当前没有进行中的交换申请")
    if not is_st and state.pending_swap.from_id != by_id:
        raise ValueError("只有申请发起人或说书人可以取消")
    _log(state, "⇄ 交换申请已取消", "swap_cancel")
    state.pending_swap = None
    return state


def st_swap_seats(state: GameState, a_id: str, b_id: str) -> GameState:
    """说书人强制交换两个玩家的座位(直接执行,无需对方同意)。"""
    state = state.model_copy(deep=True)
    pa, pb = _check_swap_eligible(state, a_id, b_id)
    # 强制交换会清掉在途申请(避免冲突)
    pa.seat, pb.seat = pb.seat, pa.seat
    if state.pending_swap is not None:
        state.pending_swap = None
    _log(state, f"⇄ ST 强制交换:{pa.name} ↔ {pb.name}", "st_swap")
    return state
