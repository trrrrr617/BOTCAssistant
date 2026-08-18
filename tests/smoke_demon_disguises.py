"""恶魔伪装(_compute_demon_disguises)单元测试。

不需要 server / eventlet,直接调函数验证。
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# 触发 eventlet monkey_patch(server/__init__.py 的副作用)
import eventlet  # noqa
eventlet.monkey_patch()

import random
from server.engine.script import Script, ScriptRole
from server.engine.state_machine import (
    assign_roles,
    _compute_demon_disguises,
)


def _make_player(state, pid, name, seat):
    from server.engine.game_state import Player, PlayerStatus
    state.players.append(Player(id=pid, name=name, seat=seat, status=PlayerStatus.ALIVE))


def _make_script_with_replace():
    """包含 drunk(replace_with) + 多个善良角色的脚本。"""
    return Script(
        id="t",
        name="test",
        roles=[
            ScriptRole(id="a", name="甲", team="townsfolk"),
            ScriptRole(id="b", name="乙", team="townsfolk"),
            ScriptRole(id="c", name="丙", team="townsfolk"),
            ScriptRole(id="d", name="丁", team="outsider"),
            ScriptRole(id="e", name="戊", team="outsider"),
            ScriptRole(id="drunk", name="酒鬼", team="outsider", replace_with=["a"]),
            ScriptRole(id="poisoner", name="投毒者", team="minion"),
            ScriptRole(id="imp", name="小恶魔", team="demon"),
        ],
    )


def _new_state(script):
    from server.engine.game_state import GameState, Phase
    return GameState(room_code="R", phase=Phase.LOBBY, script=script)


def test_basic_no_replace():
    """无 replace_with 时:候选 = 善良阵营 - 在场角色;N = 恶魔 + 爪牙 + 1。

    5 人:N=3。池子至少要有 3(在场 T)+3(伪装)=6 个善良角色。
    """
    s = Script(
        id="t", name="t",
        roles=[
            ScriptRole(id="t1", team="townsfolk"),
            ScriptRole(id="t2", team="townsfolk"),
            ScriptRole(id="t3", team="townsfolk"),
            ScriptRole(id="t4", team="townsfolk"),
            ScriptRole(id="t5", team="townsfolk"),
            ScriptRole(id="t6", team="townsfolk"),
            ScriptRole(id="o1", team="outsider"),
            ScriptRole(id="m1", team="minion"),
            ScriptRole(id="d1", team="demon"),
        ],
    )
    st = _new_state(s)
    for i in range(5):
        _make_player(st, f"p{i}", f"P{i}", i)
    st = assign_roles(st, seed=42)
    # N = 1 恶魔 + 1 爪牙 + 1 = 3
    assert len(st.demon_disguises) == 3, f"expected 3 disguises, got {st.demon_disguises}"
    # 所有伪装必须是善良角色
    roles_by_id = {r.id: r for r in s.roles}
    for rid in st.demon_disguises:
        assert roles_by_id[rid].team in ("townsfolk", "outsider"), \
            f"disguise {rid} 不是善良阵营"
    # 不能与在场角色重叠
    in_play = set()
    for p in st.players:
        if p.true_role: in_play.add(p.true_role)
        if p.apparent_role: in_play.add(p.apparent_role)
    for rid in st.demon_disguises:
        assert rid not in in_play, f"disguise {rid} 与在场角色重叠"
    print(f"[PASS] basic_no_replace: disguises={st.demon_disguises}")


def test_excludes_replace_with():
    """有 replace_with 的角色不能作为伪装。"""
    s = Script(
        id="t", name="t",
        roles=[
            ScriptRole(id="t1", team="townsfolk"),
            ScriptRole(id="t2", team="townsfolk"),
            ScriptRole(id="t3", team="townsfolk"),
            ScriptRole(id="t4", team="townsfolk"),
            ScriptRole(id="t5", team="townsfolk"),
            ScriptRole(id="o1", team="outsider"),
            # drunk 是外来者且带 replace_with,不应进入伪装池
            ScriptRole(id="drunk", team="outsider", replace_with=["t1"]),
            ScriptRole(id="m1", team="minion"),
            ScriptRole(id="d1", team="demon"),
        ],
    )
    st = _new_state(s)
    for i in range(5):
        _make_player(st, f"p{i}", f"P{i}", i)
    st = assign_roles(st, seed=7)
    # 不能含 drunk
    assert "drunk" not in st.demon_disguises, \
        f"带 replace_with 的角色不应进入伪装池: {st.demon_disguises}"
    print(f"[PASS] test_excludes_replace_with: disguises={st.demon_disguises}")


def test_in_play_includes_apparent():
    """drunk 变成 a 后,a 视为在场,不能作为伪装。

    6 人:基础 5T,0O,0M,1D。但我们要测 drunk 走 replace_with 路径,
    因此手工强制 drunk 必须被抽中(seed 不重要,可能需要重试)。
    直接观察任何抽到 drunk 的情况下 a 不在伪装池。
    """
    s = Script(
        id="t", name="t",
        roles=[
            ScriptRole(id="a", team="townsfolk"),
            ScriptRole(id="b", team="townsfolk"),
            ScriptRole(id="c", team="townsfolk"),
            ScriptRole(id="d", team="townsfolk"),
            ScriptRole(id="e", team="townsfolk"),
            ScriptRole(id="f", team="townsfolk"),
            ScriptRole(id="g", team="townsfolk"),
            ScriptRole(id="drunk", team="outsider", replace_with=["a"]),
            ScriptRole(id="m1", team="minion"),
            ScriptRole(id="d1", team="demon"),
        ],
    )
    st = _new_state(s)
    for i in range(6):
        _make_player(st, f"p{i}", f"P{i}", i)
    # 多跑几次直到抽到 drunk
    for seed in range(50):
        st = _new_state(s)
        for i in range(6):
            _make_player(st, f"p{i}", f"P{i}", i)
        st = assign_roles(st, seed=seed)
        drunk_player = next((p for p in st.players if p.true_role == "drunk"), None)
        if drunk_player is not None:
            break
    assert drunk_player is not None, "50 次都没抽到 drunk"
    assert drunk_player.apparent_role == "a", \
        f"drunk 应表现为 a,但 got {drunk_player.apparent_role}"
    # a 视为在场,不能作为伪装
    assert "a" not in st.demon_disguises, \
        f"drunk→a 后 a 应在场,不应作为伪装: {st.demon_disguises}"
    print(f"[PASS] test_in_play_includes_apparent: disguises={st.demon_disguises}")


def test_insufficient_candidates_raises():
    """候选不足应抛 ValueError。"""
    s = Script(
        id="t", name="t",
        roles=[
            # 只有 1 个 townsfolk + 1 个 outsider,5 人需 3 善良在位 + 3 伪装 = 6
            # 池子只有 2 个,远不够 → 抛错
            ScriptRole(id="t1", team="townsfolk"),
            ScriptRole(id="o1", team="outsider"),
            ScriptRole(id="m1", team="minion"),
            ScriptRole(id="d1", team="demon"),
        ],
    )
    st = _new_state(s)
    for i in range(5):
        _make_player(st, f"p{i}", f"P{i}", i)
    raised = False
    try:
        st = assign_roles(st, seed=42)
    except ValueError as e:
        raised = True
        msg = str(e)
        # 这里中文可能在 cmd 里乱码,但 .encode().hex() 看字节也行
        # 简单断言 contains 字符子集
        assert "3" in msg, f"错误信息应提及数量 3: {msg}"
    assert raised, "候选不足应抛 ValueError,但没抛"
    print(f"[PASS] test_insufficient_candidates_raises")


def test_n_equals_evil_count_plus_one():
    """验证 N = 恶魔数 + 爪牙数 + 1。

    7 人:基础 5T,0O,1M,1D → N = 1 + 1 + 1 = 3
    需要 5T 在场 + 3 伪装 = 8 个候选(都是 townsfolk)
    """
    s = Script(
        id="t", name="t",
        roles=[
            ScriptRole(id="t1", team="townsfolk"),
            ScriptRole(id="t2", team="townsfolk"),
            ScriptRole(id="t3", team="townsfolk"),
            ScriptRole(id="t4", team="townsfolk"),
            ScriptRole(id="t5", team="townsfolk"),
            ScriptRole(id="t6", team="townsfolk"),
            ScriptRole(id="t7", team="townsfolk"),
            ScriptRole(id="t8", team="townsfolk"),
            ScriptRole(id="m1", team="minion"),
            ScriptRole(id="d1", team="demon"),
        ],
    )
    st = _new_state(s)
    for i in range(7):
        _make_player(st, f"p{i}", f"P{i}", i)
    st = assign_roles(st, seed=99)
    # 7 人:基础 5T,0O,1M,1D → N = 1 + 1 + 1 = 3
    assert len(st.demon_disguises) == 3, \
        f"7 人应 N=3,got {st.demon_disguises}"
    print(f"[PASS] test_n_equals_evil_count_plus_one: N=3, disguises={st.demon_disguises}")


if __name__ == "__main__":
    test_basic_no_replace()
    test_excludes_replace_with()
    test_in_play_includes_apparent()
    test_insufficient_candidates_raises()
    test_n_equals_evil_count_plus_one()
    print("\n[OK] all 5 tests passed")
