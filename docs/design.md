# 血染钟楼本地联机说书人自动化系统 — 技术架构设计文档

> 剧本：The Midnight Oasis（夜半狂欢，作者 Zets），7-15 人，23 个角色
> 后端：Python 3.11 + Flask + Flask-SocketIO
> 前端：原生 HTML/CSS/JS（零安装）
> LLM：anthropic / openai SDK，关键节点调用
> 状态：设计文档，可直接照此编码

---

## 1. 系统总体架构

### 1.1 进程与部署模型

- **单进程部署**：一台机器同时承担 Flask HTTP 服务、SocketIO WebSocket 服务、LLM 调用客户端、游戏引擎（说书人）。
- **端口**：默认 `http://0.0.0.0:5000`，对外暴露：
  - `GET /` ：大厅（创建/加入房间）
  - `GET /st/<room_code>` ：说书人控制台（仅创建者凭 token 进入）
  - `GET /p/<room_code>` ：玩家界面
  - `GET /static/*` ：静态资源
  - `WS /socket.io` ：全双工事件通道
- **进程内部**：Flask + eventlet（或 gevent）单进程承载同步逻辑；游戏引擎是一个无锁协作式状态机（单线程循环 + 事件回调），因此不需多进程。
- **LLM 调用**：同步阻塞（gevent patch 后不阻塞事件循环），调用前用 `socketio.sleep(0)` 让出；超时与重试在 LLMClient 层封装。

### 1.2 模块划分

```
+--------------------------------------------------------------+
|                       浏览器 (前端)                           |
|  大厅页  .  玩家页  .  说书人控制台  .  LV 风视觉组件         |
+--------------------+-----------------------------------------+
                     | WebSocket (Socket.IO)
                     | HTTP (首屏 + 静态资源)
+--------------------v-----------------------------------------+
|                  Flask + Flask-SocketIO                      |
|  +--------------+  +--------------+  +----------------+      |
|  | Routes       |  | SocketIO     |  | Event          |      |
|  | (HTTP 入口)  |  | Gateway      |  | Dispatcher     |      |
|  +------+-------+  +------+-------+  +-------+--------+      |
|         +-----------------+-----------------+               |
|                           v                                |
|   +--------------------------------------------------+     |
|   |               RoomManager (房间生命周期)          |     |
|   |   rooms: Dict[code, Room] .  create/join/start/end|     |
|   +------------------------+-------------------------+     |
|                            v                              |
|   +--------------------------------------------------+     |
|   |           GameEngine (单房间游戏状态机)           |     |
|   |   阶段推进 . 夜晚调度 . 投票结算 . 胜负判定       |     |
|   +------+-----------+-------------+------------------+   |
|          v           v             v                    |
|  +------------+ +----------+ +-------------+            |
|  | RoleSystem | | LLMClient| | PrivateInfo |            |
|  | 角色注册表 | | 大模型   | | 信息分发/广播|            |
|  +-----+------+ +----+-----+ +------+------+            |
|        v            v             v                     |
|  +-------------------------------------------+           |
|  | Models: Room / Player / GameState / Role |           |
|  +-------------------------------------------+           |
+--------------------------------------------------------------+
```

### 1.3 数据流（玩家输入 -> 事件 -> 引擎 -> 广播）

```
浏览器 JS                          后端
  |                                  |
  |-- socket.emit('cast_vote', x) -->| SocketIO Gateway
  |                                  |-- 校验 sid 与 Player 绑定
  |                                  |-- 路由到 Room.event_queue
  |                                  |
  |                                  v
  |                          GameEngine 主循环
  |                          (eventlet spawn)
  |                                  |
  |                                  v
  |                          RoleSystem.night_action(...)
  |                                  |
  |                                  v
  |                          GameState.mutate(...)
  |                          (状态变更 + 事件溯源)
  |                                  |
  |                                  v
  |                          Broadcast: socketio.emit
  |<----- 'state_update' ------------|
  |<----- 'private_info' (to=sid) ---|
  |<----- 'wake_up' / 'sleep' -------|
```

**关键设计原则**：
1. 状态只通过 `GameState.mutate()` 变更，便于持久化/回放/测试。
2. 广播分两类：公共广播（房间全员）+ 定向私有信息（按 `socket.io` 的 `to=room` + 客户端 sid 过滤）。
3. 客户端的「私密信息卡」绝不持久化到 `localStorage`，仅放在内存 state（纯 vanilla JS 也用闭包），关闭即失。


---

## 2. 目录结构

