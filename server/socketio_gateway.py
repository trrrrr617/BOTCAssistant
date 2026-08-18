"""WebSocket 事件网关。所有 on_<event> 处理函数在此注册。"""
from __future__ import annotations

import logging
from typing import Any, Optional

from flask import request
from flask_socketio import emit, join_room, leave_room

from server.engine import state_machine
from server.engine.game_state import Alignment, PendingDeath, Phase, Player, PlayerStatus, RoleId
from server.engine.script import Script
from server.engine.phase import PhaseTransitionError
from server.engine.state_machine import (
    begin_day,
    begin_nomination,
    cast_vote,
    end_day,
    end_nomination_phase,
    pass_nomination,
    player_add_log,
    player_send_to_st,
    player_set_notes,
    reset_game_for_rematch,
    st_add_log,
    st_change_role,
    st_toggle_fabled,
    st_kill_player,
    st_revive_player,
    st_set_drunk,
    st_set_notes,
    st_set_poisoned,
    start_game,
    start_nomination,
    request_swap,
    accept_swap,
    decline_swap,
    cancel_swap,
    st_swap_seats,
)
from server.extensions import socketio
from server.room.player import RuntimePlayer
from server.room.room import Room
from server.room.room_manager import get_room_manager

log = logging.getLogger(__name__)


# ---- 辅助:定位 sid 所在的房间 ----

def _find_room_by_sid(sid: str) -> Optional[Room]:
    manager = get_room_manager()
    for code in manager.room_codes:
        room = manager.get_room(code)
        if room and sid in room.sid_to_player:
            # 任何 socketio 事件 handler 走到这里都视为"活动",刷新时间戳。
            # 10 小时无活动清理线程以此判断。
            room.touch()
            return room
    return None


def _require_storyteller(room: Room) -> bool:
    """检查请求 sid 是否为该房间的说书人。"""
    rp = room.get_player_by_sid(request.sid)
    return rp is not None and rp.is_storyteller


def _nomination_dict(n) -> dict:
    return {
        "id": n.id,
        "nominator_id": n.nominator_id,
        "nominee_id": n.nominee_id,
        "votes": [{"voter_id": v.voter_id, "value": v.value, "is_dead_vote": v.is_dead_vote} for v in n.votes],
        "resolved": n.resolved,
        "met_threshold": n.met_threshold,
        "executed": n.executed,
        "passed": n.passed,
        "yes_count": n.yes_count,
        "no_count": n.no_count,
        "reason": n.reason,
    }


def _public_payload(room: Room, *, viewer_id: Optional[str] = None) -> dict:
    """对所有玩家可见的状态(不含私密信息)。

    夜间(FIRST_NIGHT / NIGHT)时,对非 ST 隐藏死亡/复活状态——
    本夜新发生的死亡连被杀玩家本人也看不到,直到 begin_day 公开。
    """
    s = room.state
    players = room.list_players_public()
    if s.phase in (Phase.NIGHT, Phase.FIRST_NIGHT):
        masked = []
        pending_kill_ids = {
            pending.player_id
            for pending in s.pending_deaths
            if pending.kind == "kill"
        }
        for p in players:
            if p.get("is_storyteller"):
                # ST 在公共列表中仍以 alive 展示(其身份已在 st_state_update 中)
                masked.append(p)
            elif (
                viewer_id is not None
                and p["id"] == viewer_id
                and p["id"] not in pending_kill_ids
            ):
                # 自己之前已经死亡的状态仍可见;本夜新死亡须等白天公开
                masked.append(p)
            else:
                masked.append({**p, "status": "alive"})
        players = masked

    # 恶魔的伪装:仅恶魔/爪牙玩家可见(viewer_id 为 None 时如 ST 路径由 _st_payload 覆盖)
    demon_disguises: list[str] = []
    viewer_dead_vote_used = False
    if viewer_id is not None:
        viewer = next((p for p in s.players if p.id == viewer_id), None)
        if viewer and viewer.true_role:
            script = s.script
            if script:
                role_def = next((r for r in script.roles if r.id == viewer.true_role), None)
                if role_def and role_def.team in ("demon", "minion"):
                    demon_disguises = list(s.demon_disguises or [])
        # 仅当前 viewer 自己可见:本轮死亡期间是否已"实质性"投过赞成票。
        # 用来让玩家页面正确禁用 YES 按钮(尤其是 end_nomination_phase 后
        # current_nominations 被清空,前端无法仅从提名数据推导)。
        if viewer is not None:
            viewer_dead_vote_used = bool(viewer.dead_vote_used)

    return {
        "room_code": room.code,
        "phase": s.phase.value,
        "day": s.day,
        "night": s.night,
        "chat_started_at": s.chat_started_at,
        "chat_duration_sec": s.chat_duration_sec,
        "players": players,
        "current_nominations": [_nomination_dict(n) for n in s.current_nominations],
        "nominated_in_phase": list(s.nominated_in_phase),
        "passed_in_phase": list(s.passed_in_phase),
        "nominated_as_target": list(s.nominated_as_target),
        "nomination_index": s.nomination_index,
        "winner": s.winner,
        "win_reason": s.win_reason,
        "script": s.script.model_dump() if s.script else None,
        "demon_disguises": demon_disguises,
        "fabled_in_play": list(s.fabled_in_play),
        "viewer_dead_vote_used": viewer_dead_vote_used,
        "pending_swap": s.pending_swap.model_dump() if s.pending_swap else None,
    }


def _st_payload(room: Room) -> dict:
    """说书人可见(包含真实身份 + 活动日志)。"""
    p = _public_payload(room)
    p["players"] = room.list_players_for_storyteller()
    p["log"] = list(room.state.log or [])
    # 添加板子代码(ST 可用于查看/导出)
    if room.state.script:
        p["script_code"] = room.state.script.encode()
    # 恶魔的伪装(ST 总是看到)
    p["demon_disguises"] = list(room.state.demon_disguises or [])
    return p


# 公开日志类别(玩家可见)
_PUBLIC_LOG_KINDS = {
    "game_start", "day_start", "night_start",
    "nomination_start", "nomination_result", "nomination_failed",
    "execution", "pass", "game_over",
    "st_kill", "st_revive",
    "fabled_join", "fabled_leave",  # 传奇角色上场/离场
    "st_manual_log_public",  # ST 标记为「公开」的日志
}


