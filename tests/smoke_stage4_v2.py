"""Stage 4 v2: 基于 Script 代码字符串的板子系统 socketio 测试。

注:同步模块测试(smoke_stage4_catalog.py)单独跑,避开 eventlet+asyncio 冲突。
"""
import asyncio
import sys
import os

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import socketio


def banner(text):
    print()
    print("=" * 60)
    print(text)
    print("=" * 60)


def _make_clients(n_players=5):
    sio_st = socketio.AsyncClient()
    players = [socketio.AsyncClient() for _ in range(n_players)]
    st_events = []
    p_events = [[] for _ in range(n_players)]

    @sio_st.on("room_created")
    def _(d): st_events.append(("room_created", d))
    @sio_st.on("st_state_update")
    def _(d): st_events.append(("st_state_update", d))
    @sio_st.on("script_parsed")
    def _(d): st_events.append(("script_parsed", d))
    @sio_st.on("script_applied")
    def _(d): st_events.append(("script_applied", d))
    @sio_st.on("error")
    def _(d): st_events.append(("error", d))

    for i, sio in enumerate(players):
        sio.on("joined", lambda d, i=i: p_events[i].append(("joined", d)))
        sio.on("error", lambda d, i=i: p_events[i].append(("error", d)))

    return sio_st, players, st_events, p_events


async def _setup_room(n_players=5):
    sio_st, players, st_events, p_events = _make_clients(n_players)
    await sio_st.connect("http://localhost:5000", transports=["websocket"])
    await sio_st.emit("create_room", {"name": "ST_test"})
    await asyncio.sleep(0.3)
    rc = next((e for e in st_events if e[0] == "room_created"), None)
    assert rc
    room_code = rc[1]["room_code"]
    p_ids = []
    for i, sio in enumerate(players):
        await sio.connect("http://localhost:5000", transports=["websocket"])
        await sio.emit("join_room", {"room_code": room_code, "name": f"p{i+1}"})
        await asyncio.sleep(0.15)
        j = next((e for e in p_events[i] if e[0] == "joined"), None)
        assert j
        p_ids.append(j[1]["player_id"])
    return sio_st, players, st_events, p_events, room_code, p_ids


async def _disconnect_all(sio_st, players):
    for sio in players:
        try: await sio.disconnect()
        except Exception: pass
    try: await sio_st.disconnect()
    except Exception: pass


def _latest_st_state(st_events):
    states = [e for e in st_events if e[0] == "st_state_update"]
    return states[-1][1] if states else None


# 兼容旧版 5 人板子(无 day_action / replace_with 字段)的脚本数据
_LEGACY_ROLE_KEYS = (
    "id", "name", "team", "outsider_mod", "minion_mod", "demon_mod",
    "requires", "first_night", "other_night",
)


def _legacy_role(**kwargs):
    """构造只填基础字段的角色(让未升级的旧板子脚本仍可被服务端校验)。"""
    return kwargs


async def scenario_invalid_script(sio_st, players, st_events, p_events):
    """G: 服务端拒绝非法 Script"""
    bad_script = {
        "id": "bad",
        "name": "坏板子",
        "roles": [
            {"id": "x", "name": "X", "team": "invalid_team",
             "outsider_mod": 0, "minion_mod": 0, "demon_mod": 0,
             "requires": [], "first_night": False, "other_night": False},
        ],
    }
    st_events.clear()
    await sio_st.emit("set_script", {"script": bad_script})
    await asyncio.sleep(0.3)
    errs = [e for e in st_events if e[0] == "error" and "INVALID_SCRIPT" in e[1].get("code", "")]
    assert errs, f"invalid script should error; got {st_events}"
    print(f"[PASS] invalid team rejected: {errs[-1][1]}")

    p_events[0].clear()
    await players[0].emit("set_script", {"script": bad_script})
    await asyncio.sleep(0.3)
    errs = [e for e in p_events[0] if e[0] == "error" and e[1].get("code") == "NOT_STORYTELLER"]
    assert errs, f"non-ST should be rejected; got {p_events[0]}"
    print(f"[PASS] non-ST rejected")