```
blood-on-the-clocktower-st/
|-- README.md
|-- requirements.txt                # flask, flask-socketio, eventlet, anthropic, openai, python-dotenv
|-- .env.example                    # ANTHROPIC_API_KEY / OPENAI_API_KEY / LLM_PROVIDER
|-- run.py                          # 入口：app = create_app(); socketio.run(app, host='0.0.0.0', port=5000)
|-- config.py                       # 全局配置（端口、剧本 ID、LLM 超时等）
|
|-- server/
|   |-- __init__.py                 # create_app() 工厂
|   |-- extensions.py               # socketio = SocketIO(message_queue=...)
|   |-- routes.py                   # HTTP 路由（/, /st/<code>, /p/<code>）
|   |-- socketio_gateway.py         # 所有 on_<event> 处理函数；转交 RoomManager
|   |
|   |-- room/
|   |   |-- __init__.py
|   |   |-- room_manager.py         # rooms: Dict[str, Room]，线程安全（gevent 协作）
|   |   |-- room.py                 # Room：玩家列表 + GameEngine + sid 映射
|   |   `-- player.py               # Player：sid / name / is_st / connection_state
|   |
|   |-- engine/
|   |   |-- __init__.py
|   |   |-- game_state.py           # 不可变快照 + mutate 操作
|   |   |-- game_engine.py          # 主循环、阶段推进、夜晚调度
|   |   |-- phase.py                # Phase 枚举与转换
|   |   |-- events.py               # EngineEvent 事件总线（内部）
|   |   |-- night_scheduler.py      # 角色唤醒顺序、首夜/常规夜两套
|   |   |-- vote_resolver.py        # 投票、平票、处决
|   |   |-- win_checker.py          # 胜负判定（含 Atheist 特殊规则）
|   |   `-- private_info.py         # 信息分发队列与去重
|   |
|   |-- roles/
|   |   |-- __init__.py             # registry：自动注册所有角色类
|   |   |-- base.py                 # BaseRole 抽象类
|   |   |-- registry.py             # 角色工厂 + 角色 ID 映射
|   |   |-- role_data.py            # 角色元数据：阵营、座位、首夜/常规夜唤醒顺序、配比修正
|   |   |-- townsfolk/
|   |   |   |-- noble.py            # 贵族
|   |   |   |-- snake_charmer.py    # 舞蛇人
|   |   |   |-- balloonist.py       # 气球驾驶员
|   |   |   |-- mountain_man.py     # 巡山人
|   |   |   |-- engineer.py         # 工程师
|   |   |   |-- fisherman.py        # 渔夫
|   |   |   |-- professor.py        # 教授
|   |   |   |-- scholar.py          # 博学者
|   |   |   |-- amnesiac.py         # 失忆者
|   |   |   |-- farmer.py           # 农夫
|   |   |   |-- cannibal.py         # 食人族
|   |   |   |-- poppy_grower.py     # 罂粟种植者
|   |   |   `-- atheist.py          # 无神论者
|   |   |-- outsiders/
|   |   |   |-- drunk.py            # 酒鬼
|   |   |   |-- barber.py           # 理发师
|   |   |   |-- damsel.py           # 落难少女
|   |   |   `-- golem.py            # 魔像
|   |   |-- minions/
|   |   |   |-- poisoner.py         # 投毒者
|   |   |   |-- lunatic.py          # 精神病患者
|   |   |   |-- cerenovus.py        # 灵言师
|   |   |   `-- hag.py              # 麻脸巫婆
|   |   |-- demons/
|   |   |   |-- hadjiya.py          # 哈迪寂亚
|   |   |   `-- lleech.py           # 亡骨魔
|   |   `-- fabled/
|   |       |-- sentinel.py         # 哨兵（设置阶段调整外来者 +-1）
|   |       `-- spirit_of_ivory.py  # 圣洁之魂（邪恶总数动态限制）
|   |
|   |-- llm/
|   |   |-- __init__.py
|   |   |-- llm_client.py           # 统一接口：generate(system, user, ...)
|   |   |-- prompts.py              # 所有 system prompt 模板
|   |   |-- atheist_bluff.py        # 无神论者演戏
|   |   |-- cerenovus_keyword.py    # 灵言师关键词生成
|   |   |-- hag_role_creation.py    # 麻脸巫婆创角
|   |   |-- info_distribution.py    # 信息发配平衡（LLM 选择公开策略）
|   |   |-- scholar_info.py         # 博学者双信息（1 真 1 假）
|   |   |-- amnesiac_feedback.py    # 失忆者猜测反馈话术
|   |   `-- fisherman_advice.py     # 渔夫获胜建议
|   |
|   `-- persistence/
|       |-- __init__.py
|       `-- save_load.py            # GameState <-> JSON 存档
|
|-- static/
|   |-- css/
|   |   |-- tokens.css              # LV 风格色板/字体/装饰变量
|   |   |-- layout.css              # 大厅/玩家/说书人页布局
|   |   |-- components.css          # 信息卡、按钮、弹窗、计时器
|   |   `-- animations.css          # 醒/睡翻转、提名心跳、胜利特效
|   |-- js/
|   |   |-- socket.js               # 封装 io()、断线重连、心跳
|   |   |-- store.js                # 极简发布订阅 store（替代 Redux）
|   |   |-- pages/
|   |   |   |-- lobby.js            # 大厅页
|   |   |   |-- player.js           # 玩家页主控
|   |   |   `-- storyteller.js      # 说书人控制台
|   |   |-- components/
|   |   |   |-- role_card.js        # 角色卡翻转
|   |   |   |-- private_info_card.js
|   |   |   |-- nomination_panel.js
|   |   |   |-- vote_panel.js
|   |   |   |-- chat_timer.js       # 白天倒计时
|   |   |   |-- wake_modal.js       # 夜晚唤醒弹窗
|   |   |   `-- toast.js
|   |   `-- utils/
|   |       |-- format.js
|   |       `-- sound.js            # 音效（可选）
|   |-- img/
|   |   |-- logo.svg                # 几何 monogram + 角标 "proudly presented by tr!&Claude code, currently in alpha testing"
|   |   |-- role/                   # 23 张角色肖像
|   |   |-- emblem/                 # 镇民/外来者/爪牙/恶魔徽记
|   |   `-- decor/                  # LV 风纹饰、菱格、暗纹
|   `-- fonts/
|       `-- ...                     # Cormorant Garamond + Inter
|
|-- templates/
|   |-- base.html                   # 公共骨架
|   |-- lobby.html
|   |-- storyteller.html
|   `-- player.html
|
|-- tests/
|   |-- conftest.py                 # 内存 SocketIO 测试客户端
|   |-- test_room_lifecycle.py
|   |-- test_role_distribution.py
|   |-- test_night_cycle.py
|   |-- test_vote_execution.py
|   |-- test_damsel_guess.py
|   |-- test_atheist_rules_break.py
|   |-- test_poppy_grower.py
|   |-- test_llm_fallback.py
|   `-- fixtures/
|       `-- midnight_oasis.json
|
`-- docs/
    |-- design.md                   # 本文档（设计稿）
    |-- role_spec.md                # 23 角色规则原文与执行细节
    `-- protocol.md                 # WebSocket 事件规范
```


---

## 3. 核心数据模型

> 使用 Pydantic v2 做数据校验 + 序列化，便于存档和 WebSocket 载荷一致性。所有「可变」字段走 `model_copy(deep=True)` 触发新快照，避免隐式副作用。

