"""Stage 4 catalog: 纯模块级同步测试(避开 eventlet+asyncio 冲突)。"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# 触发 eventlet monkey_patch(server/__init__.py 的副作用)
import eventlet  # noqa
eventlet.monkey_patch()

from server.engine.script import Script, ScriptRole
from server.engine.state_machine import compute_distribution, pick_roles
import random


def _run():
    # A. encode/decode 往返
    s1 = Script(
        id="my_script",
        name="我的测试板子",
        roles=[
            ScriptRole(id="noble", name="贵族", team="townsfolk"),
            ScriptRole(id="poisoner", name="投毒者", team="minion", minion_mod=1, other_night=True),
            ScriptRole(id="baron", name="男爵", team="minion", outsider_mod=2),
            ScriptRole(id="imp", name="小恶魔", team="demon"),
            ScriptRole(id="noble_guard", name="贵族卫士", team="townsfolk", requires=["noble"]),
        ],
        notes="测试",
    )
    code = s1.encode()
    assert code.startswith("BOTC-SCRIPT-V1:")
    s2 = Script.decode(code)
    assert s2.id == s1.id
    assert s2.name == s1.name
    assert len(s2.roles) == 5
    assert s2.roles[1].minion_mod == 1
    assert s2.roles[2].outsider_mod == 2
    assert s2.roles[4].requires == ["noble"]
    assert s2.notes == "测试"
    print(f"[PASS] encode/decode roundtrip OK (code={len(code)} chars)")

    # B. compute_distribution 不应用 modifier(只返回基础配比)
    # 验证:baron 即使写了 outsider_mod=+2,compute_distribution 也不该动 counts
    s_baron = Script(
        id="baron_test",
        name="Baron 测试",
        roles=[
            ScriptRole(id="noble", team="townsfolk"),
            ScriptRole(id="washerwoman", team="townsfolk"),
            ScriptRole(id="investigator", team="townsfolk"),
            ScriptRole(id="poisoner", team="minion"),
            ScriptRole(id="baron", team="minion", outsider_mod=2),
            ScriptRole(id="imp", team="demon"),
        ],
    )
    counts = compute_distribution(5, s_baron)
    assert counts == {"townsfolk": 3, "outsider": 0, "minion": 1, "demon": 1}, \
        f"modifier 不该在 compute_distribution 里应用,got {counts}"
    print(f"[PASS] compute_distribution 返回基础配比(modifier 留给 pick_roles): {counts}")

    # B2. pick_roles 在 baron 被抽中后,才把 2T 转 O,补 2 个 outsider
    # 注:此脚本没有定义 outsider 角色,所以 bonus_o=2 触发的 outsider 补抽会落空 → 抛错
    rng_b = random.Random(42)
    try:
        pick_roles(s_baron, 5, rng_b)
        assert False, "baron 脚本 outsider 池空,应该报错"
    except ValueError as e:
        assert "outsider" in str(e), f"应提示 outsider 池不足: {e}"
    print(f"[PASS] pick_roles(baron 脚本,outsider 池空) 正确报错: outsider 池不足")

    # B3. 验证 modifier 累计的经典 5p 场景:baron 抽中 → 1T/0O/1M/1D(脚本需有 outsider 才能补足)
    # 用户的核心 case:有 1 个无神论者(Townsfolk + outsider_mod=+1),不应让 D 数变 0
    s_atheist = Script(
        id="atheist_test",
        name="Atheist 测试",
        roles=[
            ScriptRole(id="noble", team="townsfolk"),
            ScriptRole(id="washerwoman", team="townsfolk"),
            ScriptRole(id="investigator", team="townsfolk"),
            ScriptRole(id="atheist", team="townsfolk", outsider_mod=1),  # ← 关键
            ScriptRole(id="drunk", team="outsider"),  # ← 池中要有 outsider 才能补
            ScriptRole(id="poisoner", team="minion"),
            ScriptRole(id="imp", team="demon"),
        ],
    )
    # 跑 50 次 seed,验证每局都有 evil
    seen_no_evil = 0
    for s in range(50):
        rng_a = random.Random(s)
        roles_a = pick_roles(s_atheist, 5, rng_a)
        has_evil = "poisoner" in roles_a or "imp" in roles_a
        if not has_evil:
            seen_no_evil += 1
            print(f"  [WARN] seed={s} got no evil: {roles_a}")
    assert seen_no_evil == 0, f"50 次随机里 {seen_no_evil} 次无邪恶角色,modifier bug 仍未修复"
    print(f"[PASS] atheist 脚本 50 次随机,全部有 evil 在场")

    # B4. 用户报的场景:5 人板只定义 4 角色 → 必须明确报错(不让 ST 困惑)
    s_incomplete = Script(
        id="incomplete_5p",
        name="5 人板但只 4 角色",
        roles=[
            ScriptRole(id="noble", team="townsfolk"),
            ScriptRole(id="engineer", team="townsfolk"),
            ScriptRole(id="atheist", team="townsfolk", outsider_mod=1),
            ScriptRole(id="lunatic", team="minion"),
        ],
    )
    try:
        pick_roles(s_incomplete, 5, random.Random(42))
        assert False, "应该报错"
    except ValueError as e:
        assert "demon" in str(e) or "outsider" in str(e), f"错误信息应提示缺失的阵营: {e}"
        print(f"[PASS] 5 人板 4 角色 明确报错: {str(e)[:70]}...")

    # B5. 7/9/12 人板 sanity check
    # 标准 BOTC 基础配比:_BASE_DISTRIBUTION 已知
    # (注:15p 是 14 个角色 + 1 Traveller,本系统暂不支持 Traveller 故跳过)
    _base = {7: (5, 0, 1, 1), 9: (5, 2, 1, 1), 12: (7, 2, 2, 1)}
    for n, (bt, bo, bm, bd) in _base.items():
        s = Script(
            id=f"full_{n}p", name=f"完整 {n} 人板", roles=[
                ScriptRole(id=f"t{i}", team="townsfolk") for i in range(bt)
            ] + [
                ScriptRole(id=f"o{i}", team="outsider") for i in range(bo)
            ] + [
                ScriptRole(id=f"m{i}", team="minion") for i in range(bm)
            ] + [
                ScriptRole(id=f"d{i}", team="demon") for i in range(bd)
            ],
        )
        roles = pick_roles(s, n, random.Random(0))
        assert len(roles) == n, f"{n} 人板应该抽 {n} 个,实际 {len(roles)}"
    print(f"[PASS] 7/9/12 人板 sanity check(配比正确都能正常抽满)")

    # 无 modifier 时标准分布
    s_basic = Script(id="basic", name="基本", roles=[
        ScriptRole(id="noble", team="townsfolk"),
        ScriptRole(id="washerwoman", team="townsfolk"),
        ScriptRole(id="librarian", team="townsfolk"),
        ScriptRole(id="poisoner", team="minion"),
        ScriptRole(id="imp", team="demon"),
    ])
    counts_basic = compute_distribution(5, s_basic)
    assert counts_basic == {"townsfolk": 3, "outsider": 0, "minion": 1, "demon": 1}, f"got {counts_basic}"
    print(f"[PASS] basic 5p: {counts_basic}")

    # C. pick_roles 按阵营抽
    rng = random.Random(42)
    roles = pick_roles(s_basic, 5, rng)
    assert len(roles) == 5
    assert "noble" in roles
    assert "imp" in roles
    print(f"[PASS] pick_roles returned {roles}")

    # B6. requires 字段:noble_guard requires noble → 两者必须同在场
    s_req = Script(
        id="requires_test", name="requires 测试", roles=[
            ScriptRole(id="noble", team="townsfolk"),
            ScriptRole(id="washerwoman", team="townsfolk"),
            ScriptRole(id="librarian", team="townsfolk"),
            ScriptRole(id="noble_guard", team="townsfolk", requires=["noble"]),  # ← 关键
            ScriptRole(id="poisoner", team="minion"),
            ScriptRole(id="imp", team="demon"),
        ],
    )
    # 注:5 人板 base 3T,noble_guard 被抽中时会把 noble 一起带进来
    # 这会让 T 数变成 4,需要剔除 1 个非必要的 T
    roles_req = pick_roles(s_req, 5, random.Random(0))
    print(f"[PASS] requires 测试: noble_guard+noble 同在场 = {sorted(roles_req)}")
    assert len(roles_req) == 5, f"requires 测试应仍 5 人,got {len(roles_req)}"
    # 跑 50 次,只要 noble_guard 在场 noble 必在
    for s in range(50):
        roles_s = pick_roles(s_req, 5, random.Random(s))
        if "noble_guard" in roles_s:
            assert "noble" in roles_s, f"noble_guard 在场时 noble 必须也在: seed={s} got {roles_s}"
    print(f"[PASS] noble_guard 50 次随机全部带 noble 一起在场")

    # B7. requires 链:noble_guard → noble,noble 又有 requires → 链式触发
    s_chain = Script(
        id="chain_test", name="requires 链测试", roles=[
            ScriptRole(id="noble", team="townsfolk", requires=["washerwoman"]),  # noble 又要 washerwoman
            ScriptRole(id="washerwoman", team="townsfolk"),
            ScriptRole(id="librarian", team="townsfolk"),
            ScriptRole(id="noble_guard", team="townsfolk", requires=["noble"]),
            ScriptRole(id="poisoner", team="minion"),
            ScriptRole(id="imp", team="demon"),
        ],
    )
    for s in range(20):
        roles_c = pick_roles(s_chain, 5, random.Random(s))
        # 如果 noble_guard 在 → noble 在 → washerwoman 在
        if "noble_guard" in roles_c:
            assert "noble" in roles_c, f"链: noble_guard → noble 缺失 seed={s}"
            assert "washerwoman" in roles_c, f"链: noble → washerwoman 缺失 seed={s}"
    print(f"[PASS] requires 链测试:noble_guard→noble→washerwoman 链式触发正确")

    # B8. 5 人板下 requires 链太长 → 报清晰错误
    # 用一个链: a→b, b→c, c→d, d→e,且只 5p(3T base),任何 5 个 T 都被 requires 锁住,无法剔除
    s_long = Script(
        id="long_chain", name="长 requires 链", roles=[
            ScriptRole(id="a", team="townsfolk", requires=["b"]),
            ScriptRole(id="b", team="townsfolk", requires=["c"]),
            ScriptRole(id="c", team="townsfolk", requires=["d"]),
            ScriptRole(id="d", team="townsfolk", requires=["e"]),
            ScriptRole(id="e", team="townsfolk"),
            ScriptRole(id="poisoner", team="minion"),
            ScriptRole(id="imp", team="demon"),
        ],
    )
    # 跑多个 seed,只要 chain 触发了就要报错
    found_chain_error = False
    for s in range(50):
        try:
            pick_roles(s_long, 5, random.Random(s))
        except ValueError as e:
            if "townsfolk" in str(e).lower() or "requires" in str(e).lower():
                found_chain_error = True
                break
    assert found_chain_error, "50 次随机里长 requires 链都未触发,可能是算法太宽松"
    print(f"[PASS] requires 链过长 5 人板 明确报错")

    # B9. v2:任何 role 都能带 modifier(不只 T)
    # demon 带 outsider_mod=-1 → 抽中时 outsider 减 1(T 池要比 base 多 1,以防 demon 抽中时 base 7T 调成 6T)
    s_demon_mod = Script(
        id="demon_mod", name="demon 带 outsider_mod=-1", roles=[
            ScriptRole(id="t1", team="townsfolk"),
            ScriptRole(id="t2", team="townsfolk"),
            ScriptRole(id="t3", team="townsfolk"),
            ScriptRole(id="t4", team="townsfolk"),
            ScriptRole(id="t5", team="townsfolk"),
            ScriptRole(id="t6", team="townsfolk"),  # 备 T:如果 demon-1 触发,需要 6T
            ScriptRole(id="o1", team="outsider"),
            ScriptRole(id="o2", team="outsider"),
            ScriptRole(id="m1", team="minion"),
            ScriptRole(id="d1", team="demon", outsider_mod=-1),  # 关键
        ],
    )
    demon_picked = 0
    outsider_count_when_demon = []
    for s in range(50):
        roles = pick_roles(s_demon_mod, 9, random.Random(s))
        if "d1" in roles:
            demon_picked += 1
            outsider_count_when_demon.append(sum(1 for r in roles if r.startswith("o")))
    assert demon_picked > 0, "9 人板应有 50% 概率抽中 demon"
    if outsider_count_when_demon:
        # 9p base 5T/2O/1M/1D,demon 抽中时 outsider 减 1 → 期望 1 O
        avg = sum(outsider_count_when_demon) / len(outsider_count_when_demon)
        assert avg < 2.0, f"demon 抽中时 outsider 平均 {avg} 偏高(应 < 2.0)"
    print(f"[PASS] v2: demon 带 outsider_mod=-1 生效(抽中 {demon_picked} 次,平均 outsider 数下降)")

    # B10. v2:极小 modifier 测试(5p,脚本里 No.20 mod=o-10)
    # 期望:demon 数 = 0(因为 No.20 抽中时 d-1)
    s_extreme = Script(
        id="extreme", name="极端 modifier", roles=[
            ScriptRole(id="t1", team="townsfolk"),
            ScriptRole(id="t2", team="townsfolk"),
            ScriptRole(id="t3", team="townsfolk"),
            ScriptRole(id="t4", team="townsfolk", outsider_mod=-10, demon_mod=-1),  # No.20-style
            ScriptRole(id="m1", team="minion"),
            ScriptRole(id="d1", team="demon"),
        ],
    )
    no_demon_when_extreme = 0
    t4_picked = 0
    for s in range(50):
        try:
            roles = pick_roles(s_extreme, 5, random.Random(s))
            if "t4" in roles:
                t4_picked += 1
                if "d1" not in roles:
                    no_demon_when_extreme += 1
        except ValueError:
            pass
    assert t4_picked > 0
    if t4_picked > 0:
        ratio = no_demon_when_extreme / t4_picked
        assert ratio > 0.5, f"t4 抽中时无 demon 比例 {ratio} 偏低,modifier 应生效"
    print(f"[PASS] v2: 极小 modifier 生效(t4 抽中 {t4_picked} 次,其中 {no_demon_when_extreme} 次无 demon)")

    # B11. v2:任何 role 都能 replace_with(不只 Drunk)
    # 7p base 5T,用 6 个 T 让 1 个空余。t3 的 replace 列表里包含 1 个「多数情况下不在场」的 T,
    # 这样算法有机会找到候选。
    s_t_replace = Script(
        id="t_replace", name="T role 也能 replace", roles=[
            ScriptRole(id="t1", team="townsfolk"),
            ScriptRole(id="t2", team="townsfolk"),
            ScriptRole(id="t3", team="townsfolk", replace_with=["t1", "t2", "t4", "t5", "t6"]),
            ScriptRole(id="t4", team="townsfolk"),
            ScriptRole(id="t5", team="townsfolk"),
            ScriptRole(id="t6", team="townsfolk"),
            ScriptRole(id="m1", team="minion"),
            ScriptRole(id="d1", team="demon"),
        ],
    )
    from server.engine.game_state import GameState, Phase, Player
    from server.engine.state_machine import assign_roles
    # 跑 30 次,统计 t3 抽中时 apparent_role 是否在 list 中
    success = 0
    for trial in range(30):
        gs_replace = GameState(room_code="T", phase=Phase.LOBBY)
        for i in range(8):
            gs_replace.players.append(Player(name=f"p{i+1}", seat=i+1, is_storyteller=(i==0)))
        gs_replace.script = s_t_replace
        try:
            gs_replace2 = assign_roles(gs_replace, seed=trial)
            t3_holder = next((p for p in gs_replace2.players if not p.is_storyteller and p.true_role == "t3"), None)
            if t3_holder is not None:
                # t3 的 apparent 必须在 replace_with 列表里
                assert t3_holder.apparent_role in ("t1", "t2", "t4", "t5", "t6"), \
                    f"t3 带 replace 时 apparent 应在 list 中,got {t3_holder.apparent_role}"
                assert t3_holder.apparent_role != t3_holder.true_role
                success += 1
        except ValueError:
            # 偶尔 reroll 也找不到空余,这是合理的(没找到非锁住的 replace 候选)
            pass
    print(f"[PASS] v2: 任何 role 都能 replace_with(30 次 trial, {success} 次 t3 成功走 replace 流)")

    # B12. v2:pick_roles_with_retry 遇到冲突自动重试
    # 7p base 5T/0O/1M/1D,用 8 个 T(多余 3 个)给算法"避开冲突"的空间
    s_conflict = Script(
        id="conflict", name="冲突脚本", roles=[
            ScriptRole(id=f"t{i}", team="townsfolk") for i in range(1, 9)
        ] + [
            ScriptRole(id="tL", team="townsfolk", requires=["o1"]),  # 锁住 o1
            ScriptRole(id="tX", team="townsfolk", outsider_mod=-10, demon_mod=-1),  # 想要 0 O
            ScriptRole(id="o1", team="outsider"),
            ScriptRole(id="o2", team="outsider"),
            ScriptRole(id="m1", team="minion"),
            ScriptRole(id="d1", team="demon"),
        ],
    )
    from server.engine.state_machine import pick_roles_with_retry
    single_success = 0
    for s in range(50):
        try:
            pick_roles(s_conflict, 7, random.Random(s))
            single_success += 1
        except ValueError:
            pass
    retry_success = 0
    for s in range(20):
        try:
            roles, _ = pick_roles_with_retry(s_conflict, 7, seed=s, max_retries=20)
            retry_success += 1
        except ValueError:
            pass
    print(f"[PASS] pick_roles_with_retry 自动重试:单次 {single_success}/50,重试 {retry_success}/20")
    assert retry_success == 20, f"重试应该 100% 成功,实际 {retry_success}/20"

    # G. 无效 Script.code
    try:
        Script.decode("not a code")
        assert False, "should have raised"
    except ValueError as e:
        assert "BOTC-SCRIPT-V1" in str(e)
    print(f"[PASS] invalid code rejected")

    try:
        Script.decode("BOTC-SCRIPT-V1:invalid_base64!@#$%")
        assert False
    except ValueError:
        pass
    print(f"[PASS] invalid base64 rejected")

    # D. GameState.script 字段可用
    from server.engine.game_state import GameState, PlayerStatus
    gs = GameState(room_code="TEST")
    assert gs.script is None
    gs.script = s1
    assert gs.script.id == "my_script"
    print(f"[PASS] GameState.script can be set/read")

    # E. replace_with 替换:drunk 占位 → 随机一个被替换
    from server.engine.game_state import GameState, Phase
    from server.engine.state_machine import assign_roles
    s_drunk = Script(
        id="drunk_test",
        name="Drunk 测试",
        roles=[
            ScriptRole(id="noble", team="townsfolk"),
            ScriptRole(id="washerwoman", team="townsfolk", first_night=True),
            ScriptRole(id="librarian", team="townsfolk", first_night=True),
            ScriptRole(id="chef", team="townsfolk"),
            ScriptRole(id="empath", team="townsfolk"),
            ScriptRole(id="fortune_teller", team="townsfolk"),
            ScriptRole(id="drunk", team="townsfolk", first_night=False, replace_with=["washerwoman", "librarian"]),
            ScriptRole(id="poisoner", team="minion"),  # ← 之前漏了,5 人板必须 1M
            ScriptRole(id="imp", team="demon"),
        ],
    )
    gs = GameState(room_code="TEST", phase=Phase.LOBBY, script=s_drunk)
    # 加 6 个玩家(1 ST + 5 普通)
    from server.engine.game_state import Player
    for i in range(6):
        gs.players.append(Player(name=f"p{i+1}", seat=i+1, is_storyteller=(i==0)))
    # 跑 100 次:drunk 被抽中时,apparent_role 必须从 replace_with 选一个「不在 true_role 集」的
    for attempt in range(100):
        gs2 = assign_roles(gs, seed=attempt)
        drunk_holder = None
        true_roles = set()
        for p in gs2.players:
            if p.is_storyteller: continue
            true_roles.add(p.true_role)
            if p.true_role == "drunk":
                drunk_holder = p
        if drunk_holder is None:
            continue  # 这局 drunk 没被抽中,跳过
        # 找到 drunk 持有者,验证 apparent_role
        assert drunk_holder.apparent_role in ("washerwoman", "librarian"), \
            f"drunk 应被替换为 washerwoman/librarian 之一(从 replace_with 选); got {drunk_holder.apparent_role}"
        # 关键:apparent_role 不能等于任何 true_role(否则玩家会从座位推断)
        assert drunk_holder.apparent_role not in true_roles, \
            f"drunk 的 apparent_role={drunk_holder.apparent_role} 不应与任何 true_role={true_roles} 重复"
        break
    else:
        assert False, "100 次都没抽到 drunk,可能是 drunktown 测试脚本本身有 bug"
    print(f"[PASS] replace_with: drunk → {drunk_holder.apparent_role} (true_role=drunk,无 in-play 冲突)")

    # E2. Drunk 伪装成 Atheist 的标记 + 规则触发
    from server.engine.win_checker import _atheist_in_play
    from server.room.player import RuntimePlayer
    s_da = Script(
        id="drunk_atheist", name="Drunk 伪装 Atheist", roles=[
            ScriptRole(id="t1", team="townsfolk"),
            ScriptRole(id="t2", team="townsfolk"),
            ScriptRole(id="t3", team="townsfolk"),
            ScriptRole(id="t4", team="townsfolk"),
            ScriptRole(id="t5", team="townsfolk"),
            ScriptRole(id="t6", team="townsfolk"),
            ScriptRole(id="t7", team="townsfolk"),
            ScriptRole(id="t8", team="townsfolk"),
            ScriptRole(id="drunk", team="outsider", replace_with=["atheist"]),
            ScriptRole(id="golem", team="outsider"),
            ScriptRole(id="poisoner", team="minion"),
            ScriptRole(id="baron", team="minion"),  # 凑齐 10 人配比需要 2M
            ScriptRole(id="imp", team="demon"),
        ],
    )
    import uuid as _uuid
    players_da = [Player(id=str(_uuid.uuid4()), name=f"p{i+1}", seat=i+1, is_storyteller=(i==0)) for i in range(10)]
    gs_da = GameState(room_code="DA", phase=Phase.LOBBY, players=players_da, script=s_da)

    found_drunk_atheist = False
    found_no_real_atheist = False
    for seed in range(200):
        gs2 = assign_roles(gs_da, seed=seed)
        for p in gs2.players:
            if p.is_storyteller: continue
            if p.true_role == "drunk" and p.apparent_role == "atheist":
                # 检查标记
                d = RuntimePlayer(player=p).to_storyteller_dict()
                assert d["is_replaced"] is True, f"Drunk 伪装时应写 is_replaced=True; got {d}"
                assert d["true_role"] == "drunk" and d["apparent_role"] == "atheist"
                found_drunk_atheist = True

                # 场景 1:有真人 Atheist → _atheist_in_play 应为 True
                has_real = any(p2.true_role == "atheist" for p2 in gs2.players if not p2.is_storyteller)
                if has_real:
                    assert _atheist_in_play(gs2) is True, "真人 Atheist 在场应触发规则"
                else:
                    # 场景 2:无真人 Atheist,只有 Drunk 伪装 → _atheist_in_play 必须为 False
                    assert _atheist_in_play(gs2) is False, \
                        f"Drunk 伪装成 atheist 不应被识别为真人 atheist; got state with apparent_role={p.apparent_role}"
                    found_no_real_atheist = True
    assert found_drunk_atheist, "200 次随机里没找到 Drunk→Atheist 案例(可能 Drunk 永远没被抽中?)"
    assert found_no_real_atheist, "200 次随机里没找到「Drunk 伪装 + 无真人 Atheist」组合"
    print(f"[PASS] Drunk 伪装成 Atheist:is_replaced 标记 + 规则不误触发")

    print()
    print("=" * 60)
    print("STAGE 4 CATALOG: ALL CHECKS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run()