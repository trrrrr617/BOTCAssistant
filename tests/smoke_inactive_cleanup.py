"""Stage 4+: 房间不活动自动清理测试(纯模块级,不需要 server)。"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import eventlet  # noqa
eventlet.monkey_patch()

import time
import config
from server.room.room import Room
from server.room.room_manager import get_room_manager
from server.cleanup import cleanup_once, run_cleanup_loop


def _run():
    mgr = get_room_manager()

    # 把阈值改短便于测试
    original_timeout = config.ROOM_INACTIVITY_TIMEOUT_SEC
    original_interval = config.ROOM_CLEANUP_INTERVAL_SEC
    config.ROOM_INACTIVITY_TIMEOUT_SEC = 1
    config.ROOM_CLEANUP_INTERVAL_SEC = 1

    try:
        # A. 创建 3 个房间:其中 2 个超时
        r1 = mgr.create_room(code="AAA1")
        r2 = mgr.create_room(code="BBB2")
        r3 = mgr.create_room(code="CCC3")

        # 模拟 r1, r3 是 100 秒前活动过的
        r1.last_activity_at = time.time() - 100
        r3.last_activity_at = time.time() - 100

        closed = cleanup_once()
        assert closed == 2, f"expected 2, got {closed}"
        assert mgr.get_room("AAA1") is None, "r1 should be destroyed"
        assert mgr.get_room("BBB2") is not None, "r2 should survive"
        assert mgr.get_room("CCC3") is None, "r3 should be destroyed"
        print("[PASS] A. cleanup_once destroys idle rooms, preserves active")

        # B. 边界:刚刚 touch 的房间不删
        r4 = mgr.create_room(code="DDD4")
        r4.touch()
        closed = cleanup_once()
        assert closed == 0, f"expected 0, got {closed}"
        assert mgr.get_room("DDD4") is not None
        print("[PASS] B. fresh room is not destroyed")

        # C. 阈值=0 关闭自动清理
        config.ROOM_INACTIVITY_TIMEOUT_SEC = 0
        r5 = mgr.create_room(code="EEE5")
        r5.last_activity_at = time.time() - 99999
        closed = cleanup_once()
        assert closed == 0
        assert mgr.get_room("EEE5") is not None
        print("[PASS] C. ROOM_INACTIVITY_TIMEOUT_SEC=0 disables auto cleanup")

        # 还原 + 清理
        config.ROOM_INACTIVITY_TIMEOUT_SEC = original_timeout
        config.ROOM_CLEANUP_INTERVAL_SEC = original_interval
        mgr.destroy_room("BBB2")
        mgr.destroy_room("DDD4")
        mgr.destroy_room("EEE5")

        # D. run_cleanup_loop 在后台跑一会,验证能 scan + destroy
        config.ROOM_INACTIVITY_TIMEOUT_SEC = 1
        config.ROOM_CLEANUP_INTERVAL_SEC = 1
        r6 = mgr.create_room(code="FFF6")
        r6.last_activity_at = time.time() - 100

        # 用 spawn 跑 cleanup loop,等几秒后停止
        gt = eventlet.spawn(run_cleanup_loop)
        eventlet.sleep(2.5)
        gt.kill()

        assert mgr.get_room("FFF6") is None, "loop should destroy r6 within ~2.5s"
        print("[PASS] D. run_cleanup_loop spawns and destroys idle rooms")
    finally:
        config.ROOM_INACTIVITY_TIMEOUT_SEC = original_timeout
        config.ROOM_CLEANUP_INTERVAL_SEC = original_interval
        # 兜底清理
        for code in ["AAA1", "BBB2", "CCC3", "DDD4", "EEE5", "FFF6"]:
            mgr.destroy_room(code)


if __name__ == "__main__":
    _run()
    print("\n[OK] smoke_inactive_cleanup all tests passed")