```python
from __future__ import annotations
from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, Field

# -- 阵营与角色 --
class Alignment(str, Enum):
    GOOD = "good"
    EVIL = "evil"

class Team(str, Enum):
    TOWNSFOLK = "townsfolk"
    OUTSIDER = "outsider"
    MINION = "minion"
    DEMON = "demon"
    FABLED = "fabled"   # 传奇/说书人专属，单独一栏

class RoleId(str, Enum):
    NOBLE = "noble"; SNAKE_CHARMER = "snake_charmer"; BALLOONIST = "balloonist"
    MOUNTAIN_MAN = "mountain_man"; ENGINEER = "engineer"; FISHERMAN = "fisherman"
    PROFESSOR = "professor"; SCHOLAR = "scholar"; AMNESIAC = "amnesiac"
    FARMER = "farmer"; CANNIBAL = "cannibal"; POPPY_GROWER = "poppy_grower"
    ATHEIST = "atheist"
    DRUNK = "drunk"; BARBER = "barber"; DAMSEL = "damsel"; GOLEM = "golem"
    POISONER = "poisoner"; LUNATIC = "lunatic"; CERENOVUS = "cerenovus"; HAG = "hag"
    HADJIYA = "hadjiya"; LLEECH = "lleech"
    SENTINEL = "sentinel"; SPIRIT_OF_IVORY = "spirit_of_ivory"

class Phase(str, Enum):
    LOBBY = "lobby"
    SETUP = "setup"
    FIRST_NIGHT = "first_night"
    DAY = "day"
    NOMINATION = "nomination"
    VOTING = "voting"
    NIGHT = "night"
    EXECUTION = "execution"
    ENDED = "ended"

class PlayerStatus(str, Enum):
    ALIVE = "alive"
    DEAD = "dead"
    GHOST = "ghost"

class Player(BaseModel):
    id: str
    name: str
    sid: Optional[str] = None
    seat: int
    is_storyteller: bool = False
    status: PlayerStatus = PlayerStatus.ALIVE
    true_role: RoleId
    apparent_role: RoleId
    is_poisoned: bool = False
    is_drunk: bool = False
    protected_tonight: bool = False
    has_used_ability: dict[str, bool] = Field(default_factory=dict)
    voting_weight: float = 1.0
    notes: dict[str, Any] = Field(default_factory=dict)

class RoleDistribution(BaseModel):
    townsfolk: list[RoleId]
    outsiders: list[RoleId]
    minions: list[RoleId]
    demon: RoleId
    fabled: list[RoleId] = Field(default_factory=list)
    modifiers: list[str] = Field(default_factory=list)

class NightAction(BaseModel):
    role: RoleId
    actor: str
    target: Optional[str] = None
    secondary: Optional[str] = None
    args: dict[str, Any] = Field(default_factory=dict)
    resolved: bool = False
    resolved_effect: Optional[str] = None

class DayAction(BaseModel):
    kind: str
    actor: str
    target: Optional[str] = None
    args: dict[str, Any] = Field(default_factory=dict)

class PrivateInfo(BaseModel):
    to_player: str
    kind: str
    payload: dict[str, Any]
    delivered: bool = False
    day: int
    night: int
    phase: Phase

class Vote(BaseModel):
    voter: str
    target: str
    value: bool
    dead_vote: bool = False
    resolved_value: Optional[bool] = None

class Nomination(BaseModel):
    nominator: str
    nominee: str
    open: bool = True
    votes: list[Vote] = Field(default_factory=list)

class GameState(BaseModel):
    room_code: str
    day: int = 0
    night: int = 0
    phase: Phase = Phase.LOBBY
    distribution: Optional[RoleDistribution] = None
    players: list[Player] = Field(default_factory=list)
    demon_bluffed: list[RoleId] = Field(default_factory=list)
    night_queue: list[RoleId] = Field(default_factory=list)
    night_actions: list[NightAction] = Field(default_factory=list)
    day_actions: list[DayAction] = Field(default_factory=list)
    pending_info: list[PrivateInfo] = Field(default_factory=list)
    nominations: list[Nomination] = Field(default_factory=list)
    log: list[dict[str, Any]] = Field(default_factory=list)
    winner: Optional[Alignment] = None
    storyteller_token: Optional[str] = None
    atheist_rules_break_pending: Optional[dict[str, Any]] = None
    damsel_guess_open: bool = False
    spirit_of_ivory_used: bool = False

    def alive_players(self) -> list[Player]: ...
    def alive_evil(self) -> list[Player]: ...
    def alive_good(self) -> list[Player]: ...
    def mutate(self, fn) -> "GameState":
        new = fn(self.model_copy(deep=True))
        new.log.append({"ts": now(), "fn": fn.__name__})
        return new
```

---

## 4. 状态机设计

### 4.1 阶段转换

```
            +----------+
            |  LOBBY   |  房主创建，玩家加入
            +-----+----+
                  | 房主点击「开始」
                  v
            +----------+
            |  SETUP   |  角色池构建 + Sentinel 调整外来者 +-1
            +-----+----+
                  |
                  v
            +-------------+
            | FIRST_NIGHT |  按首夜顺序唤醒所有角色
            +-----+-------+
                  |
                  v
            +----------+
            |   DAY    |  公开聊天（说书人控制台计时）
            +-----+----+
                  | 计时结束 或 房主手动推进
                  v
            +-------------+
            | NOMINATION  |  玩家依次提名
            +-----+-------+
                  | 当前提名人提名完成
                  v
            +----------+
            |  VOTING  |  全体投票（死者是否计票依规则）
            +-----+----+
                  | 结算
                  v
            +------------+
            | EXECUTION  |  若 > 半数通过，处决；否则进入夜晚
            +-----+------+
                  |
                  v
            +----------+
            |  NIGHT   |  按常规夜顺序唤醒
            +-----+----+
                  |
                  v
            (win_checker -> ENDED?)
                  | 否
                  v
                DAY（day++）
```

### 4.2 夜晚唤醒顺序

**首夜（First Night）顺序**：
1. Cerenovus（灵言师）：得知 1 个关键词
2. Sentinel（哨兵）：已在 SETUP 阶段完成外来者 +-1
3. Noble（贵族）：得知 3 名玩家，其中恰有 1 邪恶
4. Snake Charmer（舞蛇人）：选 1 人；若恶魔则交换角色 + 阵营
5. Balloonist（气球驾驶员）：得知 1 个角色类型
6. Mountain Man（巡山人）：可选落难少女 -> 不在场镇民
7. Engineer（工程师）：可选改恶魔/所有爪牙身份
8. Professor（教授）：可选 1 名死亡镇民复活
9. Poppy Grower（罂粟种植者）：检查场上邪恶互认
10. Damsel（落难少女）：标记在场供爪牙识别
11. Hag（麻脸巫婆）：可选创角
12. Lleech（亡骨魔）：选 1 人死亡
13. Hadjiya（哈迪寂亚）：选 3 人
14. Poisoner（投毒者）：选 1 人中毒
15. Amnesiac（失忆者）：猜能力
16. Atheist（无神论者）：检查在场即注册演戏钩子

> **酒鬼（Drunk）虽属外来者，但不知道自己是酒鬼**；他的「自认身份」是镇民槽位里的某个真实镇民。处理方式：分发阶段将酒鬼的真实身份标记为 Drunk，`apparent_role = 酒鬼自己以为的身份`，夜晚他按自认身份行动。

**常规夜顺序**：
1. Snake Charmer
2. Balloonist
3. Mountain Man（一次性）
4. Engineer（一次性）
5. Professor（一次性，夜晚任意时机）
6. Cannibal（食人族，若刚获得能力则插入对应位置）
7. Poppy Grower（仅在他死亡当晚插入以恢复互认）
8. Damsel（持续监听）
9. Golem（魔像，一次性提名监控）
10. Barber（理发师，仅在他死亡当晚触发）
11. Hag
12. Lleech
13. Hadjiya
14. Poisoner
15. Scholar（白天能力）
16. Fisherman（白天能力）
17. Lunatic（白天能力）
18. Cerenovus（首夜关键词已确定，白天/夜晚触发判定在 `engine` 里独立模块）

> 实际的执行由 `night_scheduler.py` 中的 `NIGHT_ORDER_FIRST` 和 `NIGHT_ORDER_NORMAL` 列表驱动，引擎遍历列表，对每个 `RoleId` 实例调用其 `night_action`，等待该玩家在 WebSocket 上提交选择（带超时默认 30s）。


---