def _player_state_payload(room: Room, player_id: str) -> dict:
    """单个玩家的个性化状态(含过滤日志 + 私人批注 + 私人日志)。

    日志过滤规则:
      - visibility=st_only→仅说书人可见,不会进入玩家状态
      - visibility=night_st_only 且仍在夜间→白天开始前不进入玩家状态
      - 公开类别(kind in _PUBLIC_LOG_KINDS)→所有人可见
      - 私密类别(visibility=private_to_player 且 target_id == player_id)→仅目标可见
      - 玩家发给 ST(visibility=private_to_st 且 sender_id == player_id)→发送者自己可见
      - 其余(ST-only、target 不是自己)→对当前玩家隐藏
    """
    s = room.state
    player = s.find_player(player_id)
    filtered_log = []
    for entry in (s.log or []):
        kind = entry.get("kind")
        visibility = entry.get("visibility")
        if visibility == "st_only":
            continue
        if visibility == "night_st_only" and s.phase in (Phase.NIGHT, Phase.FIRST_NIGHT):
            continue
        if kind in _PUBLIC_LOG_KINDS:
            filtered_log.append(entry)
        elif visibility == "private_to_player" and entry.get("target_id") == player_id:
            filtered_log.append(entry)
        elif visibility == "private_to_st" and entry.get("sender_id") == player_id:
            filtered_log.append(entry)
    notes_dict = {}
    if player:
        for tid, note_list in player.player_notes.items():
            notes_dict[tid] = [n.model_dump() for n in note_list]
    return {
        "my_id": player_id,
        "filtered_log": filtered_log,
        "private_log": list(player.private_log) if player else [],
        "player_notes": notes_dict,
    }


def _broadcast_state(room: Room) -> None:
    """向房间内所有人广播 state_update。说书人额外收到 st_state_update。
    每个玩家额外收到 player_state(个性化日志+批注)。
    夜间 state_update 按 viewer 个性化(本夜新死亡对所有玩家隐藏)。"""
    for rp in room.runtime_players.values():
        if rp.sid is None:
            continue
        payload = _public_payload(room, viewer_id=rp.id)
        socketio.emit("state_update", payload, to=rp.sid)
    st_rp = next((rp for rp in room.runtime_players.values() if rp.is_storyteller), None)
    if st_rp and st_rp.sid:
        socketio.emit("st_state_update", _st_payload(room), to=st_rp.sid)
    # 向每个已连接玩家发送个性化状态
    for rp in room.runtime_players.values():
        if rp.is_storyteller or not rp.sid:
            continue
        socketio.emit("player_state", _player_state_payload(room, rp.id), to=rp.sid)


def _set_state(room: Room, new_state) -> None:
    """统一的状态变更入口:赋值并同步 runtime_players 的 Player 引用。"""
    room.state = new_state
    room.refresh_from_state()


def _send_role_assigned(room: Room) -> None:
    """向每位玩家私密发送其身份(从最新 state.players 读取,避免深拷贝失同步)。"""
    for rp in room.runtime_players.values():
        if rp.is_storyteller:
            continue
        if rp.sid is None:
            continue
        # 从最新 state 读,而不是 rp.player(state 深拷贝后 rp.player 可能是旧对象)
        state_player = next((p for p in room.state.players if p.id == rp.id), None)
        if state_player is None:
            continue
        role = state_player.true_role
        if role is None:
            continue
        # true_role 现在是字符串(ScriptRole.id)
        role_str = role.value if hasattr(role, "value") else str(role)
        apparent = state_player.apparent_role
        apparent_str = apparent.value if hasattr(apparent, "value") else (str(apparent) if apparent else role_str)
        # 注:不推送 is_poisoned/is_drunk 给玩家(隐藏信息,只有 ST 可见)
        socketio.emit(
            "role_assigned",
            {
                "true_role": role_str,
                "apparent_role": apparent_str,
            },
            to=rp.sid,
        )


# ---- 事件:客户端 -> 服务端 ----

@socketio.on("connect")
def on_connect():
    log.info("客户端连接: sid=%s", request.sid)
    emit("connected", {"sid": request.sid})


@socketio.on("disconnect")
def on_disconnect():
    """断开时**标记离线**,不删除玩家对象(允许刷新后重连恢复)。"""
    sid = request.sid
    log.info("客户端断开: sid=%s", sid)
    manager = get_room_manager()
    for code in manager.room_codes:
        room = manager.get_room(code)
        if room is None:
            continue
        if sid not in room.sid_to_player:
            continue
        rp = room.get_player_by_sid(sid)
        if rp is None:
            continue
        # 标记离线但保留
        rp.connected = False
        if sid in room.sid_to_player:
            del room.sid_to_player[sid]
        rp.sid = None
        log.info("玩家 %s 离线 (room=%s)", rp.name, code)
        _broadcast_player_list(code)


# ---- 板子(Script)管理:基于代码字符串(无需后端持久化) ----

@socketio.on("parse_script_code")
def on_parse_script_code(data: dict[str, Any]):
    """ST 粘贴一段代码 → 服务端校验并返回解析后的 Script(不写入状态)。"""
    sid = request.sid
    code = (data or {}).get("code", "")
    try:
        script = Script.decode(code)
    except Exception as e:
        emit("error", {"code": "PARSE_SCRIPT_FAILED", "message": str(e)})
        return
    socketio.emit("script_parsed", {
        "script": script.model_dump(),
        "code": script.encode(),
    }, to=sid)


