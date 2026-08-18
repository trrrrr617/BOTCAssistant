"""HTTP 路由。"""
from __future__ import annotations

from flask import Blueprint, abort, render_template, request

from server.room.room_manager import get_room_manager


bp = Blueprint("main", __name__)


@bp.get("/")
def lobby():
    """大厅首页。"""
    return render_template("lobby.html")


@bp.get("/st/")
@bp.get("/st/<code>")
def storyteller(code: str | None = None):
    """说书人控制台。

    鉴权:任何知道房间号的人都能访问 /st/<code>,但若房间已存在且 ?t=<token>
    不匹配房间的 st_token,则只渲染一个拒绝页面,不暴露任何 ST 数据。
    创建房间时 ?t 可省略(create_room 事件返回 token 后由前端 redirect)。
    """
    manager = get_room_manager()
    if code is None:
        return render_template("storyteller.html", room_code=None)

    room = manager.get_room(code)
    if room is None:
        # 房间不存在:放行让 ST 通过 create_room 创建(此时 ?t 无意义)
        return render_template("storyteller.html", room_code=code.upper())

    # 房间存在:必须 ?t=<正确 st_token> 才能进
    token = request.args.get("t", "")
    if token and token == room.st_token:
        return render_template("storyteller.html", room_code=room.code)

    # 房间存在但 token 缺失或不匹配:渲染拒绝页(st_token_invalid=True)
    return render_template(
        "storyteller.html",
        room_code=room.code,
        st_token_invalid=True,
    )


@bp.get("/p/")
@bp.get("/p/<code>")
def player(code: str | None = None):
    """玩家页面。

    鉴权:和 /st/&lt;code&gt; 一样,任何访客都能打开 URL,但 ?t=&lt;player_token&gt; 必须匹配
    该玩家的 player_token 才能进。否则只渲染拒绝页,不暴露任何游戏数据。
    """
    manager = get_room_manager()
    if code is None:
        abort(404)
    room = manager.get_room(code)
    if room is None:
        return render_template("player.html", room_code=code.upper(), room_exists=False)

    # 房间存在:必须 ?t=<正确 player_token> 才能进
    # 这里只能校验「该 token 存在于此房间的某个玩家身上」,
    # 具体是哪个玩家在 reconnect 时再校验(因为前端要拿 player_id+player_token)
    token = request.args.get("t", "")
    if token:
        matched = any(rp.player_token == token for rp in room.runtime_players.values())
        if matched:
            return render_template("player.html", room_code=room.code, room_exists=True)
    return render_template(
        "player.html",
        room_code=room.code,
        room_exists=True,
        player_token_invalid=True,
    )