## 5. 角色系统设计

### 5.1 BaseRole 抽象类

```python
from abc import ABC, abstractmethod

class BaseRole(ABC):
    role_id: RoleId
    team: Team
    name_zh: str
    name_en: str

    def distribution_modifier(self) -> list[str]:
        """返回影响配比的标记，如 ['+1 outsider'] 或 ['+damsel']"""
        return []

    def on_game_setup(self, state: GameState) -> GameState: ...
    def on_first_night(self, state: GameState) -> GameState: ...
    def on_night(self, state: GameState) -> GameState: ...
    def on_day_start(self, state: GameState) -> GameState: ...
    def on_nomination_start(self, state: GameState) -> GameState: ...
    def on_vote(self, state: GameState, vote: Vote) -> Vote: ...
    def on_execution(self, state: GameState, executed: Player) -> GameState: ...
    def on_death(self, state: GameState, dead: Player) -> GameState: ...
    def query(self, state: GameState, player: Player, request: dict) -> PrivateInfo: ...

    def learn_for_player(self, state: GameState, player: Player) -> Optional[PrivateInfo]:
        """夜醒后向玩家推送的私密信息。默认 None；由子类实现。"""
        return None
```

> **设计哲学**：所有规则副作用通过 `BaseRole` 子类钩子实现。引擎是「调度器」，不内置规则逻辑。角色类是「策略对象」。

### 5.2 类继承结构

```
BaseRole
|-- FabledRole
|   |-- Sentinel            # 仅 on_game_setup
|   `-- SpiritOfIvory       # on_execution 钩子监控邪恶人数
|-- TownsfolkRole
|   |-- Noble               # learn_for_player
|   |-- SnakeCharmer        # night_action + 恶魔中毒/交换
|   |-- Balloonist          # 维护 seen_types 集合
|   |-- MountainMan         # 一次性标记
|   |-- Engineer            # 一次性标记
|   |-- Fisherman           # day_action query -> LLM
|   |-- Professor           # 一次性 night_action 复活
|   |-- Scholar             # day_action query -> LLM（1 真 1 假）
|   |-- Amnesiac            # 每日 query -> LLM 反馈
|   |-- Farmer              # on_death 钩子
|   |-- Cannibal            # on_death 时获取上一个死亡者能力
|   |-- PoppyGrower         # on_death 时插入 night 钩子恢复互认
|   `-- Atheist             # 注册全局「说书人可改规则」标志
|-- OutsiderRole
|   |-- Drunk               # 仅注册 apparent_role 错配
|   |-- Barber              # on_death 触发交换
|   |-- Damsel              # 注册全局 damsel_guess_open
|   `-- Golem               # on_nomination 钩子保护提名
|-- MinionRole
|   |-- Poisoner            # night_action
|   |-- Lunatic             # on_nomination_start 钩子（每天 1 次）
|   |-- Cerenovus           # 首夜 LLM 生成关键词 + on_day 监听
|   `-- Hag                 # night_action + LLM 创角决策
`-- DemonRole
    |-- Hadjiya             # night_action (3 个目标 + 集体决策)
    `-- Lleech              # night_action + on_death 维护 poisonous 邻接
```

### 5.3 复杂机制的处理方案

**1) `+1 outsider` / `+damsel` 配比调整**
- 在 `setup.py` 中：`distribution_for(n_players)` 先按基础表生成，遍历每个角色调 `distribution_modifier()`，收集 `+1 outsider` / `-1 outsider` / `+damsel` 标记后修正配比。
- 哨兵额外加一次：游戏设置阶段说书人控制台弹出「是否增减 1 外来者」UI，调用 `Sentinel.on_game_setup` 调整。

**2) 无神论者.打破规则**
- `Atheist.on_game_setup` 设置 `state.atheist_rules_break_pending = {"active": True}`。
- 说书人控制台暴露一个隐藏菜单：「Break a rule」，所有触发后游戏规则的弹窗（投票门槛、保护、处决上限等）都可以由说书人覆写。
- `win_checker` 在 `Atheist` 死亡时检查：若说书人「被处决」则善良立即获胜（`winner = GOOD`），无需在场邪恶判定。
- LLM 节点：每次说书人执行打破规则的操作，`atheist_bluff.py` 让 LLM 生成「完美符合规则的官方说辞」。

**3) 罂粟种植者.拦截互认**
- 在 setup 阶段：若 Poppy Grower 在场，跳过 `demon_meets_minions` 和 `minions_meet_demon`。
- Poppy Grower 死亡当晚：`on_death(state, dead)` 在 night 队列最前面插入「恶魔与爪牙互认」子阶段。
- 「互认」是 night scheduler 中的一个独立子步骤 `interaction_step(role_pairs)`，被 Poppy Grower 复用。

**4) 落难少女.独立猜测入口**
- Damsel 在场时：所有爪牙首夜收到 `PrivateInfo(kind="know_damsel", payload={damsel_player_id})`。
- 玩家 UI：爪牙玩家的「私人信息」面板永久显示一个独立按钮「公开猜测落难少女」（一次性）。
- 点击后：广播 `damsel_guess_attempt {guesser, target}`。引擎判定：`target.true_role == DAMSEL`？则 `winner = EVIL`；否则记下错误猜测（不再允许）。
- LLM 介入：判定结果可调用 `info_distribution.py` 让 LLM 生成戏剧化播报。

**5) 麻脸巫婆.创角**
- `Hag.night_action` 提交：`(target_player, role_to_create)`。
- 若 `role_to_create` 不在场且 `target_player` 是善良：状态变成该角色，且触发后续效应（如新恶魔入场则当晚死亡由说书人决定 — LLM 生成剧情或直接枚举选项）。
- LLM 介入：选择「创哪个角色」与「选哪个目标」由 `hag_role_creation.py` 智能决策。

**6) 哈迪寂亚.三人秘密决策**
- 选 3 人 -> 依次唤醒他们，每人秘密按「活/死」按钮。
- 全部存活则 3 人同时死亡（Engine 一次性广播 death 事件）。
- UI：每个被唤醒的玩家看到「你被恶魔选中，请秘密决定生死」，按钮不公开；结算时所有人才知道结果。

**7) 亡骨魔.邻接中毒**
- 杀死 1 爪牙 -> 该爪牙**保留能力**（on_death 不移除 Role 钩子）。
- 该爪牙两侧镇民之一中毒。
- 座位用环状数组，取 `seat+-1`。

**8) 食人族.继承能力**
- `Cannibal.on_death` 不在自己身上触发；监听 `previous_dead` 的角色元数据，把 `Cannibal.player.effective_role_id` 设为上一个死者角色，并在后续夜晚插入对应 night_action。
- 若上一个死者属邪恶，Cannibal 中毒直到下次「善良玩家因处决死亡」（监听 `execution` 事件）。

