"""板子(Script)数据模型 + 编码/解码。

板子完全由说书人在每次开房时录入,不需要后端持久化。
导出的代码字符串是 Base64(JSON),包含板子的全部信息,可以复制分享。

JSON 格式:
{
  "v": 1,
  "id": "<script_id>",
  "name": "<display_name>",
  "notes": "...",
  "roles": [
    {
      "id": "<role_id>",
      "name": "<display_name>",
      "team": "townsfolk"|"outsider"|"minion"|"demon",
      "outsider_mod": int,
      "minion_mod": int,
      "requires": [other_role_id, ...],
      "first_night": bool,
      "other_night": bool
    },
    ...
  ]
}

代码字符串前缀: BOTC-SCRIPT-V1:<base64(json)>
"""
from __future__ import annotations

import base64
import json
from typing import List

from pydantic import BaseModel, Field, field_validator


_VALID_TEAMS = ("townsfolk", "outsider", "minion", "demon", "fabled")


class ScriptRole(BaseModel):
    """板子中的单个角色(由说书人录入)。"""
    id: str
    name: str = ""
    team: str  # townsfolk / outsider / minion / demon
    outsider_mod: int = 0  # 该角色在场时,外来者数量 +/- 调整(T↔O 转换)
    minion_mod: int = 0    # 该角色在场时,爪牙数量 +/- 调整(T↔M 转换)
    demon_mod: int = 0     # 该角色在场时,恶魔数量 +/- 调整(T↔D 转换)
    requires: List[str] = Field(default_factory=list)  # 该角色在场时要求同在场的角色 ID
    # 分配时,该角色的实际身份会从该列表中随机抽取(优先选不在场的 ID)
    # 用于「酒鬼」等占位机制:玩家以为自己是被替换的 ID,实际是本占位
    replace_with: List[str] = Field(default_factory=list)
    first_night: bool = False   # 该角色是否在首夜行动
    other_night: bool = False   # 该角色是否在后续夜晚行动
    day_action: bool = False    # 该角色在白天是否需要被说书人特别注意(如投毒者)
    notes: str = ""             # 角色备注(ST 控制台显示在「在场角色备注」区)

    @field_validator("team")
    @classmethod
    def _validate_team(cls, v: str) -> str:
        if v not in _VALID_TEAMS:
            raise ValueError(
                f"无效阵营: {v}(必须为 townsfolk/outsider/minion/demon/fabled)"
            )
        return v


class Script(BaseModel):
    """完整板子定义。"""
    id: str
    name: str
    roles: List[ScriptRole] = Field(default_factory=list)
    notes: str = ""

    # ---- 编码/解码 ----

    def encode(self) -> str:
        """导出为可分享的代码字符串(URL-safe Base64 + JSON)。"""
        payload = {"v": 1, **self.model_dump()}
        json_str = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        b64 = base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("ascii")
        return f"BOTC-SCRIPT-V1:{b64}"

    @classmethod
    def decode(cls, code: str) -> "Script":
        """从代码字符串解析为 Script 对象。"""
        if not isinstance(code, str) or not code.startswith("BOTC-SCRIPT-V1:"):
            raise ValueError("代码格式错误(必须以 'BOTC-SCRIPT-V1:' 开头)")
        b64 = code[len("BOTC-SCRIPT-V1:"):]
        try:
            raw = base64.urlsafe_b64decode(b64.encode("ascii")).decode("utf-8")
        except Exception as e:
            raise ValueError(f"代码 Base64 解码失败: {e}")
        try:
            data = json.loads(raw)
        except Exception as e:
            raise ValueError(f"代码 JSON 解析失败: {e}")
        if not isinstance(data, dict):
            raise ValueError("代码内容不是有效的对象")
        version = data.pop("v", 1)
        if version != 1:
            raise ValueError(f"不支持的代码版本: {version}")
        # 校验角色 team
        for r in data.get("roles", []):
            if r.get("team") not in _VALID_TEAMS:
                raise ValueError(f"角色 {r.get('id')} 的阵营无效: {r.get('team')}")
        return cls(**data)

    # ---- 派生属性 ----

    def first_night_order(self) -> List[str]:
        """首夜行动顺序(按 roles 中出现顺序,仅含 first_night=True 的角色)。"""
        return [r.id for r in self.roles if r.first_night]

    def other_nights_order(self) -> List[str]:
        """后续夜晚行动顺序。"""
        return [r.id for r in self.roles if r.other_night]

    def get_role_team(self, role_id: str) -> str:
        """返回角色所在阵营,未找到则返回 'fabled'。"""
        for r in self.roles:
            if r.id == role_id:
                return r.team
        return "fabled"

    def get_role_name(self, role_id: str) -> str:
        """返回角色显示名,未找到回退为 ID。"""
        for r in self.roles:
            if r.id == role_id:
                return r.name or r.id
        return role_id or "?"


def make_default_script() -> Script:
    """生成一个空板子(只有 ST 在大厅录入后会用上)。"""
    return Script(id="", name="", roles=[], notes="")


def make_legacy_compat_script() -> Script:
    """兜底:当玩家在没设置板子时,使用一个最小可用板子。

    包含 5 个最常见角色,保证游戏可进行(主要用于离线兼容)。
    """
    return Script(
        id="legacy_default",
        name="兼容默认板子",
        roles=[
            ScriptRole(id="noble", name="贵族", team="townsfolk"),
            ScriptRole(id="snake_charmer", name="舞蛇人", team="townsfolk"),
            ScriptRole(id="balloonist", name="气球驾驶员", team="townsfolk"),
            ScriptRole(id="poisoner", name="投毒者", team="minion", other_night=True),
            ScriptRole(id="hadjiya", name="哈迪寂亚", team="demon", other_night=True),
        ],
        notes="兜底默认板子,5 人游戏可跑",
    )