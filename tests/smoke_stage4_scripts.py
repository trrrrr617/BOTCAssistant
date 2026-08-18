"""Stage 4: 板子(Script)socketio 回归测试。

场景:
  E. assign_roles 集成 script:开局默认使用 default 板子
  F. 板子 socketio 事件:list / get / save / delete / select
  G. 默认板子不可删

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
    @sio_st.on("script_list")
    def _(d): st_events.append(("script_list", d))
    @sio_st.on("script_detail")
    def _(d): st_events.append(("script_detail", d))
    @sio_st.on("error")
    def _(d): st_events.append(("error", d))

    for i, sio in enumerate(players):
        sio.on("joined", lambda d, i=i: p_events[i].append(("joined", d)))
        sio.on("state_update", lambda d, i=i: p_events[i].append(("state_update", d)))
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


async def scenario_assign_with_script():
    """E: 实际游戏中 assign_roles 使用 default 板子"""
    sio_st, players, st_events, p_events, room_code, p_ids = await _setup_room(7)
    st_events.clear()
    await sio_st.emit("start_game", {})
    await asyncio.sleep(0.5)
    state = _latest_st_state(st_events)
    assert state["script_id"] == "default", f"script_id should be default; got {state['script_id']}"
    # 7 人应是 5T/0O/1M/1D(避开 server.engine 导入,本地实现 role_team)
    def role_team(rid):
        if not rid: return None
        DEMONS = {"hadjiya", "lleech"}
        MINIONS = {"poisoner", "lunatic", "cerenovus", "hag"}
        OUTSIDERS = {"drunk", "barber", "damsel", "golem"}
        TOWNSFOLK = {"noble","snake_charmer","balloonist","mountain_man","engineer","fisherman",
                     "professor","scholar","amnesiac","farmer","cannibal","poppy_grower","atheist"}
        if rid in TOWNSFOLK: return "townsfolk"
        if rid in OUTSIDERS: return "outsider"
        if rid in MINIONS: return "minion"
        if rid in DEMONS: return "demon"
        return "fabled"
    counts = {"townsfolk": 0, "outsider": 0, "minion": 0, "demon": 0, "fabled": 0}
    for p in state["players"]:
        if p["is_storyteller"]: continue
        t = role_team(p["true_role"]) if p["true_role"] else None
        if t in counts:
            counts[t] += 1
    assert counts["townsfolk"] == 5, f"T count wrong: {counts}"
    assert counts["outsider"] == 0
    assert counts["minion"] == 1
    assert counts["demon"] == 1
    print(f"[PASS] game with default script assigns {counts}")
    await _disconnect_all(sio_st, players)


async def scenario_script_management():
    """F/G: 板子管理 socketio 事件"""
    sio_st, players, st_events, p_events, room_code, p_ids = await _setup_room(3)

    # list
    st_events.clear()
    await sio_st.emit("list_scripts", {})
    await asyncio.sleep(0.3)
    sl = [e for e in st_events if e[0] == "script_list"]
    assert sl, "should receive script_list"
    script_ids = [s["id"] for s in sl[-1][1]["scripts"]]
    assert "default" in script_ids
    print(f"[PASS] script_list has {script_ids}")

    # get default
    st_events.clear()
    await sio_st.emit("get_script", {"script_id": "default"})
    await asyncio.sleep(0.3)
    sd = [e for e in st_events if e[0] == "script_detail"]
    assert sd, "should receive script_detail"
    assert sd[-1][1]["id"] == "default"
    assert len(sd[-1][1]["enabled_roles"]) == 25
    print(f"[PASS] get default: enabled={len(sd[-1][1]['enabled_roles'])} roles")

    # save new script
    new_script = {
        "id": "test_t7",
        "name": "测试板子(7人)",
        "enabled_roles": ["noble", "snake_charmer", "balloonist", "engineer", "fisherman", "hag", "hadjiya"],
        "first_night_order": [],
        "other_nights_order": ["hag", "hadjiya"],
        "notes": "测试",
    }
    st_events.clear()
    await sio_st.emit("save_script", new_script)
    await asyncio.sleep(0.3)
    sl = [e for e in st_events if e[0] == "script_list"]
    assert sl and "test_t7" in [s["id"] for s in sl[-1][1]["scripts"]], \
        f"saved script not in list"
    print(f"[PASS] save_script: test_t7 in registry")

    # get test_t7
    st_events.clear()
    await sio_st.emit("get_script", {"script_id": "test_t7"})
    await asyncio.sleep(0.3)
    sd = [e for e in st_events if e[0] == "script_detail"]
    assert sd and sd[-1][1]["name"] == "测试板子(7人)"
    print(f"[PASS] get test_t7: name='{sd[-1][1]['name']}'")

    # select_script (only in lobby)
    st_events.clear()
    await sio_st.emit("select_script", {"script_id": "test_t7"})
    await asyncio.sleep(0.3)
    state = _latest_st_state(st_events)
    assert state["script_id"] == "test_t7", f"script_id should change; got {state['script_id']}"
    print(f"[PASS] select_script: state.script_id = test_t7")

    # G. delete default 应被拒
    st_events.clear()
    await sio_st.emit("delete_script", {"script_id": "default"})
    await asyncio.sleep(0.3)
    errs = [e for e in st_events if e[0] == "error" and e[1].get("code") == "CANNOT_DELETE"]
    assert errs, f"deleting default should fail; got {st_events}"
    print(f"[PASS] delete default rejected")

    # 删除 test_t7 应成功
    st_events.clear()
    await sio_st.emit("delete_script", {"script_id": "test_t7"})
    await asyncio.sleep(0.3)
    sl = [e for e in st_events if e[0] == "script_list"]
    if sl:
        assert "test_t7" not in [s["id"] for s in sl[-1][1]["scripts"]], \
            "test_t7 should be removed"
    print(f"[PASS] delete test_t7 succeeded")

    # 非 ST 调 save_script 应被拒
    p_events[0].clear()
    await players[0].emit("save_script", new_script)
    await asyncio.sleep(0.3)
    errs = [e for e in p_events[0] if e[0] == "error" and e[1].get("code") == "NOT_STORYTELLER"]
    assert errs, f"non-ST should be rejected; got {p_events[0]}"
    print(f"[PASS] non-ST save_script rejected")

    await _disconnect_all(sio_st, players)


async def main():
    await scenario_assign_with_script()
    await scenario_script_management()
    banner("STAGE 4 SCRIPTS: ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())