**9) 魔像.一次提名保护**
- `Golem.on_nomination(nominee)`：若 `nominee.true_role != DEMON` -> Golem 死亡；否则提名继续。
- 一次性：用 `has_used_ability["golem_nomination"]` 控制。

**10) 舞蛇人.恶魔交换**
- 选中恶魔：交换 `true_role` 与 `apparent_role`、阵营互换；恶魔中毒当晚。
- 中毒由 `Poisoner`-like 状态机管理：每晚施毒由 Poisoner 角色触发；若舞蛇人触发恶魔中毒，则当晚 `demon.is_poisoned = true`。

**11) 工程师.改身份**
- 一次性：把所有 `minion.true_role` 改为某 minion 类型，恶魔同理。
- 配合 `demon_bluffed` 列表维持「恶魔手上假身份」集合。

**12) 圣洁之魂.邪恶总数限制**
- `SpiritOfIvory.on_night` 与 `on_execution` 钩子：检查 `alive_evil_count <= initial_evil_count + 1`，否则说书人控制台提示「违反 Spirit of Ivory」并要求决定。

**13) 失忆者.每日猜测**
- 每天白天开始：失忆者被唤醒，秘密提交「我认为我的能力是 ___」。
- `Amnesiac.query` 调用 LLM 生成「对/部分对/错」的戏剧化反馈。

**14) 博学者.双信息（1 真 1 错）**
- 白天能力：玩家在 UI 点击「询问说书人」，弹窗中输入一个具体问题（玩家自由文本）。
- 后端：调用 `scholar_info.py`，LLM 必须返回 `{ "true_info": ..., "false_info": ... }`。
- 引擎校验：内部用确定性规则确认哪条为真（避免 LLM 幻觉）；若 LLM 两条都同真假，则回退到随机选一条为假。

**15) 农夫.死亡转职**
- `Farmer.on_death(dead_player, state)`：若 `dead_player.true_role == FARMER`，选 1 存活善良玩家，其 `true_role = FARMER`。

**16) 理发师.死亡当晚交换**
- `Barber.on_death`：当晚 night 队列插入「恶魔选 2 人交换」步骤。
- 引擎：恶魔玩家收到 `request {kind: "barber_swap", options: [活人列表]}`，提交 2 个玩家，交换 `true_role/apparent_role`。

**17) 巡山人.落难少女 -> 不在场镇民**
- 一次性：若选 Damsel，`Damsel.player.apparent_role = 某镇民`（不在场），并在 Damsel 的元数据里标注「out_of_play townsfolk」。
- 该镇民不参与后续任何 night_action（player 标记 `is_in_play = False`）。


---

## 6. WebSocket 事件协议

命名：`snake_case`。带 `*` 的事件服务端只广播给特定 sid。

### 6.1 客户端 -> 服务端

| 事件 | Payload | 谁能发 |
|---|---|---|
| `join_room` | `{room_code, player_name, as_storyteller?, token?}` | 所有人 |
| `reconnect` | `{room_code, player_id, token?}` | 所有人 |
| `leave_room` | `{}` | 所有人 |
| `start_game` | `{}` | 仅说书人 |
| `night_action` | `{action_id, target_id?, secondary?, args?}` | 被唤醒的角色 |
| `day_action` | `{kind, target_id?, args?}` | 任意玩家 |
| `speak_done` | `{}` | 任意玩家（白天结束发言） |
| `nominate` | `{nominee_id}` | 存活非魔像超限玩家 |
| `vote` | `{value: bool, target_id}` | 存活非死者 |
| `use_day_ability` | `{ability_id, args?}` | 玩家主动（博学者询问、渔夫建议、灵言师监听等） |
| `damsel_guess` | `{target_id}` | 仅爪牙（且未猜过） |
| `lunatic_kill` | `{target_id}` | 仅精神病患者 |
| `skip_timer` | `{}` | 仅说书人 |
| `break_rule` | `{rule, payload}` | 仅说书人（无神论者模式） |
| `end_game` | `{reason}` | 仅说书人 |

### 6.2 服务端 -> 客户端

| 事件 | Payload | 谁能收 |
|---|---|---|
| `joined` | `{player_id, room_code, is_storyteller}` | 发起者 |
| `player_list` | `{players: [{id, name, seat, status, is_storyteller}]}` | 全部 |
| `state_update` | `{phase, day, night, public_state}` | 全部 |
| `role_assigned` | `{true_role, apparent_role, ability_text, team_color}` | 单人 `to=sid` |
| `wake_up` | `{role, prompt, options_ref, timeout_ms}` | 单人 `to=sid` |
| `sleep` | `{role}` | 单人 `to=sid` |
| `private_info` | `{kind, payload}` | 单人 `to=sid` |
| `night_action_resolved` | `{summary_public}` | 全部（仅公开摘要） |
| `public_announcement` | `{text, kind}` | 全部 |
| `nomination_open` | `{nominator, nominee}` | 全部 |
| `nomination_closed` | `{nominee, votes_for, votes_against, passes?}` | 全部 |
| `execution` | `{player_id, role_revealed}` | 全部 |
| `death` | `{player_id, cause}` | 全部 |
| `timer` | `{phase, seconds_left}` | 全部 |
| `wake_for_demon_swap` | `{kind, options}` | 恶魔 sid（理发师机制） |
| `damsel_guess_result` | `{guesser, target, correct, winner?}` | 全部 |
| `lunatic_kickoff` | `{target}` | 全部 |
| `game_over` | `{winner, reason, final_state}` | 全部 |
| `error` | `{code, message}` | 发起者 |
| `llm_thinking` | `{label}` | 说书人（显示 LLM 思考摘要） |
| `chat_message` | `{from, text, is_ghost?}` | 全部（可选功能） |

### 6.3 协议约定

- 所有 payload 通过 Pydantic 校验；失败回 `error` 事件，HTTP 状态码 422。
- 心跳：客户端每 25s 发 `ping`，服务端回 `pong`；60s 无活动断开。
- 重连：客户端拿到 `player_id` 后写入 `sessionStorage`，断线后 `reconnect` 自动恢复 sid 映射。
- 私密事件使用 SocketIO `to=player_sid`，**绝不广播**。

---

## 7. LLM 接入设计

### 7.1 LLMClient 统一接口

```python
class LLMClient:
    def __init__(self, provider: str = "anthropic"):
        if provider == "anthropic":
            self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            self.model = os.getenv("LLM_MODEL", "MiniMax-M3")
        else:
            self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            self.model = os.getenv("LLM_MODEL", "MiniMax-M3")

    def generate(self, system: str, user: str, *, max_tokens=800, temperature=0.7,
                 json_schema: dict | None = None, timeout=20) -> str:
        for attempt in range(2):
            try:
                return self._call(system, user, max_tokens, temperature, json_schema, timeout)
            except Exception as e:
                log.warning("LLM attempt %s failed: %s", attempt, e)
        return self._fallback(system, user)
```

