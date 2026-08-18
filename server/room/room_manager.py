"""全局房间管理器。"""
from __future__ import annotations

import threading
from typing import Optional

from server.room.room import Room


class RoomManager:
    """单例:管理所有活跃房间。"""

    _instance: Optional["RoomManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "RoomManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._rooms = {}
        return cls._instance

    # ---- 房间 CRUD ----
    def create_room(self, code: Optional[str] = None) -> Room:
        room = Room(code=code)
        # 避免房间号冲突
        while room.code in self._rooms:
            room = Room()
        self._rooms[room.code] = room
        return room

    def get_room(self, code: str) -> Optional[Room]:
        return self._rooms.get(code.upper())

    def get_or_create(self, code: str) -> Room:
        room = self.get_room(code)
        if room is None:
            room = self.create_room(code=code.upper())
        return room

    def destroy_room(self, code: str) -> None:
        self._rooms.pop(code.upper(), None)

    @property
    def room_codes(self) -> list[str]:
        return list(self._rooms.keys())


def get_room_manager() -> RoomManager:
    return RoomManager()