@socketio.on("set_script")
def on_set_script(data: dict[str, Any]):
    """ST 将当前编辑的板子应用到房间(写入 state.script)。只能在 LOBBY 阶段。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    if not _require_storyteller(room):
        emit("error", {"code": "NOT_STORYTELLER", "message": "只有说书人可以设置板子"})
        return
    data = data or {}
    script_data = data.get("script")
    if not script_data:
        emit("error", {"code": "INVALID_INPUT", "message": "缺少 script 数据"})
        return
    try:
        script = Script.model_validate(script_data)
    except Exception as e:
        emit("error", {"code": "INVALID_SCRIPT", "message": f"板子格式无效: {e}"})
        return
    if room.state.phase != Phase.LOBBY:
        emit("error", {"code": "WRONG_PHASE", "message": f"游戏已开始,无法更换板子"})
        return
    room.state = room.state.model_copy(deep=True)
    room.state.script = script
    room.refresh_from_state()
    log.info("ST 在房间 %s 中应用板子 %s (%d 角色)", room.code, script.id, len(script.roles))
    socketio.emit("script_applied", {"script": script.model_dump(), "code": script.encode()}, to=request.sid)
    _broadcast_state(room)


@socketio.on("create_room")
def on_create_room(data: dict[str, Any]):
    """说书人创建房间。"""
    sid = request.sid

    # 防止同 sid 重复创建
    existing = _find_room_by_sid(sid)
    if existing is not None:
        rp = existing.get_player_by_sid(sid)
        if rp is not None and rp.is_storyteller:
            # 已经是该房间的说书人,直接恢复
            rp.connected = True
            join_room(existing.code)
            emit(
                "room_created",
                {
                    "room_code": existing.code,
                    "player_id": rp.id,
                    "is_storyteller": True,
                    "players": existing.list_players_public(),
                },
            )
            _broadcast_player_list(existing.code)
            return

    manager = get_room_manager()
    storyteller_name = (data or {}).get("name", "说书人").strip() or "说书人"
    room = manager.create_room()
    room.touch()  # 新建房间也视作一次活动

    rp = RuntimePlayer(
        player=Player(
            name=storyteller_name,
            seat=0,
            is_storyteller=True,
        ),
        sid=sid,
    )
    room.add_player(rp)
    join_room(room.code)

    log.info("说书人 %s 创建房间 %s", storyteller_name, room.code)
    emit(
        "room_created",
        {
            "room_code": room.code,
            "player_id": rp.id,
            "is_storyteller": True,
            "st_token": room.st_token,  # ← ST 浏览器存 localStorage,后续访问 /st/<code> 需带
            "players": room.list_players_public(),
        },
    )
    _broadcast_player_list(room.code)


@socketio.on("join_room")
def on_join_room(data: dict[str, Any]):
    """玩家加入房间。同 sid 重复 join 视为重连,不创建新玩家。"""
    sid = request.sid
    code = ((data or {}).get("room_code") or "").upper()
    name = ((data or {}).get("name") or "").strip()
    # 长度上限 20(防恶意超长名撑爆 UI,也避免名字里有不可见字符)
    if len(name) > 20:
        name = name[:20]

    if not code:
        emit("error", {"code": "INVALID_INPUT", "message": "房间号不能为空"})
        return
    if not name:
        emit("error", {"code": "INVALID_NAME", "message": "名字不能为空或纯空白"})
        return

    # 1) 同 sid 已在某房间 -> 重连复用
    existing_room = _find_room_by_sid(sid)
    if existing_room is not None:
        rp = existing_room.get_player_by_sid(sid)
        if rp is not None:
            rp.connected = True
            join_room(existing_room.code)
            log.info("玩家 %s 重连至房间 %s (sid=%s)", rp.name, existing_room.code, sid)
            emit(
                "joined",
                {
                    "room_code": existing_room.code,
                    "player_id": rp.id,
                    "is_storyteller": rp.is_storyteller,
                    "players": existing_room.list_players_public(),
                },
            )
            _broadcast_player_list(existing_room.code)
            return

    # 2) 全新加入
    manager = get_room_manager()
    room = manager.get_room(code)
    if room is None:
        emit("error", {"code": "ROOM_NOT_FOUND", "message": f"房间 {code} 不存在"})
        return

    # 防重名:房间内已有同名玩家(无论是否在线)则直接拒绝
    # 同名玩家顶替逻辑已移除——避免有人意外「抢」他人身份
    for rp in room.runtime_players.values():
        if rp.name == name:
            emit("error", {
                "code": "DUPLICATE_NAME",
                "message": f"房间内已有同名玩家「{name}」",
            })
            return

    # 3) 真的新玩家 -> 分配新座位
    existing_seats = {p.player.seat for p in room.runtime_players.values()}
    seat = 1
    while seat in existing_seats:
        seat += 1

    rp = RuntimePlayer(
        player=Player(
            name=name,
            seat=seat,
            is_storyteller=False,
        ),
        sid=sid,
    )
    room.add_player(rp)
    join_room(room.code)

    log.info("玩家 %s (座位 %d) 加入房间 %s", name, seat, code)
    emit(
        "joined",
        {
            "room_code": room.code,
            "player_id": rp.id,
            "is_storyteller": False,
            "player_token": rp.player_token,  # ← 防作弊:玩家自己的令牌,只有持有它的人能进 /p/<code>
            "players": room.list_players_public(),
        },
    )
    _broadcast_player_list(room.code)


@socketio.on("reconnect_room")
def on_reconnect_room(data: dict[str, Any]):
    """说书人/玩家刷新后,用保存的 player_id + room_code 重连并绑定新 sid。"""
    sid = request.sid
    code = ((data or {}).get("room_code") or "").upper()
    player_id = (data or {}).get("player_id") or ""
    provided_st = (data or {}).get("st_token") or ""
    provided_player = (data or {}).get("player_token") or ""

    if not code or not player_id:
        emit("error", {"code": "INVALID_INPUT", "message": "缺少 room_code 或 player_id"})
        return

    manager = get_room_manager()
    room = manager.get_room(code)
    if room is None:
        emit("error", {"code": "ROOM_NOT_FOUND", "message": f"房间 {code} 不存在"})
        return

    # ST 重连必须提供正确的 st_token(防止有人拿到 player_id 后冒充 ST)
    # 玩家重连必须提供正确的 player_token(防止有人拿到 player_id 后冒充玩家)
    rp_lookahead = room.get_runtime(player_id)
    if rp_lookahead and rp_lookahead.is_storyteller:
        if provided_st != room.st_token:
            emit("error", {"code": "INVALID_ST_TOKEN", "message": "ST 令牌无效,无法进入说书人控制台"})
            return
    else:
        # 玩家:校验 player_token
        if provided_player != rp_lookahead.player_token:
            emit("error", {"code": "INVALID_PLAYER_TOKEN", "message": "玩家令牌无效,无法进入"})
            return

    rp = room.get_runtime(player_id)
    if rp is None:
        emit("error", {"code": "PLAYER_NOT_FOUND", "message": "玩家身份已失效,请重新加入"})
        return

    # 绑定新 sid
    room.rebind_sid(player_id, sid)
    join_room(room.code)
    log.info("玩家 %s 重连成功 room=%s (新 sid=%s)", rp.name, code, sid)

    event_name = "room_created" if rp.is_storyteller else "joined"
    emit(
        event_name,
        {
            "room_code": room.code,
            "player_id": rp.id,
            "is_storyteller": rp.is_storyteller,
            "players": room.list_players_public(),
            "reconnected": True,
        },
    )
    _broadcast_player_list(room.code)
    # 关键:重连后必须广播完整 state_update,这样 ST 刷新后能看到阶段、日志、按钮
    _broadcast_state(room)
    # 关键:重连后必须重新推送身份卡给该玩家,否则刷新后「你的身份」栏无法渲染
    state_player = room.state.find_player(player_id)
    if state_player and state_player.true_role and rp.sid:
        # true_role / apparent_role 已经是 str(ScriptRole.id),不需要 .value
        tr = state_player.true_role.value if hasattr(state_player.true_role, "value") else state_player.true_role
        ar = state_player.apparent_role.value if hasattr(state_player.apparent_role, "value") else state_player.apparent_role
        # 注:不推送 is_poisoned/is_drunk 给玩家(隐藏信息,只有 ST 可见)
        socketio.emit(
            "role_assigned",
            {
                "true_role": tr,
                "apparent_role": ar if ar else tr,
            },
            to=rp.sid,
        )


@socketio.on("leave_room")
def on_leave_room(data: dict[str, Any]):
    """玩家主动离开(永久删除)。"""
    sid = request.sid
    code = ((data or {}).get("room_code") or "").upper()
    manager = get_room_manager()
    room = manager.get_room(code)
    if room is None:
        return
    rp = room.get_player_by_sid(sid)
    if rp is None:
        return
    # 真删除(用于主动 leave)
    if sid in room.sid_to_player:
        del room.sid_to_player[sid]
    if rp.id in room.runtime_players:
        del room.runtime_players[rp.id]
    # 同步从 GameState 移除
    room.state.players = [p for p in room.state.players if p.id != rp.id]
    leave_room(room.code)
    log.info("玩家 %s 主动离开房间 %s", rp.name, code)
    _broadcast_player_list(code)


# ---- 辅助 ----

def _broadcast_player_list(room_code: str) -> None:
    """向房间内所有人广播玩家列表(公开视图)。"""
    manager = get_room_manager()
    room = manager.get_room(room_code)
    if room is None:
        return
    payload = {
        "room_code": room.code,
        "phase": room.phase.value,
        "day": room.state.day,
        "night": room.state.night,
        "players": room.list_players_public(),
    }
    socketio.emit("player_list", payload, to=room.code)

    # 说书人控制台另外需要看真实身份
    st_rp = None
    for rp in room.runtime_players.values():
        if rp.is_storyteller:
            st_rp = rp
            break
    if st_rp and st_rp.sid:
        st_payload = {
            "room_code": room.code,
            "phase": room.phase.value,
            "day": room.state.day,
            "night": room.state.night,
            "players": room.list_players_for_storyteller(),
        }
        socketio.emit("st_player_list", st_payload, to=st_rp.sid)


# ---- 游戏流程事件(阶段 1) ----

@socketio.on("start_game")
def on_start_game(data: dict[str, Any]):
    """ST 点击「开始游戏」:分配角色,跳到 DAY。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    if not _require_storyteller(room):
        emit("error", {"code": "NOT_STORYTELLER", "message": "只有说书人可以开始游戏"})
        return
    if room.state.phase != Phase.LOBBY:
        emit("error", {"code": "WRONG_PHASE", "message": f"当前阶段 {room.state.phase.value} 不能开始游戏"})
        return
    real_players = [p for p in room.state.players if not p.is_storyteller]
    if len(real_players) < 5:
        emit("error", {"code": "NOT_ENOUGH_PLAYERS", "message": f"至少需要 5 名玩家,当前 {len(real_players)}"})
        return
    if room.state.script is None:
        emit("error", {"code": "NO_SCRIPT", "message": "请先在「板子」处录入或导入一个板子"})
        return

    try:
        _set_state(room, start_game(room.state))
    except (ValueError, PhaseTransitionError) as e:
        emit("error", {"code": "START_GAME_FAILED", "message": str(e)})
        return

    # 私密发送身份卡
    _send_role_assigned(room)
    # 公开广播
    socketio.emit(
        "public_announcement",
        {"text": "游戏开始!身份已发放。", "kind": "game_start"},
        to=room.code,
    )
    _broadcast_state(room)
    log.info("ST %s started game in room %s", request.sid, room.code)