### 7.2 必须调用 LLM 的节点

| 节点 | 模块 | 说明 | 降级 |
|---|---|---|---|
| 无神论者演戏 | `atheist_bluff.py` | 每次说书人打破规则后，LLM 生成符合官方规则的播报 | 模板：直接用通用说辞 |
| 灵言师关键词 | `cerenovus_keyword.py` | 首夜生成适合本局的关键词（与玩家已知信息不冲突） | 从 30 词表随机 |
| 麻脸巫婆创角 | `hag_role_creation.py` | 选目标 + 角色，平衡局势 | 规则化选择：选人数最少阵营的稀有角色 |
| 信息发配平衡 | `info_distribution.py` | noble/balloonist/poisoner 等信息「说什么」由 LLM 包装 | 直接返回 ID/角色名 |
| 博学者双信息 | `scholar_info.py` | 玩家问问题，LLM 出 1 真 1 假 | 取一条当前公开事实 + 一条无关事实 |
| 失忆者反馈 | `amnesiac_feedback.py` | 玩家猜测能力，LLM 生成「全对/部分对/错」反馈 | 随机真/假 |
| 渔夫建议 | `fisherman_advice.py` | 询问获胜建议，LLM 出 1-2 句剧情化建议 | 「多观察发言」通用建议 |
| 哈迪寂亚三人命运 | `hadjiya_outcome.py` | 戏剧化播报「他们私下讨论后决定...」 | 固定模板 |
| 食人族继承 | `cannibal_inherit.py` | 包装叙事：玩家意识里获得新能力 | 「你感到一阵眩晕，想起一些事」 |
| 罂粟种植者死亡 | `poppy_grower_reveal.py` | 死时对爪牙/恶魔互认的叙事 | 「你们突然意识到彼此」 |

### 7.3 System Prompt 设计原则

每个模块一个 `system` 文件，集中存放在 `prompts/`。例如 `prompts/scholar_info.txt`：

```
You are the Storyteller of Blood on the Clocktower. A Scholar asks a question.
You MUST reply with JSON: {"true": "...", "false": "..."}
Rules:
1. Both statements must be plausible and consistent with the game state.
2. EXACTLY ONE is true. Use the provided hidden state to verify.
3. Both statements must be of the same type (e.g., both about role identities, both about alignment, or both about mechanical facts).
4. Keep each statement under 25 words.
5. Do NOT reveal the player is a Scholar or the storyteller nature to other players.
```

### 7.4 降级方案（确定性回退）

- 博学者：`true = state.alive_demon_id_alignment_info`；`false = state.random_other_fact`。
- 灵言师关键词：从内置词表 `["mirror", "snake", "shadow", "music", ...]` 随机抽，且确保不在场信息中已出现。
- 无神论者：用模板 `f"[规则解释] 由 {STORYTELLER_NAME} 宣布：{RULE_TEXT}"`
- LLM 整体不可用时：`engine.py` 设置 `state.llm_available = False`，所有相关能力降级为模板化播报。说书人控制台顶部显示警告横幅。

### 7.5 API Key 加载

```
.env.example
  LLM_PROVIDER=anthropic      # or openai
  LLM_MODEL=MiniMax-M3
  ANTHROPIC_API_KEY=sk-ant-xxx
  OPENAI_API_KEY=sk-xxx
  LLM_TIMEOUT=20
  LLM_FALLBACK=template       # template | disabled
```

通过 `python-dotenv` 在 `create_app()` 启动时加载；任何调用前先 `assert os.getenv("ANTHROPIC_API_KEY")`，缺失则启动时日志告警但允许程序以纯模板模式运行。


---

## 8. 前端架构

### 8.1 三个核心页面

1. **大厅页 (`/`)**
   - 中央：LV 风格菱格暗纹 + 几何 monogram
   - 「创建房间」按钮 -> 跳转 `/st/<code>`
   - 「加入房间」表单（4-6 位大写字母 + 玩家名）
   - 底部角标：`proudly presented by tr!&Claude code, currently in alpha testing`

2. **说书人控制台 (`/st/<code>`)**
   - 左侧：玩家列（座位、状态、真实身份可见、是否中毒）
   - 中部：当前阶段大仪表（Day 3 / Nomination 阶段），含倒计时
   - 右侧：今夜行动队列、票数面板、LLM 思考流
   - 顶部工具栏：跳过计时、打破规则（仅 Atheist 在场）、强制推进、查看私密日志
   - 弹窗：阶段切换、外来者调整、LLM 调用进度

3. **玩家页 (`/p/<code>`)**
   - 中央偏上：身份卡（hover/点击翻转显示能力）
   - 中央：私密信息卡列表（夜醒收到 + 白天询问）
   - 底部：行动区（按当前阶段动态：夜醒选择 / 提名按钮 / 投票按钮 / 询问按钮 / 公开猜测按钮）
   - 顶部：状态条（Day 3 . 你的状态：存活 . 是否中毒提示）

### 8.2 关键 UI 组件

- **`<role-card>`**：CSS 3D 翻转，正面是 emblem + 名称，背面是能力描述。左下角显示阵营徽记（金/红/黑）。
- **`<private-info-card>`**：羊皮纸纹理 + 蜡封样式；过期（下一阶段开始）自动折叠。
- **`<nomination-panel>`**：当某人被提名，玩家看到投票面板：「投赞成 / 投反对」，含计时。
- **`<chat-timer>`**：白天倒计时大字（`04:32`），最后 10s 红色脉冲。
- **`<wake-modal>`**：全屏暗色遮罩 + 中央卡，提示「X 角色请醒来」，含角色图标 + 步骤指引。
- **`<toast>`**：右下角非阻塞通知（连接状态、夜醒提示、LLM 调用中）。

### 8.3 LV 风格视觉规范

**色板（CSS 变量）**：
```
--ink:       #1a1410   /* 主文字 */
--parchment: #f4ede1   /* 背景羊皮纸 */
--gold:      #b08a3e   /* 装饰金 */
--gold-deep: #8a6a2a   /* 强调金 */
--rouge:     #6e1f23   /* 邪恶阵营红 */
--azur:      #1a3a5e   /* 善良阵营蓝 */
--noir:      #0d0a08   /* 恶魔黑 */
--ivoire:    #ece3d0   /* 圣洁之魂象牙白 */
```

**字体**：
- 标题：`Cormorant Garamond`（衬线，奢华）
- 正文：`Inter`（现代衬线不抢戏）
- 角色名：`Cinzel`（古典罗马体）

