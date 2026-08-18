"""Pydantic 数据模型。所有状态变更走 GameState.mutate(fn)。"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from server.engine.phase import Phase
from server.engine.script import Script  # 用于前向引用


# ---- 阵营 ----
class Alignment(str, Enum):
    GOOD = "good"
    EVIL = "evil"


class Team(str, Enum):
    TOWNSFOLK = "townsfolk"
    OUTSIDER = "outsider"
    MINION = "minion"
    DEMON = "demon"
    FABLED = "fabled"


class RoleId(str, Enum):
    # Townsfolk
    NOBLE = "noble"
    SNAKE_CHARMER = "snake_charmer"
    BALLOONIST = "balloonist"
    MOUNTAIN_MAN = "mountain_man"
    ENGINEER = "engineer"
    FISHERMAN = "fisherman"
    PROFESSOR = "professor"
    SCHOLAR = "scholar"
    AMNESIAC = "amnesiac"
    FARMER = "farmer"
    CANNIBAL = "cannibal"
    POPPY_GROWER = "poppy_grower"
    ATHEIST = "atheist"
    # Outsiders
    DRUNK = "drunk"
    BARBER = "barber"
    DAMSEL = "damsel"
    GOLEM = "golem"
    # Minions
    POISONER = "poisoner"
    LUNATIC = "lunatic"
    CERENOVUS = "cerenovus"
    HAG = "hag"
    # Demons
    HADJIYA = "hadjiya"
    LLEECH = "lleech"
    # Fabled
    SENTINEL = "sentinel"
    SPIRIT_OF_IVORY = "spirit_of_ivory"


# ---- 角色中文显示名(用于日志/UI)----
_ROLE_DISPLAY_NAME: dict[str, str] = {
    "noble": "贵族", "snake_charmer": "舞蛇人", "balloonist": "气球驾驶员",
    "mountain_man": "巡山人", "engineer": "工程师", "fisherman": "渔夫",
    "professor": "教授", "scholar": "博学者", "amnesiac": "失忆者",
    "farmer": "农夫", "cannibal": "食人族", "poppy_grower": "罂粟种植者",
    "atheist": "无神论者", "drunk": "酒鬼", "barber": "理发师",
    "damsel": "落难少女", "golem": "魔像", "poisoner": "投毒者",
    "lunatic": "精神病患者", "cerenovus": "灵言师", "hag": "麻脸巫婆",
    "hadjiya": "哈迪寂亚", "lleech": "亡骨魔",
    "sentinel": "哨兵", "spirit_of_ivory": "圣洁之魂",
}


def role_display_name(role: "RoleId | str | None", script: "Script | None" = None) -> str:
    """返回角色的中文显示名。

    优先从传入的 script 查找显示名,否则回退到内置 _ROLE_DISPLAY_NAME 表,
    最后回退到原 ID。
    """
    if role is None:
        return "?"
    key = role.value if hasattr(role, "value") else str(role)
    if script is not None:
        name = script.get_role_name(key)
        if name and name != key:
            return name
    return _ROLE_DISPLAY_NAME.get(key, key)


class PlayerStatus(str, Enum):
    ALIVE = "alive"
    DEAD = "dead"
    GHOST = "ghost"  # 鬼魂(已死但仍可投票)


# ---- 模型 ----
class Note(BaseModel):
    """批注:一条记录。可以由 ST (关于某玩家) 或 玩家 (关于另一玩家) 创建。"""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    text: str
    created_at: float = Field(default_factory=lambda: __import__("time").time)
    updated_at: Optional[float] = None


class Player(BaseModel):
    """玩家持久化模型。"""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str
    seat: int
    is_storyteller: bool = False
    status: PlayerStatus = PlayerStatus.ALIVE
    # 真实身份(可以是 ScriptRole.id 字符串,不再限定于 RoleId 枚举)
    true_role: Optional[str] = None
    apparent_role: Optional[str] = None  # 醉酒时 != true_role
    effective_role: Optional[str] = None  # 食人族继承的能力
    is_poisoned: bool = False
    is_drunk: bool = False
    has_used_ability: dict[str, bool] = Field(default_factory=dict)
    # 死亡后是否已用过「死亡一票」(每次进入死亡时由 st_kill_player 重置为 False)
    dead_vote_used: bool = False
    # 说书人关于该玩家的多条批注(列表中每条可独立增/删/改)
    st_notes: list[Note] = Field(default_factory=list)
    # 玩家对其他玩家的多条批注:target_id -> [Note, ...]
    player_notes: dict[str, list[Note]] = Field(default_factory=dict)
    private_log: list[dict[str, Any]] = Field(default_factory=list)  # 玩家私人日志
    notes: dict[str, Any] = Field(default_factory=dict)

    def display_name(self) -> str:
        return f"座位 {self.seat} - {self.name}"


class NightAction(BaseModel):
    role: RoleId
    actor_id: str
    target_id: Optional[str] = None
    secondary_id: Optional[str] = None
    args: dict[str, Any] = Field(default_factory=dict)
    resolved: bool = False


class PendingDeath(BaseModel):
    """夜间发生、待白天公开的死亡/复活事件。

    真实血染钟楼规则:ST 在夜晚的处决/复活对其他玩家保密,
    直到白天开始才一次性向所有人公布。
    """
    player_id: str
    name: str
    kind: str  # "kill" | "revive"
    cause: str = ""


class PendingSwap(BaseModel):
    """Lobby 阶段的座位交换申请。

    from_id:发起人(玩家)
    to_id:被申请人(玩家);只有 to_id 能接受
    """
    from_id: str
    to_id: str
    from_name: str = ""
    to_name: str = ""


class Vote(BaseModel):
    voter_id: str
    target_id: str  # 被提名人
    value: bool     # True=赞成(放上处决台), False=反对
    is_dead_vote: bool = False  # 死者是否仍然投票


class Nomination(BaseModel):
    """单个提名。一个提名阶段内可同时存在多个。"""
    id: str  # 阶段内唯一 ID
    nominator_id: str
    nominee_id: str
    votes: list[Vote] = Field(default_factory=list)
    closed: bool = False
    resolved: bool = False     # True=已结算(阶段结束)
    met_threshold: bool = False  # True=yes 票数 >= alive/2(有资格成为被处决者)
    executed: bool = False       # True=最终被处决的那个(只有 1 个,或 0 个)
    passed: bool = False         # 兼容旧字段,等同 executed
    yes_count: int = 0           # 结算时填入
    no_count: int = 0            # 结算时填入
    reason: str = ""             # 结算原因说明


class PrivateInfo(BaseModel):
    """待分发的私密信息。"""

    to_player_id: str
    kind: str  # learn_role / learn_alignment / yes_no / choose_target / etc.
    payload: dict[str, Any] = Field(default_factory=dict)
    delivered: bool = False
    phase: Phase
    day: int
    night: int


class GameState(BaseModel):
    """游戏状态(可序列化)。所有变更走 mutate(fn)。"""

    room_code: str
    phase: Phase = Phase.LOBBY
    day: int = 0
    night: int = 0
    players: list[Player] = Field(default_factory=list)
    story_teller_id: Optional[str] = None

    # 私有信息队列(待分发)
    pending_info: list[PrivateInfo] = Field(default_factory=list)

    # 夜晚行动队列
    night_queue: list[RoleId] = Field(default_factory=list)
    night_actions: list[NightAction] = Field(default_factory=list)

    # 当前提名阶段(可同时存在多个未结算的提名)
    current_nominations: list[Nomination] = Field(default_factory=list)
    nominated_in_phase: set[str] = Field(default_factory=set)      # 本阶段已提名过别人
    nominated_as_target: set[str] = Field(default_factory=set)    # 本阶段已被提名
    passed_in_phase: set[str] = Field(default_factory=set)         # 本阶段主动 pass
    nomination_index: int = 0  # 今日所有提名的累计数(用于广播)

    # 白天聊天计时
    chat_started_at: Optional[float] = None
    chat_duration_sec: int = 300  # 默认 5 分钟

    # 全局机制标志
    atheist_in_play: bool = False
    atheist_rules_break_pending: bool = False
    damsel_in_play: bool = False
    damsel_player_id: Optional[str] = None
    poppy_grower_alive: bool = True
    spirit_of_ivory_used: bool = False

    winner: Optional[Alignment] = None
    win_reason: str = ""
    # 当前使用的板子(可选;None 表示尚未录入)
    script: Optional["Script"] = None
    # 夜间发生、待白天公开的死亡/复活事件
    pending_deaths: list[PendingDeath] = Field(default_factory=list)
    log: list[dict[str, Any]] = Field(default_factory=list)
    # 恶魔的伪装:开局时随机抽取的 N 个善良阵营角色(镇民+外来者),给恶魔/爪牙在白天撒谎用
    # N = (恶魔数 + 爪牙数) + 1
    # 选取规则:team∈{townsfolk, outsider} && replace_with 为空 && 不在 (true_roles ∪ apparent_roles)
    demon_disguises: list[str] = Field(default_factory=list)

    # 当前在场的传奇角色(fabled) ID 集合。
    # 传奇角色不会通过 pick_roles 分发给玩家,也不计入人数。
    # ST 在游戏进行中可通过 st_toggle_fabled 增删;初始为空。
    fabled_in_play: set[str] = Field(default_factory=set)

    # Lobby 阶段的座位交换请求(游戏中应始终为 None)
    # from_id 发起人;to_id 被申请人(只能由 to_id 接受)
    pending_swap: Optional["PendingSwap"] = None

    # ---- 查询辅助 ----
    def find_player(self, player_id: str) -> Optional[Player]:
        for p in self.players:
            if p.id == player_id:
                return p
        return None

    def alive_players(self) -> list[Player]:
        return [p for p in self.players if p.status == PlayerStatus.ALIVE]

    def storyteller(self) -> Optional[Player]:
        if self.story_teller_id is None:
            return None
        return self.find_player(self.story_teller_id)

    # ---- 单一变更入口 ----
    def mutate(self, fn) -> "GameState":
        """以 fn(state_copy) 形式做不可变变更,自动记录日志。"""
        new = fn(self.model_copy(deep=True))
        if not hasattr(new, "log") or new.log is None:
            new.log = []
        new.log.append({"ts": time.time(), "fn": fn.__name__})
        return new
