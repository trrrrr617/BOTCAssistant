"""Flask 应用工厂。"""
from __future__ import annotations

import eventlet
eventlet.monkey_patch()

from flask import Flask

import config
from server.extensions import socketio


def create_app() -> Flask:
    """构造 Flask 应用并挂载 SocketIO。"""
    app = Flask(
        __name__,
        template_folder=str(config.TEMPLATES_DIR),
        static_folder=str(config.STATIC_DIR),
    )
    app.config["SECRET_KEY"] = "storyteller-assistant-alpha"

    # 挂载 HTTP 路由
    from server.routes import bp as routes_bp
    app.register_blueprint(routes_bp)

    # 初始化 SocketIO
    socketio.init_app(
        app,
        cors_allowed_origins="*",
        async_mode="eventlet",
        ping_interval=config.HEARTBEAT_INTERVAL,
        ping_timeout=config.HEARTBEAT_TIMEOUT,
    )

    # 注册 WebSocket 事件
    from server import socketio_gateway  # noqa: F401  — 副作用:注册 on_<event> 处理器

    # 启动房间不活动清理后台 greenlet(默认 10 小时)
    if config.ROOM_INACTIVITY_TIMEOUT_SEC > 0:
        from server.cleanup import start_cleanup_loop
        start_cleanup_loop()

    return app