**装饰**：
- 菱格暗纹背景 SVG（CSS 重复）
- 金色细线边框（`border: 1px solid var(--gold)`）
- 角落烫金纹饰（SVG `<path>`）
- 角色卡用真实皮革纹理 + 烫金浮雕
- 进场动画：角色卡 3D 翻转 + 阴影投射
- 角标固定：`position: fixed; bottom: 12px; right: 16px; font-size: 11px; letter-spacing: 0.15em; color: var(--gold-deep);`

### 8.4 计时/弹窗/动画统一处理

- 单一 `Toast` 服务：所有跨组件提示走 `store.dispatch({type:'toast', payload})`
- 倒计时：服务端权威计时（说书人控制台控制），客户端展示用 `socket.io` 的 `timer` 事件。
- 阶段切换：CSS 过渡 `transition: opacity 400ms ease`，配合轻微缩放。
- 所有动画：CSS-only，禁用 JS 动画（兼容浏览器）。

---

## 9. 关键流程时序图

### A. 开房 -> 加入 -> 身份发放

```
说书人浏览器        玩家A浏览器       玩家B浏览器        后端
   |                  |                |                  |
   |-- join_room ---->|                 |                 |-- 校验 token，分配 sid
   |   {as_st=true}   |                |                  |-- Room.players.add(ST)
   |<-- joined -------|                |                  |
   |   {player_id}    |                |                  |
   |                  |-- join_room -->|                  |
   |                  |   {name:A}     |                  |-- player_id=A
   |                  |<-- joined -----|                  |
   |                  |                |-- join_room ---->|
   |                  |                |                  |-- player_id=B
   |                  |                |<-- joined ------|
   |<-- player_list --|<-- player_list -|<-- player_list -|
   |                  |                |                  |
   |-- start_game --->|                 |                 |-- SETUP 阶段
   |                  |                |                  |-- 角色池构建（含 Sentinel 调整）
   |                  |                |                  |-- 分配 true_role / apparent_role
   |                  |                |                  |-- 加恶魔手上 bluff
   |<-- state_update -|<-- state_update -|<-- state_update -|
   |   {phase=setup} |                |                  |
   |                  |                |                  |
   |                  |                |                  |-- FIRST_NIGHT
   |                  |                |                  |
   |                  |                |                  |-- Cerenovus 唤醒
   |                  |<-- role_assigned |                  |-- C 玩家 sid
   |                  |   {role=CERENOVUS,keyword}         |
   |                  |-- night_action >|                  |
   |                  |                |                  |
   |                  |                |                  |-- ...（按顺序唤醒所有人）
```

### B. 一个完整的夜晚循环

```
            NightScheduler
                 |
                 |  foreach role in NIGHT_ORDER_NORMAL:
                 v
        +----------------------+
        | 找到该角色持有者(s)  |
        +----------+-----------+
                   v
        +----------------------+
        | emit wake_up to sid  |--> 玩家 UI 弹出醒的对话框
        +----------+-----------+
                   v
        +----------------------+
        | 等待 night_action    |<-- 玩家提交选择
        | (timeout 30s)        |
        +----------+-----------+
                   v
        +----------------------+
        | emit learn_for_player|--> 玩家收到私密信息
        +----------+-----------+
                   v
        +----------------------+
        | emit sleep           |--> 玩家 UI 关闭弹窗
        +----------+-----------+
                   v
        +----------------------+
        | 全部顺序完成后       |
        | engine.resolve_night |--> 状态变更（死亡、中毒、复活）
        |   - 应用所有 action  |
        |   - win_check        |
        |   - 广播 night_action_resolved
        +----------+-----------+
                   v
                DAY 阶段
```

**关键点**：每个 `night_action` 调用是「收集」而非立即生效。所有死亡/中毒/复活在 `resolve_night()` 一次性结算，确保顺序敏感（如 Poisoner 先投毒 -> Snake Charmer 后交换时仍记录「曾中毒者」）。

### C. 白天提名投票 -> 处决 -> 胜负

```
DAY 开始
   |
   |  ChatTimer 计时（说书人控制）
   v
NOMINATION 阶段
   | 轮询：每个存活玩家可提名一次（直至全部跳过）
   | 魔像：仅一次；若提名非恶魔 -> 魔像死亡 -> 提名继续
   | 精神病患者：提名阶段开始前可选 1 人公开杀死
   v
VOTING 阶段
   | 当前提名人发起 -> 所有玩家投票（活/死可选）
   | 中毒者票被翻转（rules）
   v
vote_resolver
   |  votes_for > alive_count / 2  -> 处决
   |  否则 -> 不处决
   v
EXECUTION
   |  若处决：死亡广播 + 触发 on_execution 钩子
   |  - Atheist 在场且被处执行 -> 善良获胜
   |  - Cannibal.on_execution 监听
   v
win_checker
   |  善良：恶魔死亡 -> 胜
   |  邪恶：人数 >= 善良 && 恶魔存活 -> 胜
   v
NIGHT 或 ENDED
```

### D. 落难少女被猜对时的特殊流程

```
SETUP 阶段
   |  Damsel 在场 -> 所有爪牙的私密信息中标注 damsel_player_id
   v
爪牙 UI 永久显示「公开猜测落难少女」按钮（一次性）
   |
   |  爪牙点击
   v
damsel_guess 事件 -> 引擎
   |
   |  若 target.true_role == DAMSEL：
   |     - 广播 damsel_guess_result {correct: true}
   |     - LLM 生成戏剧化播报
   |     - winner = EVIL
   |     - game_over
   |  否则：
   |     - 广播 {correct: false}
   |     - 该爪牙标记 has_used_ability[damsel_guess]=true
   |     - 游戏继续
```

### E. 无神论者在场时打破规则

```
SETUP 阶段
   |  Atheist.on_game_setup -> state.atheist_rules_break_pending = {active: True}
   v
说书人控制台检测到 -> 显示「无神论者模式：启用打破规则」横幅
   |
   |  例外：说书人想「处决 1 名不死玩家」（打破「处决即死」）
   v
说书人点击 break_rule {rule: "execution_immunity_bypass", payload: {player_id: X}}
   |
   |  后端：
   |     - LLM 调用 atheist_bluff 生成完美说辞
   |     - 写入公共日志 public_announcement
   |     - 执行破规则的效果
   v
若说书人「被处决」（Atheist 模式下的特殊规则）：
   |
   |  - 不进入常规 win_check
   |  - winner = GOOD（即使场上无邪恶、或邪恶仍占多数）
   v
Atheist 死亡常规情况：
   |  - 不触发特殊胜利
   |  - 但 state.atheist_rules_break_pending.active 仍保持为 True 直到游戏结束
```


---

## 10. 测试与验证

### 10.1 端到端关键场景

1. **完整 7 人首夜->白天->夜晚循环**
   - 7 个 SocketIO 测试客户端连接
   - 模拟：Cerenovus 获关键词、Noble 获 3 人含 1 邪恶、Balloonist 获角色类型
   - 断言：`state.alive_count == 7`、无错误事件、`state.phase == DAY`

