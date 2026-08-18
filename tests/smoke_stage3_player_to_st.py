"""玩家给说书人发日志:回归测试。

场景:
  A. 玩家发送日志 → ST state.log 中可见,kind=player_to_st,visibility=private_to_st
  B. 发送者本人的 filtered_log 包含这条
  C. 其它玩家的 filtered_log 不包含
  D. ST 不可发送给自己(普通玩家接口)
  E. 空文本被拒
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


def _make_clients(n_players=3):
    sio_st = socketio.AsyncClient()
    players = [socketio.AsyncClient() for _ in range(n_players)]
    st_events = []
    p_events = [[] for _ in range(n_players)]

    @sio_st.on("room_created")
    def _(d): st_events.append(("room_created", d))
    @sio_st.on("st_state_update")
    def _(d): st_events.append(("st_state_update", d))
    @sio_st.on("error")
    def _(d): st_events.append(("error", d))

    for i, sio in enumerate(players):
        sio.on("joined", lambda d, i=i: p_events[i].append(("joined", d)))
        sio.on("player_state", lambda d, i=i: p_events[i].append(("player_state", d)))
        sio.on("error", lambda d, i=i: p_events[i].append(("error", d)))

    return sio_st, players, st_events, p_events


async def _setup_room(n_players=3):
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


def _latest_player_state(p_events, idx):
    states = [e for e in p_events[idx] if e[0] == "player_state"]
    return states[-1][1] if states else None


async def scenario_player_to_st():
    banner("A/B/C/D/E: 玩家发送日志给说书人")
    sio_st, players, st_events, p_events, room_code, p_ids = await _setup_room(3)
    await asyncio.sleep(0.3)

    st_events.clear()
    for pe in p_events: pe.clear()

    # A. p1 发送一条消息
    await players[0].emit("player_send_to_st", {"text": "我观察到 p3 好像有点奇怪"})
    await asyncio.sleep(0.4)

    # ST 状态日志中应有该条
    state = _latest_st_state(st_events)
    assert state is not None
    p2st_logs = [e for e in state["log"] if e.get("kind") == "player_to_st"]
    assert len(p2st_logs) == 1, f"ST log should have 1 player_to_st; got {len(p2st_logs)}"
    entry = p2st_logs[0]
    assert entry["visibility"] == "private_to_st"
    assert entry["sender_id"] == p_ids[0]
    assert "📨" in entry["text"]
    assert "[p1]" in entry["text"] or "p1" in entry["text"]
    print(f"[PASS] ST sees log: '{entry['text']}'")

    # B. 发送者(p1)自己的 filtered_log 应包含
    ps0 = _latest_player_state(p_events, 0)
    assert ps0 is not None
    own_matches = [e for e in ps0["filtered_log"] if e.get("kind") == "player_to_st"]
    assert len(own_matches) == 1, f"sender should see own message; got {len(own_matches)}"
    print(f"[PASS] sender p1 sees own message in filtered_log")

    # C. 其它玩家(p2/p3)filtered_log 不应包含
    ps1 = _latest_player_state(p_events, 1)
    ps2 = _latest_player_state(p_events, 2)
    for label, ps in [("p2", ps1), ("p3", ps2)]:
        others = [e for e in ps["filtered_log"] if e.get("kind") == "player_to_st"] if ps else []
        assert not others, f"{label} should NOT see sender's private log; got {others}"
    print(f"[PASS] other players do NOT see the message")

    # D. ST 不可通过 player_send_to_st 给自己发
    # (虽然 ST 客户端不会触发,但服务端应该防御)
    st_events.clear()
    # 模拟 ST 直接 emit player_send_to_st:服务端会因 is_storyteller 拒绝
    # 注意:我们的 ST sio_st 没有监听 player_send_to_st 不会收到 error,但服务端会发 error
    # 这里我们直接测后端防御逻辑:让 ST 模拟 player 行为
    # 由于 ST 是另一个 sid,改用:创建一个 sid 模拟玩家但 player.is_storyteller=True 来测试
    # 实际上 player.is_storyteller 由服务端从 state.players 推断,ST 永远 is_storyteller=True
    # 所以无论什么 sid,ST 都会 is_storyteller=True,会拒绝
    # 这里跳过直接测试,逻辑已在 state_machine 验证

    # E. 空文本被拒
    p_events[0].clear()
    await players[0].emit("player_send_to_st", {"text": "   "})
    await asyncio.sleep(0.3)
    errs = [e for e in p_events[0] if e[0] == "error" and e[1].get("code") == "INVALID_INPUT"]
    assert errs, "empty text should be rejected"
    print(f"[PASS] empty text rejected")

    await _disconnect_all(sio_st, players)
    print("[OK] Scenario passed.")


async def scenario_st_blocked_from_self():
    """防御:ST 试图通过 player_send_to_st 发送给自己应被拒。"""
    banner("F: ST 不能调用 player_send_to_st")
    sio_st, players, st_events, p_events, room_code, p_ids = await _setup_room(2)
    await asyncio.sleep(0.3)

    st_events.clear()
    # ST 用自己 sid 发 player_send_to_st;服务端应因 is_storyteller 返回错误
    # 服务端会 emit("error", {code: NOT_PLAYER, ...}) 给 ST
    # 由于 ST sio_st 监听了 error,我们需要查找
    await sio_st.emit("player_send_to_st", {"text": "我想给自己发"})
    await asyncio.sleep(0.3)
    errs = [e for e in st_events if e[0] == "error" and e[1].get("code") == "NOT_PLAYER"]
    assert errs, f"ST should be rejected; got {[e for e in st_events if e[0] == 'error']}"
    print(f"[PASS] ST blocked: {errs[-1][1]}")

    await _disconnect_all(sio_st, players)
    print("[OK] Scenario F passed.")


async def main():
    await scenario_player_to_st()
    await scenario_st_blocked_from_self()
    banner("PLAYER->ST: ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())