"""全局配置。从环境变量加载,提供默认值。"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件(若存在)
_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(_PROJECT_ROOT / ".env")


# ---- 服务器 ----
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "5000"))
DEBUG: bool = os.getenv("FLASK_DEBUG", "0") == "1"


# ---- LLM ----
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "anthropic")
LLM_MODEL: str = os.getenv("LLM_MODEL", "MiniMax-M3")
LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "20"))
LLM_FALLBACK: str = os.getenv("LLM_FALLBACK", "template")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")


# ---- 剧本 ----
DEFAULT_SCRIPT: str = os.getenv("DEFAULT_SCRIPT", "midnight_oasis")


# ---- 路径 ----
PROJECT_ROOT: Path = _PROJECT_ROOT
TEMPLATES_DIR: Path = PROJECT_ROOT / "templates"
STATIC_DIR: Path = PROJECT_ROOT / "static"


# ---- 房间号长度 ----
ROOM_CODE_LEN: int = 4


# ---- 心跳 / 超时 ----
HEARTBEAT_INTERVAL: int = 25
HEARTBEAT_TIMEOUT: int = 60


# ---- 房间不活动自动清理 ----
# 房间超过此秒数没有任何 socketio 事件活动时,被自动 destroy。
# 默认 10 小时。设为 0 关闭自动清理。
ROOM_INACTIVITY_TIMEOUT_SEC: int = int(os.getenv("ROOM_INACTIVITY_TIMEOUT_SEC", str(10 * 3600)))
# 后台清理 greenlet 多久跑一次扫描
ROOM_CLEANUP_INTERVAL_SEC: int = int(os.getenv("ROOM_CLEANUP_INTERVAL_SEC", "60"))