2. **投票平票/多数不通过**
   - 7 人，3 票 vs 3 票 -> 不处决
   - 触发 `Golem.on_nomination` 走一次

3. **Damsel 猜对 -> 邪恶立即胜**
   - 7 人配置含 Damsel + 1 爪牙
   - 爪牙猜测正确 -> `winner == EVIL`

### 10.2 模拟真人玩家最小验证

- `tests/e2e/manual_smoke.py`：spawn 2 个 headless socket.io 客户端（用 `python-socketio[asyncio_client]`）模拟人类玩家，1 个说书人。
- 跑通：加入 -> 开始 -> Cerenovus 提交关键词 -> Balloonist 提交目标 -> Nomination -> Vote -> 推进到 Night。

### 10.3 规则回归测试（每个角色至少 1 case）

`tests/roles/` 下每角色一个 `test_<role>.py`：

- `test_noble.py`：3 人中恰 1 邪恶
- `test_snake_charmer.py`：选中恶魔交换 + 中毒；未选中无事发生
- `test_balloonist.py`：连续 3 夜返回不同类型；超过上限报错
- `test_engineer.py`：一次性；改恶魔为指定恶魔；改所有爪牙
- `test_mountain_man.py`：选 Damsel -> 不在场镇民
- `test_professor.py`：复活死亡镇民
- `test_scholar.py`：LLM 返回必须 1 真 1 假（用确定性 mock 校验）
- `test_amnesiac.py`：猜测正确 -> 「全对」
- `test_farmer.py`：夜晚死亡 -> 1 善良变 Farmer
- `test_cannibal.py`：上一个死亡者能力继承；邪恶死亡则中毒
- `test_poppy_grower.py`：在场时不互认；死亡当晚互认
- `test_atheist.py`：说书人打破规则；说书人被处决 -> 善良胜
- `test_drunk.py`：apparent_role != true_role；行动按 apparent_role
- `test_barber.py`：死亡当晚恶魔交换 2 人
- `test_damsel.py`：爪牙正确猜测 -> 邪恶胜
- `test_golem.py`：提名非恶魔 -> 死亡
- `test_poisoner.py`：夜晚中毒持续到次日白天
- `test_lunatic.py`：每日提名阶段前可选 1 人；处决后 RPS
- `test_cerenovus.py`：关键词触发；说关键词者阵营翻转
- `test_hag.py`：不在场角色创角；创恶魔则当晚死亡由 ST 决定
- `test_hadjiya.py`：3 人秘密决策；全活 -> 全死；至少 1 死 -> 仅死的人死
- `test_lleech.py`：杀 1 爪牙 -> 邻接镇民中毒；爪牙保留能力
- `test_sentinel.py`：设置阶段 +-1 外来者
- `test_spirit_of_ivory.py`：邪恶人数超 +1 -> 报警

### 10.4 测试基础设施

- `conftest.py` 提供 `make_room(n_players)`：内存 Room + 7-15 mock sid
- `mock_llm_client`：替换 LLMClient，所有调用返回固定结构
- `assert_state_unchanged(prev, new, except_keys=[...])`：常用断言

---

## 11. 开发里程碑建议

### 阶段一：核心骨架（2 周）

- [ ] Flask + SocketIO 骨架、`create_app` 工厂
- [ ] Room/Player/GameState 模型（Pydantic）
- [ ] 大厅页 UI + 路由
- [ ] 玩家页 UI 基础框架（身份卡 + 状态条）
- [ ] 说书人控制台 UI 基础框架
- [ ] 状态机：LOBBY -> SETUP -> FIRST_NIGHT -> DAY -> NIGHT -> ENDED
- [ ] 「无角色」版：仅作为通用投票工具
- [ ] 存档/读档（JSON）
- 验收：能开房、加入、发任意身份、白天聊天+投票+处决、夜晚无任何角色自动跳过。

### 阶段二：角色补全（3-4 周，按优先级）

**P0（必做，先做）**：
- Poisoner、Hadjiya、Lleech、Hag、Noble、Snake Charmer、Balloonist
- 覆盖首夜+常规夜核心循环

**P1**：
- Engineer、Mountain Man、Professor、Scholar、Amnesiac、Poppy Grower
- Barber、Damsel、Golem、Lunatic、Cerenovus

**P2**：
- Cannibal、Farmer、Drunk、Atheist、Fisherman
- Sentinel、Spirit of Ivory

每完成一批角色就补对应回归测试。

### 阶段三：LLM 接入（1 周）

- [ ] LLMClient 抽象 + Provider 切换
- [ ] `prompts/` 10 个模板
- [ ] 降级路径
- [ ] 说书人控制台 LLM 思考流面板

### 阶段四：美术打磨（1 周）

- [ ] tokens.css（LV 色板）
- [ ] logo.svg + 角标
- [ ] 23 张角色肖像（占位 + 后续替换）
- [ ] 组件动画（翻转、倒计时、阶段切换）
- [ ] 字体接入
- [ ] 响应式（手机/平板/桌面）

### 阶段五：可选打磨

- 音效（夜醒钟声、处决）
- 文字回放
- 战绩统计（每局后邪恶/善良胜率、角色出场率）

---

## 附录 A：关键技术决策与理由

| 决策 | 方案 | 理由 |
|---|---|---|
| 实时通信 | Flask-SocketIO + eventlet | 单进程 + 双向事件，符合协作式状态机 |
| 数据模型 | Pydantic v2 | 序列化、校验、文档一体化；存档/广播协议共用 |
| 状态变更 | 单一 `mutate(fn)` 入口 | 易做快照/回放/调试；杜绝散落副作用 |
| 角色系统 | BaseRole 子类钩子 | 23 角色解耦；新剧本加角色无需改引擎 |
| LLM | 统一接口 + JSON 输出 + 降级 | 关键节点必须 LLM，但 LLM 失败不能阻断游戏 |
| 前端 | 原生 JS（无框架） | 部署零依赖；规模适合；后续可换 Vue/React |
| 私密信息 | 仅 SocketIO `to=sid` | 浏览器无 localStorage；服务端权威 |

## 附录 B：扩展点预留

- **新剧本**：在 `roles/fabled/` 加新传奇；在 `engine/night_scheduler.py` 加新顺序；角色自动注册（装饰器）。
- **多剧本同存**：`config.py` 加 `SCRIPT_REGISTRY`，UI 大厅加剧本选择。
- **说书人教学模式**：`state.mode = "teaching"`，每个 night_action 后打印 LLM 解释。
- **录播**：所有 `state_update` 事件写入 `recordings/<room_code>.jsonl`，配合前端重放。

---

> 本文档以「可执行性」为首要目标。每个钩子、Pydantic 模型、事件名、文件路径都已细化到可直接编码的程度。后续开发应严格按此架构落地，重大偏离需重新走设计评审。