@socketio.on("nominate")
def on_nominate(data: dict[str, Any]):
    """玩家发起提名(每阶段最多 1 次,被提名人不能重复)。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    nominee_id = (data or {}).get("target_id")
    if not nominee_id:
        emit("error", {"code": "INVALID_INPUT", "message": "缺少 target_id"})
        return

    me = room.get_player_by_sid(request.sid)
    if me is None or me.is_storyteller:
        emit("error", {"code": "CANNOT_NOMINATE", "message": "说书人不能被提名(也无权提名)"})
        return

    try:
        _set_state(room, start_nomination(room.state, me.id, nominee_id))
    except ValueError as e:
        emit("error", {"code": "NOMINATE_FAILED", "message": str(e)})
        return

    _broadcast_state(room)


@socketio.on("pass_nomination")
def on_pass_nomination(data: dict[str, Any]):
    """玩家主动 pass(本阶段跳过提名)。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    me = room.get_player_by_sid(request.sid)
    if me is None or me.is_storyteller:
        emit("error", {"code": "CANNOT_PASS", "message": "说书人不能 pass"})
        return
    try:
        _set_state(room, pass_nomination(room.state, me.id))
    except ValueError as e:
        emit("error", {"code": "PASS_FAILED", "message": str(e)})
        return
    _broadcast_state(room)


@socketio.on("vote")
def on_vote(data: dict[str, Any]):
    """对指定提名投票(覆盖式,需要 nomination_id)。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    value = (data or {}).get("value")
    nomination_id = (data or {}).get("nomination_id")
    if value is None or not nomination_id:
        emit("error", {"code": "INVALID_INPUT", "message": "缺少 value 或 nomination_id"})
        return

    me = room.get_player_by_sid(request.sid)
    if me is None or me.is_storyteller:
        emit("error", {"code": "CANNOT_VOTE", "message": "只有玩家可以投票"})
        return

    try:
        _set_state(room, cast_vote(room.state, me.id, nomination_id, bool(value)))
    except ValueError as e:
        emit("error", {"code": "VOTE_FAILED", "message": str(e)})
        return
    _broadcast_state(room)


@socketio.on("end_nomination_phase")
def on_end_nomination_phase(data: dict[str, Any]):
    """ST 手动结束提名阶段,统一计票。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    if not _require_storyteller(room):
        emit("error", {"code": "NOT_STORYTELLER", "message": "只有说书人可以结束提名阶段"})
        return

    # 先快照:结算后需要找出 best.nominee_id
    try:
        new_state = end_nomination_phase(room.state)
    except ValueError as e:
        emit("error", {"code": "END_PHASE_FAILED", "message": str(e)})
        return

    # 找被处决者
    executed_id = None
    executed_true_role = None
    for nom in new_state.current_nominations:
        if nom.passed:
            # 取 yes 最多的那个(同之前 end_nomination_phase 的平局规则:先提名的赢)
            pass
    # 重新跑一遍逻辑找 best(与 state_machine 中保持一致)
    alive_players = [p for p in new_state.players if p.status == PlayerStatus.ALIVE and not p.is_storyteller]
    threshold = len(alive_players) / 2
    best = None
    for nom in new_state.current_nominations:
        if nom.passed and (best is None or nom.yes_count > best.yes_count):
            best = nom
    if best is not None:
        executed_id = best.nominee_id
        # 找到的真实角色(从 new_state 读)
        ex_p = next((p for p in new_state.players if p.id == executed_id), None)
        if ex_p is not None:
            executed_true_role = ex_p.true_role.value if hasattr(ex_p.true_role, "value") else ex_p.true_role

    _set_state(room, new_state)

    if executed_id:
        ex_player = room.state.find_player(executed_id)
        if ex_player is not None:
            socketio.emit(
                "execution",
                {
                    "player_id": ex_player.id,
                    "name": ex_player.name,
                    "true_role": executed_true_role,
                    "reason": best.reason if best else "",
                },
                to=room.code,
            )

    _broadcast_state(room)

