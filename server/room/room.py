"""单个房间:持有 GameState + RuntimePlayer 列表 + 房间事件。"""
from __future__ import annotations

import secrets
import string
import time
from typing import Optional

import config
from server.engine.game_state import GameState, Player
from server.engine.phase import Phase
from server.room.player import RuntimePlayer


def generate_room_code() -> str:
    """生成 4 位大写字母房间号。"""
    alphabet = string.ascii_uppercase
    return "".join(secrets.choice(alphabet) for _ in range(config.ROOM_CODE_LEN))


def generate_st_token() -> str:
    """生成 8 位 ST 令牌(大小写字母+数字,排除易混字符 0/O/1/l/I)。
    用于 ST 控制台鉴权:只有持有正确令牌的浏览器才能操作 ST 视角。
    """
    alphabet = "".join(c for c in (string.ascii_uppercase + string.ascii_lowercase + string.digits)
                        if c not in "0O1lI")
    return "".join(secrets.choice(alphabet) for _ in range(8))


class Room:
    """一个房间,持有 GameState 与所有玩家。"""

    def __init__(self, code: Optional[str] = None) -> None:
        self.code: str = code or generate_room_code()
        self.state: GameState = GameState(room_code=self.code)
        self.runtime_players: dict[str, RuntimePlayer] = {}
        # sid -> player_id 映射(便于断线/重连)
        self.sid_to_player: dict[str, str] = {}
        # ST 控制台令牌(创建房间时生成,只有持有该令牌的浏览器能进入 ST 视角)
        self.st_token: str = generate_st_token()
        # 最近一次活动时间(秒) — 用于 10 小时无活动自动清理。
        # 任何 socketio 事件 handler 在改房间状态前调用 touch()。
        self.last_activity_at: float = time.time()

    def touch(self) -> None:
        """刷新最近活动时间。"""
        self.last_activity_at = time.time()

    # ---- 玩家管理 ----
    def add_player(self, runtime_player: RuntimePlayer) -> RuntimePlayer:
        """加入玩家到房间(GameState 与 RuntimePlayer 双向同步)。"""
        self.runtime_players[runtime_player.id] = runtime_player
        # 同步到 GameState
        if not any(p.id == runtime_player.id for p in self.state.players):
            self.state.players.append(runtime_player.player)
        if runtime_player.sid:
            self.sid_to_player[runtime_player.sid] = runtime_player.id
            # 记录说书人
            if runtime_player.is_storyteller and self.state.story_teller_id is None:
                self.state.story_teller_id = runtime_player.id
        return runtime_player

    def remove_player_by_sid(self, sid: str) -> Optional[RuntimePlayer]:
        player_id = self.sid_to_player.pop(sid, None)
        if player_id is None:
            return None
        rp = self.runtime_players.get(player_id)
        if rp:
            rp.sid = None
            rp.connected = False
        return rp

    def rebind_sid(self, player_id: str, new_sid: str) -> None:
        rp = self.runtime_players.get(player_id)
        if rp:
            if rp.sid and rp.sid in self.sid_to_player:
                self.sid_to_player.pop(rp.sid, None)
            rp.sid = new_sid
            rp.connected = True
            self.sid_to_player[new_sid] = player_id

    def get_player_by_sid(self, sid: str) -> Optional[RuntimePlayer]:
        pid = self.sid_to_player.get(sid)
        if pid is None:
            return None
        return self.runtime_players.get(pid)

    def get_runtime(self, player_id: str) -> Optional[RuntimePlayer]:
        return self.runtime_players.get(player_id)

    def refresh_from_state(self) -> None:
        """state.model_copy(deep=True) 会产生新的 Pydantic Player 对象,
        但 runtime_players 仍持有旧对象。此方法将 runtime_players 的 player
        字段同步到当前 state.players 中的最新对象。
        """
        for rp in self.runtime_players.values():
            new_p = next((p for p in self.state.players if p.id == rp.id), None)
            if new_p is not None:
                rp.player = new_p

    def list_players_public(self) -> list[dict]:
        # ST 在前(seat=0 固定),玩家按 seat 升序 — 配合座位交换功能
        rps = sorted(
            self.runtime_players.values(),
            key=lambda rp: (not rp.player.is_storyteller, rp.player.seat),
        )
        return [rp.to_public_dict() for rp in rps]

    def list_players_for_storyteller(self) -> list[dict]:
        rps = sorted(
            self.runtime_players.values(),
            key=lambda rp: (not rp.player.is_storyteller, rp.player.seat),
        )
        return [rp.to_storyteller_dict() for rp in rps]

    @property
    def player_count(self) -> int:
        return len(self.runtime_players)

    @property
    def phase(self) -> Phase:
        return self.state.phase
