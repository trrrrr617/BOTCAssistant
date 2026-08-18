"""房间不活动自动清理后台任务。

策略:
  - 用 eventlet.spawn 启动一个常驻 greenlet
  - 每 ROOM_CLEANUP_INTERVAL_SEC 秒扫描一次 RoomManager._rooms
  - 超过 ROOM_INACTIVITY_TIMEOUT_SEC 无活动的房间直接 destroy
  - 销毁前向房间内所有连接的 sid 发 "room_closed" 事件并 disconnect
"""
from __future__ import annotations

import time

import eventlet

import config
from server.extensions import socketio
from server.room.room_manager import get_room_manager


def _close_inactive_room(room, reason: str) -> None:
    """关闭单个超时房间:广播 + 断开 + destroy。"""
    code = room.code
    # 向所有还连着的 sid 推 room_closed + 强制断开
    for rp in list(room.runtime_players.values()):
        if rp.sid is None:
            continue
        try:
            socketio.emit(
                "room_closed",
                {"code": code, "reason": reason},
                to=rp.sid,
            )
        except Exception:
            # emit 失败不影响后续销毁
            pass
        try:
            socketio.disconnect(rp.sid)
        except Exception:
            pass
    get_room_manager().destroy_room(code)


def cleanup_once() -> int:
    """扫描一次,关闭所有超时房间。返回关闭数量。"""
    if config.ROOM_INACTIVITY_TIMEOUT_SEC <= 0:
        return 0
    manager = get_room_manager()
    now = time.time()
    closed = 0
    # 取快照后再迭代:避免销毁过程中修改字典
    for code in list(manager.room_codes):
        room = manager.get_room(code)
        if room is None:
            continue
        idle = now - room.last_activity_at
        if idle >= config.ROOM_INACTIVITY_TIMEOUT_SEC:
            _close_inactive_room(room, f"房间 {config.ROOM_INACTIVITY_TIMEOUT_SEC // 3600} 小时无活动已自动关闭")
            closed += 1
    return closed


def run_cleanup_loop() -> None:
    """常驻循环:在 eventlet greenlet 中运行,定时调用 cleanup_once。"""
    interval = max(1, config.ROOM_CLEANUP_INTERVAL_SEC)
    while True:
        try:
            cleanup_once()
        except Exception:
            # 单次失败不影响后续扫描
            pass
        eventlet.sleep(interval)


def start_cleanup_loop() -> None:
    """应用启动时调用:在 eventlet 上下文中 spawn 一次。"""
    eventlet.spawn(run_cleanup_loop)