@socketio.on("end_day")
def on_end_day(data: dict[str, Any]):
    """ST 结束白天:DAY_DISCUSSION/DAY → NIGHT。
    - DAY_DISCUSSION:讨论阶段直接跳过提名入夜(无需先结束提名阶段)
    - DAY:必须先 end_nomination_phase 结算所有开放提名
    """
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    if not _require_storyteller(room):
        emit("error", {"code": "NOT_STORYTELLER", "message": "只有说书人可以结束白天"})
        return
    if room.state.phase not in (Phase.DAY_DISCUSSION, Phase.DAY):
        emit("error", {"code": "WRONG_PHASE", "message": f"当前阶段 {room.state.phase.value} 不能 end_day"})
        return
    if room.state.phase == Phase.DAY and any((not n.resolved) for n in room.state.current_nominations):
        emit("error", {"code": "NOMINATION_OPEN", "message": "请先结束提名阶段"})
        return
    try:
        _set_state(room, end_day(room.state))
    except PhaseTransitionError as e:
        emit("error", {"code": "END_DAY_FAILED", "message": str(e)})
        return

    socketio.emit(
        "public_announcement",
        {"text": "夜幕降临,所有人请闭眼。", "kind": "night_start"},
        to=room.code,
    )
    _broadcast_state(room)

@socketio.on("st_begin_nomination")
def on_st_begin_nomination(data: dict[str, Any]):
    """ST 手动从白天讨论阶段切换到提名阶段:DAY_DISCUSSION → DAY。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    if not _require_storyteller(room):
        emit("error", {"code": "NOT_STORYTELLER", "message": "只有说书人可以开始提名"})
        return
    if room.state.phase != Phase.DAY_DISCUSSION:
        emit("error", {"code": "WRONG_PHASE", "message": f"当前阶段 {room.state.phase.value} 不是白天讨论阶段,无需开启提名"})
        return
    try:
        _set_state(room, begin_nomination(room.state))
    except PhaseTransitionError as e:
        emit("error", {"code": "BEGIN_NOMINATION_FAILED", "message": str(e)})
        return
    _broadcast_state(room)


@socketio.on("begin_day")
def on_begin_day(data: dict[str, Any]):
    """ST 结束夜晚:NIGHT/FIRST_NIGHT → DAY。白天开始时公开夜间的死亡/复活。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    if not _require_storyteller(room):
        emit("error", {"code": "NOT_STORYTELLER", "message": "只有说书人可以开始白天"})
        return
    if room.state.phase not in (Phase.NIGHT, Phase.FIRST_NIGHT):
        emit("error", {"code": "WRONG_PHASE", "message": f"当前阶段 {room.state.phase.value} 不能 begin_day"})
        return

    # 在状态变更前先取出待公布的死亡/复活(从旧 state 读取)
    pending = list(room.state.pending_deaths)
    try:
        _set_state(room, begin_day(room.state))
    except PhaseTransitionError as e:
        emit("error", {"code": "BEGIN_DAY_FAILED", "message": str(e)})
        return

    # 状态变更后清空队列(此时已应用)
    room.state.pending_deaths = []

    # 一次性公开夜间的死亡/复活(按发生顺序)
    for p in pending:
        if p.kind == "kill":
            socketio.emit(
                "death",
                {"player_id": p.player_id, "name": p.name, "cause": p.cause or "说书人裁决"},
                to=room.code,
            )
        else:  # revive
            socketio.emit(
                "public_announcement",
                {"text": f"{p.name} 被说书人复活了。", "kind": "st_revive"},
                to=room.code,
            )

    socketio.emit(
        "public_announcement",
        {"text": f"第 {room.state.day} 天开始了。", "kind": "day_start"},
        to=room.code,
    )
    _broadcast_state(room)

@socketio.on("set_timer")
def on_set_timer(data: dict[str, Any]):
    """ST 设置聊天时长(秒)。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        return
    if not _require_storyteller(room):
        return
    seconds = int((data or {}).get("seconds") or 300)
    room.state = room.state.model_copy(deep=True)
    room.state.chat_duration_sec = max(30, min(seconds, 1800))  # 30s - 30min
    _broadcast_state(room)


@socketio.on("end_game")
def on_end_game(data: dict[str, Any]):
    """ST 强制结束游戏。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        return
    if not _require_storyteller(room):
        return
    room.state = room.state.model_copy(deep=True)
    reason = (data or {}).get("reason") or "说书人手动结束"
    room.state.winner = "manual"
    room.state.win_reason = reason
    room.state.phase = Phase.ENDED
    socketio.emit(
        "game_over",
        {"winner": "manual", "reason": reason},
        to=room.code,
    )
    _broadcast_state(room)


@socketio.on("close_room")
def on_close_room(data: dict[str, Any]):
    """ST 关闭房间:广播 room_closed,所有人离开,然后销毁房间对象。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    if not _require_storyteller(room):
        emit("error", {"code": "NOT_STORYTELLER", "message": "只有说书人可以关闭房间"})
        return

    reason = (data or {}).get("reason") or "说书人关闭了房间"
    code = room.code
    # 顺序很重要:必须先广播,后 leave_room,否则 leave 之后客户端不在 group 中就收不到广播
    socketio.emit(
        "room_closed",
        {"room_code": code, "reason": reason},
        to=code,
    )
    # 让所有 SocketIO 客户端从房间组中离开
    try:
        for rp in list(room.runtime_players.values()):
            if rp.sid:
                leave_room(code, sid=rp.sid)
    except Exception as e:  # pragma: no cover
        log.warning("close_room: leave_room 异常: %s", e)

    log.info("ST 关闭房间 %s (原因: %s)", code, reason)

    # 销毁房间对象
    get_room_manager().destroy_room(code)
    # 给 ST 自身一个回执(便于 lobby 检测后跳回)
    emit("room_closed_ack", {"room_code": code, "reason": reason})


@socketio.on("reset_game")
def on_reset_game(data: dict[str, Any]):
    """ST 在游戏结束后重开:保留玩家,清空状态,重新分配角色。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    if not _require_storyteller(room):
        emit("error", {"code": "NOT_STORYTELLER", "message": "只有说书人可以重开"})
        return
    if room.state.phase != Phase.ENDED:
        emit("error", {"code": "WRONG_PHASE", "message": f"当前阶段 {room.state.phase.value} 不能重开"})
        return

    try:
        new_state = reset_game_for_rematch(room.state)
    except ValueError as e:
        emit("error", {"code": "RESET_GAME_FAILED", "message": str(e)})
        return

    _set_state(room, new_state)
    # 重新分发身份卡
    _send_role_assigned(room)
    # 公开广播
    socketio.emit(
        "public_announcement",
        {"text": "游戏已重开,身份已重新发放。", "kind": "game_start"},
        to=room.code,
    )
    # 通知所有客户端状态已被重置
    socketio.emit(
        "game_reset",
        {"room_code": room.code, "day": room.state.day, "night": room.state.night},
        to=room.code,
    )
    _broadcast_state(room)
    log.info("ST 在房间 %s 中重开游戏", room.code)


