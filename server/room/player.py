"""运行时玩家对象:Pydantic Player + SocketIO sid 映射。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from server.engine.game_state import Player


def generate_player_token() -> str:
    """生成 8 位玩家令牌(同 ST 令牌的字符集)。用于 /p/<code> 鉴权。"""
    import secrets
    import string
    alphabet = "".join(c for c in (string.ascii_uppercase + string.ascii_lowercase + string.digits)
                        if c not in "0O1lI")
    return "".join(secrets.choice(alphabet) for _ in range(8))


@dataclass
class RuntimePlayer:
    """Pydantic Player + WebSocket 状态。"""

    player: Player
    sid: Optional[str] = None  # SocketIO session id
    connected: bool = True
    # 玩家令牌(加入时生成),用于 /p/<code> 鉴权
    player_token: str = field(default_factory=generate_player_token)

    # 便捷属性
    @property
    def id(self) -> str:
        return self.player.id

    @property
    def name(self) -> str:
        return self.player.name

    @property
    def is_storyteller(self) -> bool:
        return self.player.is_storyteller

    def to_public_dict(self) -> dict:
        """公开信息(对其他玩家可见)。"""
        return {
            "id": self.player.id,
            "name": self.player.name,
            "seat": self.player.seat,
            "status": self.player.status.value,
            "is_storyteller": self.player.is_storyteller,
        }

    def to_storyteller_dict(self) -> dict:
        """说书人可见(包含真实身份)。"""
        d = self.to_public_dict()
        # true_role / apparent_role 现在是字符串(可能是 RoleId.value 或 ScriptRole.id)
        tr = self.player.true_role
        ar = self.player.apparent_role
        d["true_role"] = tr if tr else None
        d["apparent_role"] = ar if ar else None
        # 若 true_role != apparent_role(被 replace_with 替换过),
        # 标志 actual_role = true_role 供 ST 备注显示。
        d["is_replaced"] = bool(tr and ar and tr != ar)
        d["is_poisoned"] = self.player.is_poisoned
        d["is_drunk"] = self.player.is_drunk
        d["st_notes"] = [n.model_dump() for n in self.player.st_notes]
        d["connected"] = self.connected
        return d
