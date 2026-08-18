"""E2E: 自定义角色 ID + st_change_role (用 ScriptRole 直接构造,避开 base64)。"""
import asyncio, os, sys
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
import socketio
from server.engine.script import Script, ScriptRole


async def main():
    sio_st = socketio.AsyncClient()
    st_events = []
    @sio_st.on('room_created')
    def _(d): st_events.append(('room_created', d))
    @sio_st.on('error')
    def _(d): st_events.append(('error', d))
    @sio_st.on('st_state_update')
    def _(d): st_events.append(('st_state_update', d))
    @sio_st.on('script_parsed')
    def _(d): st_events.append(('script_parsed', d))

    await sio_st.connect('http://localhost:5000', transports=['websocket'])
    await sio_st.emit('create_room', {'name': 'ST'})
    await asyncio.sleep(0.4)
    room_code = st_events[0][1]['room_code']
    print(f'房间 {room_code}')

    # 5 玩家加入
    p_clients, p_infos = [], []
    for i in range(5):
        sio = socketio.AsyncClient()
        evs = []
        @sio.on('joined')
        def _(d, evs=evs): evs.append(('joined', d))
        @sio.on('state_update')
        def _(d, evs=evs): evs.append(('state_update', d))
        await sio.connect('http://localhost:5000', transports=['websocket'])
        await sio.emit('join_room', {'room_code': room_code, 'name': f'P{i+1}'})
        await asyncio.sleep(0.2)
        j = [e for e in evs if e[0] == 'joined'][0][1]
        p_clients.append((sio, evs))
        p_infos.append((j['player_id'], j['player_token']))

    # 用 ScriptRole 直接构造脚本(13T/4O/4M/2D,5 人局)
    script = Script(id='custom', name='Custom', roles=[
        ScriptRole(id=f'No.{i}', team='townsfolk') for i in range(1, 14)
    ] + [
        ScriptRole(id='No.3',  team='outsider',  name='落难少女'),
        ScriptRole(id='No.11', team='outsider'),
        ScriptRole(id='No.21', team='outsider', replace_with=[f'No.{i}' for i in [20, 19, 18, 17, 16, 15, 14, 13, 12, 4, 2]]),
        ScriptRole(id='No.22', team='outsider'),
        ScriptRole(id='No.5',  team='minion'),
        ScriptRole(id='No.7',  team='minion'),
        ScriptRole(id='No.8',  team='minion'),
        ScriptRole(id='No.23', team='minion'),
        ScriptRole(id='No.9',  team='demon',  outsider_mod=-1),
        ScriptRole(id='No.10', team='demon'),
    ])
    await sio_st.emit('set_script', {'script': script.model_dump()})
    await asyncio.sleep(0.4)
    await sio_st.emit('start_game', {})
    await asyncio.sleep(0.4)

    p1_id, _ = p_infos[0]

    # === Case 1: 选 No.10 (脚本里有的) → 应成功 ===
    st_events.clear()
    await sio_st.emit('st_change_role', {'player_id': p1_id, 'new_role': 'No.10'})
    await asyncio.sleep(0.4)
    errs = [e for e in st_events if e[0] == 'error']
    if errs:
        print(f'[FAIL] Case 1: 选 No.10 居然报错: {errs[-1][1]}')
    else:
        st_state = [e for e in st_events if e[0] == 'st_state_update'][-1][1]
        p1 = next(p for p in st_state['players'] if p['id'] == p1_id)
        if p1.get('true_role') == 'No.10':
            print(f'[PASS] Case 1: No.10 变更成功 → P1 true_role = No.10 ✓')
        else:
            print(f'[FAIL] Case 1: P1 true_role = {p1.get("true_role")!r}')

    # === Case 2: 选 No.999 (不在脚本里) → 应报 INVALID_ROLE ===
    st_events.clear()
    await sio_st.emit('st_change_role', {'player_id': p1_id, 'new_role': 'No.999'})
    await asyncio.sleep(0.4)
    errs = [e for e in st_events if e[0] == 'error']
    if errs and 'INVALID_ROLE' in errs[-1][1].get('code', ''):
        print(f'[PASS] Case 2: No.999 正确报错 ✓ {errs[-1][1]}')
    else:
        print(f'[FAIL] Case 2: 应该报 INVALID_ROLE 但收到: {errs}')

    for sio, _ in p_clients:
        try: await sio.disconnect()
        except: pass
    await sio_st.disconnect()


asyncio.run(main())