# ---- 说书人超级权限事件 ----

@socketio.on("st_kill")
def on_st_kill(data: dict[str, Any]):
    """ST 强制杀死某玩家。白天立即公开;夜间延迟到 begin_day 才公开。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    if not _require_storyteller(room):
        emit("error", {"code": "NOT_STORYTELLER", "message": "只有说书人可以执行此操作"})
        return
    player_id = (data or {}).get("player_id")
    if not player_id:
        emit("error", {"code": "INVALID_INPUT", "message": "缺少 player_id"})
        return
    try:
        _set_state(room, st_kill_player(room.state, player_id))
    except ValueError as e:
        emit("error", {"code": "ST_KILL_FAILED", "message": str(e)})
        return
    dead_player = room.state.find_player(player_id)
    if dead_player and room.state.phase in (Phase.NIGHT, Phase.FIRST_NIGHT):
        room.state.pending_deaths.append(
            PendingDeath(player_id=player_id, name=dead_player.name, kind="kill", cause="说书人裁决")
        )
    elif dead_player:
        socketio.emit(
            "death",
            {"player_id": player_id, "name": dead_player.name, "cause": "说书人裁决"},
            to=room.code,
        )
    _broadcast_state(room)

@socketio.on("st_revive")
def on_st_revive(data: dict[str, Any]):
    """ST 强制复活某玩家。白天立即公开;夜间延迟到 begin_day 才公开,但私下通知被复活者。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    if not _require_storyteller(room):
        emit("error", {"code": "NOT_STORYTELLER", "message": "只有说书人可以执行此操作"})
        return
    player_id = (data or {}).get("player_id")
    if not player_id:
        emit("error", {"code": "INVALID_INPUT", "message": "缺少 player_id"})
        return
    try:
        _set_state(room, st_revive_player(room.state, player_id))
    except ValueError as e:
        emit("error", {"code": "ST_REVIVE_FAILED", "message": str(e)})
        return
    revived = room.state.find_player(player_id)
    revived_rp = room.get_runtime(player_id)
    if revived and room.state.phase in (Phase.NIGHT, Phase.FIRST_NIGHT):
        room.state.pending_deaths.append(
            PendingDeath(player_id=player_id, name=revived.name, kind="revive")
        )
        if revived_rp and revived_rp.sid:
            socketio.emit(
                "revive",
                {"player_id": player_id, "name": revived.name},
                to=revived_rp.sid,
            )
    elif revived:
        socketio.emit(
            "public_announcement",
            {"text": f"{revived.name} 被说书人复活了。", "kind": "st_revive"},
            to=room.code,
        )
    _broadcast_state(room)


@socketio.on("st_set_drunk")
def on_st_set_drunk(data: dict[str, Any]):
    """ST 设置玩家醉酒状态(仅 ST 可见)。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    if not _require_storyteller(room):
        emit("error", {"code": "NOT_STORYTELLER", "message": "只有说书人可以执行此操作"})
        return
    player_id = (data or {}).get("player_id")
    value = (data or {}).get("value", True)
    if not player_id:
        emit("error", {"code": "INVALID_INPUT", "message": "缺少 player_id"})
        return
    try:
        _set_state(room, st_set_drunk(room.state, player_id, bool(value)))
    except ValueError as e:
        emit("error", {"code": "ST_SET_DRUNK_FAILED", "message": str(e)})
        return
    _broadcast_state(room)


@socketio.on("st_set_poisoned")
def on_st_set_poisoned(data: dict[str, Any]):
    """ST 设置玩家中毒状态(仅 ST 可见)。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    if not _require_storyteller(room):
        emit("error", {"code": "NOT_STORYTELLER", "message": "只有说书人可以执行此操作"})
        return
    player_id = (data or {}).get("player_id")
    value = (data or {}).get("value", True)
    if not player_id:
        emit("error", {"code": "INVALID_INPUT", "message": "缺少 player_id"})
        return
    try:
        _set_state(room, st_set_poisoned(room.state, player_id, bool(value)))
    except ValueError as e:
        emit("error", {"code": "ST_SET_POISONED_FAILED", "message": str(e)})
        return
    _broadcast_state(room)


@socketio.on("st_clear_status")
def on_st_clear_status(data: dict[str, Any]):
    """ST 同时清除玩家的醉酒和中毒状态(仅 ST 可见)。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    if not _require_storyteller(room):
        emit("error", {"code": "NOT_STORYTELLER", "message": "只有说书人可以执行此操作"})
        return
    player_id = (data or {}).get("player_id")
    if not player_id:
        emit("error", {"code": "INVALID_INPUT", "message": "缺少 player_id"})
        return
    try:
        _set_state(room, st_set_drunk(room.state, player_id, False))
        _set_state(room, st_set_poisoned(room.state, player_id, False))
    except ValueError as e:
        emit("error", {"code": "ST_CLEAR_STATUS_FAILED", "message": str(e)})
        return
    _broadcast_state(room)


@socketio.on("st_change_role")
def on_st_change_role(data: dict[str, Any]):
    """ST 变更玩家身份(告知当事玩家,广播 ST 列表)。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    if not _require_storyteller(room):
        emit("error", {"code": "NOT_STORYTELLER", "message": "只有说书人可以执行此操作"})
        return
    player_id = (data or {}).get("player_id")
    role_str = (data or {}).get("new_role")
    if not player_id or not role_str:
        emit("error", {"code": "INVALID_INPUT", "message": "缺少 player_id 或 new_role"})
        return
    # 校验 role_str 是当前脚本里的角色 ID(自定义脚本的 ID 可能不在 RoleId 枚举里)
    script = room.state.script
    if script and script.roles:
        valid_ids = {r.id for r in script.roles}
        if role_str not in valid_ids:
            emit("error", {"code": "INVALID_ROLE", "message": f"无效角色: {role_str}(不在当前脚本中)"})
            return
        # 传奇阵营不能分发给玩家(只能由 ST 在控制台手动切换在场/离场)
        target_role = next((r for r in script.roles if r.id == role_str), None)
        if target_role and target_role.team == "fabled":
            emit(
                "error",
                {
                    "code": "INVALID_ROLE",
                    "message": f"传奇角色 {role_str} 不能分配给玩家",
                },
            )
            return
    try:
        _set_state(room, st_change_role(room.state, player_id, role_str))
    except ValueError as e:
        emit("error", {"code": "ST_CHANGE_ROLE_FAILED", "message": str(e)})
        return
    # 顺序很重要:先 broadcast 新 state(让所有客户端 lastState 更新),
    # 再发 role_assigned,避免前端用旧 lastState 查 roleDisplayName 拿到 ID
    _broadcast_state(room)

    target_rp = room.get_runtime(player_id)
    if target_rp and target_rp.sid:
        state_player = room.state.find_player(player_id)
        if state_player:
            tr = state_player.true_role.value if hasattr(state_player.true_role, "value") else state_player.true_role
            ar = state_player.apparent_role.value if hasattr(state_player.apparent_role, "value") else state_player.apparent_role
            # 注:不推送 is_poisoned/is_drunk 给玩家(隐藏信息,只有 ST 可见)
            socketio.emit(
                "role_assigned",
                {
                    "true_role": tr,
                    "apparent_role": ar,
                },
                to=target_rp.sid,
            )


