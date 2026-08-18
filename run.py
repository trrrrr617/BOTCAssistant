"""应用入口。"""
from __future__ import annotations

import config
from server import create_app
from server.extensions import socketio


app = create_app()


if __name__ == "__main__":
    # eventlet 已被 flask-socketio 自动 monkey-patch
    print(f"\n  Blood on the Clocktower — Storyteller Assistant")
    print(f"  proudly presented by tr!&Claude code, currently in alpha testing\n")
    print(f"  Lobby:        http://{config.HOST}:{config.PORT}/")
    print(f"  Storyteller:  http://{config.HOST}:{config.PORT}/st/<code>")
    print(f"  Player:       http://{config.HOST}:{config.PORT}/p/<code>\n")
    socketio.run(
        app,
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG,
        use_reloader=False,
    )