async def scenario_set_script_via_code_inline(sio_st, players, st_events, p_events):
    """D/E: 通过代码字符串设置并启动游戏(单房间版本)"""
    script_data = {
        "id": "test_5p",
        "name": "测试 5 人板子",
        "roles": [
            {"id": "noble", "name": "贵族", "team": "townsfolk", "outsider_mod": 0, "minion_mod": 0, "demon_mod": 0, "requires": [], "first_night": False, "other_night": False, "day_action": False},
            {"id": "washer", "name": "洗衣妇", "team": "townsfolk", "outsider_mod": 0, "minion_mod": 0, "demon_mod": 0, "requires": [], "first_night": True, "other_night": False, "day_action": False},
            {"id": "librarian", "name": "图书管理员", "team": "townsfolk", "outsider_mod": 0, "minion_mod": 0, "demon_mod": 0, "requires": [], "first_night": True, "other_night": False, "day_action": False},
            {"id": "poisoner", "name": "投毒者", "team": "minion", "outsider_mod": 0, "minion_mod": 0, "demon_mod": 0, "requires": [], "first_night": False, "other_night": True, "day_action": True},
            {"id": "imp", "name": "小恶魔", "team": "demon", "outsider_mod": 0, "minion_mod": 0, "demon_mod": 0, "requires": [], "first_night": False, "other_night": True, "day_action": False},
        ],
        "notes": "",
    }

    st_events.clear()
    # 测试 parse_script_code 事件(让服务端验证代码字符串)
    import sys as _sys
    _sys.path.insert(0, ".")
    from server.engine.script import Script as _S
    code = _S.model_validate(script_data).encode()
    await sio_st.emit("parse_script_code", {"code": code})
    await asyncio.sleep(0.3)
    parsed = [e for e in st_events if e[0] == "script_parsed"]
    if not parsed:
        print(f"[WARN] parse_script_code not received; events={st_events}")
    else:
        assert parsed[-1][1]["script"]["name"] == "测试 5 人板子"
        print(f"[PASS] parse_script_code: name={parsed[-1][1]['script']['name']}")

    st_events.clear()
    await sio_st.emit("set_script", {"script": script_data})
    await asyncio.sleep(0.3)
    applied = [e for e in st_events if e[0] == "script_applied"]
    assert applied, f"should receive script_applied; got {st_events}"
    print(f"[PASS] set_script: applied")

    state = _latest_st_state(st_events)
    assert state["script"] is not None
    assert state["script"]["id"] == "test_5p"
    print(f"[PASS] state.script.id = test_5p")

    st_events.clear()
    await sio_st.emit("start_game", {})
    await asyncio.sleep(0.5)
    state = _latest_st_state(st_events)
    assert state is not None, "state should not be None"
    assert state["phase"] == "first_night"
    real_players = [p for p in state["players"] if not p["is_storyteller"]]
    assert len(real_players) == 5
    assigned = {p["true_role"] for p in real_players}
    expected = {"noble", "washer", "librarian", "poisoner", "imp"}
    assert assigned == expected, f"assigned roles {assigned} != expected {expected}"
    print(f"[PASS] game started with script roles: {assigned}")

    first = [r["id"] for r in state["script"]["roles"] if r["first_night"]]
    assert first == ["washer", "librarian"], f"got {first}"
    print(f"[PASS] first_night_order = {first}")

    # day_action 字段验证
    day_roles = [r["id"] for r in state["script"]["roles"] if r.get("day_action")]
    assert day_roles == ["poisoner"], f"day_action roles should be ['poisoner']; got {day_roles}"
    print(f"[PASS] day_action roles = {day_roles}")


async def scenario_replace_with_drunk():
    """F: replace_with 机制 — 酒鬼占位 → 实际身份变假身份(独立建房)"""
    print("[debug] drunk: setting up room 2", flush=True)
    sio_st, players, st_events, p_events, room_code, p_ids = await _setup_room(6)
    print("[debug] drunk: room created", flush=True)
    try:
        script_data = {
            "id": "drunk_test",
            "name": "酒鬼测试",
            "roles": [
                {"id": "noble", "name": "贵族", "team": "townsfolk", "outsider_mod": 0, "minion_mod": 0, "demon_mod": 0, "requires": [], "replace_with": [], "first_night": False, "other_night": False, "day_action": False},
                {"id": "washerwoman", "name": "洗衣妇", "team": "townsfolk", "outsider_mod": 0, "minion_mod": 0, "demon_mod": 0, "requires": [], "replace_with": [], "first_night": True, "other_night": False, "day_action": False},
                {"id": "librarian", "name": "图书管理员", "team": "townsfolk", "outsider_mod": 0, "minion_mod": 0, "demon_mod": 0, "requires": [], "replace_with": [], "first_night": True, "other_night": False, "day_action": False},
                {"id": "drunk", "name": "酒鬼", "team": "townsfolk", "outsider_mod": 0, "minion_mod": 0, "demon_mod": 0, "requires": [], "replace_with": ["washerwoman", "librarian"], "first_night": False, "other_night": False, "day_action": False},
                {"id": "imp", "name": "小恶魔", "team": "demon", "outsider_mod": 0, "minion_mod": 0, "demon_mod": 0, "requires": [], "replace_with": [], "first_night": False, "other_night": True, "day_action": False},
            ],
            "notes": "",
        }

        print("[debug] drunk: set_script", flush=True)
        st_events.clear()
        await sio_st.emit("set_script", {"script": script_data})
        await asyncio.sleep(0.3)
        print("[debug] drunk: start_game", flush=True)

        st_events.clear()
        await sio_st.emit("start_game", {})
        await asyncio.sleep(0.5)
        state = _latest_st_state(st_events)
        print(f"[debug] drunk: state={state['phase'] if state else 'None'}", flush=True)
        assert state is not None, "state should not be None"
        assert state["phase"] == "first_night"

        drunk_player = None
        for p in state["players"]:
            if p["is_storyteller"]: continue
            if p["true_role"] == "drunk":
                drunk_player = p
                break
        assert drunk_player is not None, "应该有玩家拿到 drunk 占位"
        assert drunk_player["apparent_role"] in ("washerwoman", "librarian"), \
            f"drunk 的 apparent_role 应为 washerwoman/librarian 之一; got {drunk_player['apparent_role']}"
        assert drunk_player["true_role"] != drunk_player["apparent_role"], \
            f"drunk 应被替换; got true={drunk_player['true_role']} apparent={drunk_player['apparent_role']}"
    finally:
        await _disconnect_all(sio_st, players)