@socketio.on("st_toggle_fabled")
def on_st_toggle_fabled(data: dict[str, Any]):
    """ST 切换某传奇角色的在场/离场。

    请求体:{role_id, on(bool)}
    校验:
      - 当前房间已 set_script
      - role_id 在脚本中
      - 该角色 team == 'fabled'
    副作用:写公开日志(玩家可见),状态广播。
    """
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    if not _require_storyteller(room):
        emit("error", {"code": "NOT_STORYTELLER", "message": "只有说书人可以执行此操作"})
        return
    role_id = (data or {}).get("role_id")
    on = (data or {}).get("on")
    if not role_id or not isinstance(on, bool):
        emit("error", {"code": "INVALID_INPUT", "message": "缺少 role_id 或 on"})
        return
    try:
        _set_state(room, st_toggle_fabled(room.state, role_id, on))
    except ValueError as e:
        emit("error", {"code": "ST_TOGGLE_FABLED_FAILED", "message": str(e)})
        return
    _broadcast_state(room)


@socketio.on("st_set_notes")
def on_st_set_notes(data: dict[str, Any]):
    """ST 为玩家设置多条自定义批注(仅 ST 可见)。

    请求体:{player_id, notes: [{id?, text}, ...]}
    整个 notes 列表覆盖替换;客户端负责增/删/改后同步完整列表。
    """
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    if not _require_storyteller(room):
        emit("error", {"code": "NOT_STORYTELLER", "message": "只有说书人可以执行此操作"})
        return
    player_id = (data or {}).get("player_id")
    notes_data = (data or {}).get("notes", [])
    if not player_id:
        emit("error", {"code": "INVALID_INPUT", "message": "缺少 player_id"})
        return
    if not isinstance(notes_data, list):
        emit("error", {"code": "INVALID_INPUT", "message": "notes 必须是列表"})
        return
    try:
        _set_state(room, st_set_notes(room.state, player_id, notes_data))
    except ValueError as e:
        emit("error", {"code": "ST_SET_NOTES_FAILED", "message": str(e)})
        return
    _broadcast_state(room)


# ---- 向后兼容旧版单条 st_set_note ----

@socketio.on("st_set_note")
def on_st_set_note(data: dict[str, Any]):
    """(旧 API 兼容)单条批注。内部走 st_set_notes。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        return
    if not _require_storyteller(room):
        return
    player_id = (data or {}).get("player_id")
    note_text = (data or {}).get("note", "")
    if not player_id:
        return
    # 取旧值,合成新列表(避免覆盖可能存在的多条)
    existing = room.state.find_player(player_id)
    current = list(existing.st_notes) if existing else []
    if note_text:
        # 没有 id → 用 uuid;若已存在一条同 text,保留
        nid_seed = f"legacy_{player_id[:4]}"
        current.append({"id": nid_seed, "text": note_text})
    else:
        # 空文本 → 清空
        current = []
    try:
        _set_state(room, st_set_notes(room.state, player_id, current))
    except ValueError:
        return
    _broadcast_state(room)


@socketio.on("st_add_log")
def on_st_add_log(data: dict[str, Any]):
    """ST 手动追加活动日志,支持可见范围。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    if not _require_storyteller(room):
        emit("error", {"code": "NOT_STORYTELLER", "message": "只有说书人可以执行此操作"})
        return
    text = ((data or {}).get("text") or "").strip()
    if not text:
        emit("error", {"code": "INVALID_INPUT", "message": "日志内容不能为空"})
        return
    visibility = (data or {}).get("visibility") or "st_only"
    target_id = (data or {}).get("target_id")
    try:
        _set_state(room, st_add_log(room.state, text, visibility=visibility, target_id=target_id))
    except ValueError as e:
        emit("error", {"code": "ST_ADD_LOG_FAILED", "message": str(e)})
        return
    _broadcast_state(room)


@socketio.on("st_kick")
def on_st_kick(data: dict[str, Any]):
    """ST 踢人:从房间移除玩家(完全销毁),被踢者收到 kicked 事件后跳转大厅。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    if not _require_storyteller(room):
        emit("error", {"code": "NOT_STORYTELLER", "message": "只有说书人可以踢人"})
        return
    player_id = (data or {}).get("player_id")
    if not player_id:
        emit("error", {"code": "INVALID_INPUT", "message": "缺少 player_id"})
        return

    target_rp = room.get_runtime(player_id)
    if target_rp is None:
        emit("error", {"code": "PLAYER_NOT_FOUND", "message": "玩家不存在或已离线"})
        return
    if target_rp.is_storyteller:
        emit("error", {"code": "CANNOT_KICK_ST", "message": "不能说书人踢说书人"})
        return

    reason = (data or {}).get("reason") or "被说书人踢出房间"
    target_name = target_rp.name
    target_sid = target_rp.sid

    # 1) 私下通知被踢玩家
    if target_sid:
        try:
            socketio.emit("kicked", {"room_code": room.code, "reason": reason}, to=target_sid)
        except Exception:
            pass
        # 2) 让其离开房间组
        try:
            leave_room(room.code, sid=target_sid)
        except Exception:
            pass

    # 3) 从 runtime_players / state.players 中清除
    room.runtime_players.pop(player_id, None)
    if target_sid and target_sid in room.sid_to_player:
        del room.sid_to_player[target_sid]
    room.state.players = [p for p in room.state.players if p.id != player_id]

    log.info("ST 把玩家 %s 踢出房间 %s", target_name, room.code)

    # 4) 公开一条广播(让其他人看到)
    socketio.emit(
        "public_announcement",
        {"text": f"🚪 {target_name} 被说书人踢出房间。", "kind": "st_kick"},
        to=room.code,
    )
    _broadcast_state(room)


# ---- 玩家私人日志与批注事件 ----
@socketio.on("player_add_log")
def on_player_add_log(data: dict[str, Any]):
    """玩家追加一条私人日志(仅自己可见)。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    me = room.get_player_by_sid(request.sid)
    if me is None or me.is_storyteller:
        emit("error", {"code": "NOT_PLAYER", "message": "只有玩家可以记录日志"})
        return
    text = ((data or {}).get("text") or "").strip()
    if not text:
        emit("error", {"code": "INVALID_INPUT", "message": "日志内容不能为空"})
        return
    _set_state(room, player_add_log(room.state, me.id, text))
    _broadcast_state(room)


@socketio.on("player_send_to_st")
def on_player_send_to_st(data: dict[str, Any]):
    """玩家发送一条消息给说书人(发送者自己与 ST 可见)。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    me = room.get_player_by_sid(request.sid)
    if me is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "玩家不存在"})
        return
    if me.is_storyteller:
        emit("error", {"code": "NOT_PLAYER", "message": "说书人不需要发送给自己"})
        return
    text = ((data or {}).get("text") or "").strip()
    if not text:
        emit("error", {"code": "INVALID_INPUT", "message": "消息内容不能为空"})
        return
    try:
        _set_state(room, player_send_to_st(room.state, me.id, text))
    except ValueError as e:
        emit("error", {"code": "PLAYER_SEND_TO_ST_FAILED", "message": str(e)})
        return
    _broadcast_state(room)


@socketio.on("player_set_notes")
def on_player_set_notes(data: dict[str, Any]):
    """玩家对另一玩家设置多条私人批注(仅自己可见)。

    请求体:{target_id, notes: [{id?, text}, ...]}
    整个 notes 列表覆盖替换;客户端负责增/删/改后同步完整列表。
    """
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    me = room.get_player_by_sid(request.sid)
    if me is None or me.is_storyteller:
        emit("error", {"code": "NOT_PLAYER", "message": "只有玩家可以设置批注"})
        return
    target_id = (data or {}).get("target_id")
    notes_data = (data or {}).get("notes", [])
    if not target_id:
        emit("error", {"code": "INVALID_INPUT", "message": "缺少 target_id"})
        return
    if not isinstance(notes_data, list):
        emit("error", {"code": "INVALID_INPUT", "message": "notes 必须是列表"})
        return
    try:
        _set_state(room, player_set_notes(room.state, me.id, target_id, notes_data))
    except ValueError as e:
        emit("error", {"code": "PLAYER_SET_NOTES_FAILED", "message": str(e)})
        return
    # 只向本玩家推送 player_state,其他人无感知
    me_state = _player_state_payload(room, me.id)
    socketio.emit("player_state", me_state, to=me.sid)


# ---- 向后兼容旧版单条 player_set_note ----

@socketio.on("player_set_note")
def on_player_set_note(data: dict[str, Any]):
    """(旧 API 兼容)单条批注。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        return
    me = room.get_player_by_sid(request.sid)
    if me is None or me.is_storyteller:
        return
    target_id = (data or {}).get("target_id")
    note_text = (data or {}).get("note", "")
    if not target_id:
        return
    me_state_p = room.state.find_player(me.id)
    current = list(me_state_p.player_notes.get(target_id, [])) if me_state_p else []
    if note_text:
        current.append({"id": f"legacy_{me.id[:4]}_{target_id[:4]}", "text": note_text})
    else:
        current = []
    try:
        _set_state(room, player_set_notes(room.state, me.id, target_id, current))
    except ValueError:
        return
    me_state = _player_state_payload(room, me.id)
    socketio.emit("player_state", me_state, to=me.sid)


# ---- Lobby 阶段:座位交换 ----

@socketio.on("swap_request")
def on_swap_request(data: dict[str, Any]):
    """玩家发起交换申请:from_id(自己) → to_id(对方)。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    me = room.get_player_by_sid(request.sid)
    if me is None:
        emit("error", {"code": "PLAYER_NOT_FOUND", "message": "未找到玩家"})
        return
    if me.is_storyteller:
        emit("error", {"code": "INVALID_INPUT", "message": "说书人不能用此事件,请用 st_swap_players"})
        return
    to_id = (data or {}).get("to_id")
    if not to_id:
        emit("error", {"code": "INVALID_INPUT", "message": "缺少 to_id"})
        return
    try:
        _set_state(room, request_swap(room.state, me.id, to_id))
    except ValueError as e:
        emit("error", {"code": "SWAP_REQUEST_FAILED", "message": str(e)})
        return
    _broadcast_state(room)


@socketio.on("swap_accept")
def on_swap_accept(data: dict[str, Any]):
    """被申请人接受交换:仅 pending_swap.to_id 能调用。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    me = room.get_player_by_sid(request.sid)
    if me is None:
        emit("error", {"code": "PLAYER_NOT_FOUND", "message": "未找到玩家"})
        return
    try:
        _set_state(room, accept_swap(room.state, me.id))
    except ValueError as e:
        emit("error", {"code": "SWAP_ACCEPT_FAILED", "message": str(e)})
        return
    _broadcast_state(room)


@socketio.on("swap_decline")
def on_swap_decline(data: dict[str, Any]):
    """被申请人拒绝交换:仅 pending_swap.to_id 能调用。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    me = room.get_player_by_sid(request.sid)
    if me is None:
        emit("error", {"code": "PLAYER_NOT_FOUND", "message": "未找到玩家"})
        return
    try:
        _set_state(room, decline_swap(room.state, me.id))
    except ValueError as e:
        emit("error", {"code": "SWAP_DECLINE_FAILED", "message": str(e)})
        return
    _broadcast_state(room)


@socketio.on("swap_cancel")
def on_swap_cancel(data: dict[str, Any]):
    """申请人或说书人取消在途申请。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    me = room.get_player_by_sid(request.sid)
    if me is None:
        emit("error", {"code": "PLAYER_NOT_FOUND", "message": "未找到玩家"})
        return
    try:
        _set_state(room, cancel_swap(room.state, me.id, is_st=me.is_storyteller))
    except ValueError as e:
        emit("error", {"code": "SWAP_CANCEL_FAILED", "message": str(e)})
        return
    _broadcast_state(room)


@socketio.on("st_swap_players")
def on_st_swap_players(data: dict[str, Any]):
    """说书人强制交换两个玩家的座位(点选交换)。"""
    room = _find_room_by_sid(request.sid)
    if room is None:
        emit("error", {"code": "NOT_IN_ROOM", "message": "未在任何房间"})
        return
    if not _require_storyteller(room):
        emit("error", {"code": "NOT_STORYTELLER", "message": "只有说书人可以执行此操作"})
        return
    a_id = (data or {}).get("a_id")
    b_id = (data or {}).get("b_id")
    if not a_id or not b_id:
        emit("error", {"code": "INVALID_INPUT", "message": "缺少 a_id 或 b_id"})
        return
    try:
        _set_state(room, st_swap_seats(room.state, a_id, b_id))
    except ValueError as e:
        emit("error", {"code": "ST_SWAP_FAILED", "message": str(e)})
        return
    _broadcast_state(room)