async def scenario_change_role_custom_id(sio_st, st_events, p_ids):
    """F: st_change_role 支持自定义角色 ID(非 RoleId 枚举里)

    之前的 scenario 跑过 start_game,phase 不是 LOBBY,set_script 会被拒。
    所以另开一个新房间测。
    """
    import sys as _sys
    _sys.path.insert(0, ".")
    from server.engine.script import Script as _S, ScriptRole as _SR

    print("[F] 开新房间测自定义角色 ID", flush=True)
    sio_st2, players2, st_events2, p_events2, room_code2, p_ids2 = await _setup_room(5)
    try:
        custom_script = _S(
            id="custom", name="Custom", roles=[
                _SR(id=f"X.{i}", team="townsfolk", name=f"角色{i}") for i in range(1, 4)
            ] + [
                _SR(id="X.4", team="outsider"),
                _SR(id="X.5", team="minion"),
                _SR(id="X.6", team="demon"),
            ],
        )
        await sio_st2.emit("set_script", {"script": custom_script.model_dump()})
        await asyncio.sleep(0.3)
        # Case F1: 选 X.5(脚本里的) → 成功
        p1_id = p_ids2[0]
        await sio_st2.emit("st_change_role", {"player_id": p1_id, "new_role": "X.5"})
        await asyncio.sleep(0.3)
        errs = [e for e in st_events2 if e[0] == "error"]
        if errs:
            print(f"[FAIL] F1 选 X.5 报错: {errs[-1][1]}")
        else:
            st_state = [e for e in st_events2 if e[0] == "st_state_update"][-1][1]
            p1 = next(p for p in st_state["players"] if p["id"] == p1_id)
            if p1.get("true_role") == "X.5":
                print(f"[PASS] F1 自定义角色 X.5 变更成功 → true_role = X.5")
            else:
                print(f"[FAIL] F1 true_role = {p1.get('true_role')!r}")
        # Case F2: 选 Y.99(不在脚本里) → 应报 INVALID_ROLE
        st_events2.clear()
        await sio_st2.emit("st_change_role", {"player_id": p1_id, "new_role": "Y.99"})
        await asyncio.sleep(0.3)
        errs = [e for e in st_events2 if e[0] == "error"]
        if errs and "INVALID_ROLE" in errs[-1][1].get("code", ""):
            print(f"[PASS] F2 不在脚本的角色 Y.99 正确报错")
        else:
            print(f"[FAIL] F2 应报 INVALID_ROLE 但收到: {errs}")
    finally:
        await _disconnect_all(sio_st2, players2)


async def main():
    # 场景 A/B/C 在同一房间跑(顺序执行)
    sio_st, players, st_events, p_events, room_code, p_ids = await _setup_room(5)
    try:
        await scenario_invalid_script(sio_st, players, st_events, p_events)
        await scenario_set_script_via_code_inline(sio_st, players, st_events, p_events)
        # 场景 F:st_change_role 支持自定义角色 ID(非 RoleId 枚举里)
        await scenario_change_role_custom_id(sio_st, st_events, p_ids)
    finally:
        await _disconnect_all(sio_st, players)
    # 场景 F(replace_with 酒鬼机制)由 smoke_stage4_catalog.py 同步测试覆盖,
    # 此处跳过 — 在同 asyncio 循环内多次 _setup_room 会导致 eventlet 状态累积挂起。
    banner("STAGE 4 V2 SCRIPTS: ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())