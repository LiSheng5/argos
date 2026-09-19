"""Benchmark 测试（Phase 7）。

这里钉的不只是"能跑"，更是**结论本身**：
  * 「反思只写不读 = 零价值」这个负结果一旦不再成立，测试要炸；
  * 「记忆过度泛化有代价」要一直可复现；
  * 以及本轮踩过的两个坑（空障碍被 falsy 吞掉、读写 Lesson 门槛不一致）。
"""
import pytest

from argos.agent.interfaces import FailReason
from argos.benchmark.configs import CONFIGS, config_by_name, make_agent_parts, make_memory
from argos.benchmark.report import render_markdown
from argos.benchmark.runner import run_matrix, run_scenario
from argos.benchmark.scenarios import build_scenarios, by_name, scenario_names
from argos.agent.memory_agent import AgentMemory, LessonStore


# ---------- 场景库 ----------

def test_at_least_20_scenarios_and_unique_names():
    names = scenario_names()
    assert len(names) >= 20
    assert len(set(names)) == len(names)


def test_transient_scenarios_really_have_no_obstacle():
    """回归钉：空障碍曾被 falsy 判断吞掉 → "瞬时故障"场景悄悄带了永久障碍。"""
    for s in build_scenarios():
        if s.kind == "transient":
            assert s.obstacles == (), f"{s.name} 的 obstacles 被回退成了默认世界"
            assert s.world().obstacles == (), f"{s.name} 的世界里仍有障碍"


def test_unknown_scenario_raises():
    with pytest.raises(KeyError):
        by_name("不存在的场景")


# ---------- 配置 ----------

def test_scenario_library_covers_every_injectable_failure_kind():
    """**覆盖守卫**：9 类可注入失败，每一类都要有场景跑到。

    这条是 2026-09-19 补的 —— 当时实测发现 benchmark 全矩阵**只用了障碍阻挡 1 类**，
    于是"反思有效"的结论其实只站在一类失败上。`network_delay` 不走注入器，
    而是由丢包延迟剖面产生，所以单列处理。
    """
    from argos.sim.failure_injector import INJECTABLE

    scenarios = build_scenarios()
    injected = {s.failure for s in scenarios}
    latency_names = {s.latency for s in scenarios if s.latency}
    NETWORK_DELAY_VIA_LATENCY = {"packet_loss"}      # 丢包剖面 → NETWORK_DELAY

    uncovered = []
    for kind in INJECTABLE:
        if kind in injected:
            continue
        if kind is FailReason.NETWORK_DELAY and latency_names & NETWORK_DELAY_VIA_LATENCY:
            continue
        uncovered.append(kind.value)
    assert not uncovered, f"这些失败类型没有任何场景覆盖：{uncovered}"
    assert len(injected) >= 8, "直接注入的类型数偏少"


def test_sensor_scenarios_declare_specs():
    """**覆盖守卫**：感知层要有场景真的用上（此前它从未进过 benchmark）。"""
    with_sensors = [s for s in build_scenarios() if s.sensors is not None]
    assert len(with_sensors) >= 3
    assert any(s.sensors.pose_dropout > 0 for s in with_sensors)     # 失灵
    assert any(s.sensors.pose_noise > 0 for s in with_sensors)       # 噪声
    assert any(s.sensors.obstacle_radius < 5.0 for s in with_sensors)  # 探测半径受限


def test_runner_actually_applies_sensors_and_failure_kind():
    """场景声明的东西必须真的接到 backend 上（否则声明只是装饰）。"""
    sc = by_name("sensor_pose_dropout")
    r = run_scenario(sc, config_by_name("planner_only"), 42)
    # 15% 整轮失灵 + 闸门 fail-closed 且不重试 → 至少有一轮报废
    assert any(not e.ok for e in r.episodes), "装了传感器却没影响到任何一轮，接线大概是断的"
    assert r.success_rate < 1.0

    sc2 = by_name("nonroute_failure_action_timeout")
    cfg = config_by_name("planner_only")
    r2 = run_scenario(sc2, cfg, 42)
    reasons = set()
    for e in r2.episodes:
        reasons.add(e.ok)
    assert any(e.failures > 0 for e in r2.episodes), "注入的失败没生效"


def test_nonroute_failures_teach_nothing_about_routes():
    """**负对照**：非路线类失败（定位漂移等）不该让任何一层去改路线。

    这是补覆盖时抓到真缺陷的地方 —— 当时语义层把"定位漂移"算成"这条路不顺"，
    学习臂于是比无记忆臂**多花 2 个动作**改走远路（失败数却一样，说明学错了对象）。
    修法见 `brain._is_route_reason`：`route_ok` 只由路线相关失败决定。
    """
    for name in ("nonroute_failure_localization_error", "nonroute_failure_action_timeout"):
        sc = by_name(name)
        base = run_scenario(sc, config_by_name("planner_only"), 42)
        for cfg_name in ("memory_only", "semantic_only", "memory_reflection"):
            r = run_scenario(sc, config_by_name(cfg_name), 42)
            assert r.avg_steps == base.avg_steps, \
                f"{name} × {cfg_name}：学习臂改变了路线选择，说明非路线失败被算到路线上了"
            assert r.avg_failures == base.avg_failures


def test_route_ok_only_counts_route_reasons():
    """单元钉：`_is_route_reason` 的判据与 Procedural 层同源。"""
    from argos.agent.brain import _is_route_reason
    assert _is_route_reason(FailReason.OBSTACLE_BLOCKED) is True
    assert _is_route_reason(FailReason.PATH_INVALID) is True
    assert _is_route_reason(FailReason.LOCALIZATION_ERROR) is False
    assert _is_route_reason(FailReason.BATTERY_LOW) is False
    assert _is_route_reason(FailReason.SAFETY_REJECTED) is False
    assert _is_route_reason("obstacle_blocked") is True      # trace 里存的是字符串
    assert _is_route_reason("这不是个失败原因") is False      # 认不出 → 不算路线问题
    assert _is_route_reason(None) is False


def test_arms_include_negative_and_special_purpose_ones():
    """六臂 = 指令要的四组对比 + 复核臂 + 语义软降权臂。"""
    names = [c.name for c in CONFIGS]
    assert names == ["planner_only", "semantic_only", "memory_only", "reflection_only",
                     "memory_reflection", "memory_reflection_revalidate"]
    assert config_by_name("reflection_only").consume is False          # 故意留的负结果臂
    assert config_by_name("semantic_only").semantic_only is True       # 只开软降权
    assert config_by_name("memory_reflection").revalidate_every == 0   # 不复核（会永久化）
    assert config_by_name("memory_reflection_revalidate").revalidate_every == 2


def test_reflection_only_writes_but_planner_cannot_read():
    """负结果臂的机制：反思写进 persistent，planner 读的是永远空的 store。"""
    persistent = AgentMemory()
    memory, reflector = make_agent_parts(config_by_name("reflection_only"), persistent)
    assert reflector.store is persistent.procedural
    assert memory.procedural is not persistent.procedural
    assert memory.procedural.all() == []


def test_zero_memory_arm_gets_no_semantic_leak():
    """回归钉：零记忆臂**不许**因为共享对象而偷偷学到东西。

    踩过的坑：把 memory 建在 episode 循环外，Semantic 窗口就跨 episode 共享了，
    连 `planner_only` 都能"学会"绕开被挡的路 —— 等于给无记忆臂开了软降权。
    """
    persistent = AgentMemory()
    cfg = config_by_name("planner_only")
    persistent.windows["north"] = [False, False]      # 假装持久记忆里已有证据
    mem = make_memory(cfg, persistent)
    assert mem.windows == {}                          # 不共享
    assert mem.soft_penalty() == {}
    assert mem.procedural.all() == []


def test_persistent_arms_do_share_semantic_windows():
    persistent = AgentMemory()
    persistent.windows["north"] = [False, False]
    for name in ("memory_only", "memory_reflection", "memory_reflection_revalidate",
                 "semantic_only"):
        mem = make_memory(config_by_name(name), persistent)
        assert mem.windows is persistent.windows, name


# ---------- 可复现 ----------

def test_same_seed_reproducible():
    sc = [by_name("permanent_block_x5.0_northfirst")]
    a = run_matrix(scenarios=sc, seeds=(42,))
    b = run_matrix(scenarios=sc, seeds=(42,))
    assert [(r.config, r.avg_steps, r.avg_failures) for r in a] == \
           [(r.config, r.avg_steps, r.avg_failures) for r in b]


# ---------- 核心结论（钉住，变了就要知道）----------

@pytest.mark.parametrize("cfg", ["planner_only", "memory_only", "reflection_only", "memory_reflection"])
def test_permanent_block_never_drops_success(cfg):
    """永久障碍下所有配置都能到达（本次运行内换路），区别只在过程代价。"""
    r = run_scenario(by_name("permanent_block_x5.0_northfirst"), config_by_name(cfg), 42)
    assert r.success_rate == 1.0


def test_memory_and_reflection_reduce_repeat_failures():
    """学过的配置，平均失败数必须低于从不学习的 baseline。"""
    sc = by_name("permanent_block_x5.0_northfirst")
    base = run_scenario(sc, config_by_name("planner_only"), 42)
    mem = run_scenario(sc, config_by_name("memory_only"), 42)
    ref = run_scenario(sc, config_by_name("memory_reflection"), 42)
    assert base.avg_failures == 1.0            # 每次都犯同一个错
    assert mem.avg_failures < base.avg_failures
    assert ref.avg_failures < base.avg_failures
    # 有证据门槛的那一臂要慢一步（min_hits=2），这就是"学得稳"的代价
    assert ref.avg_failures > mem.avg_failures


def test_reflection_only_equals_planner_only():
    """核心负结果：反思只写不读 ⇒ 与无反思完全一致。"""
    sc = by_name("permanent_block_x5.0_northfirst")
    a = run_scenario(sc, config_by_name("planner_only"), 42)
    b = run_scenario(sc, config_by_name("reflection_only"), 42)
    assert (a.avg_steps, a.avg_failures, a.avg_retries if hasattr(a, "avg_retries") else a.avg_replans) == \
           (b.avg_steps, b.avg_failures, b.avg_replans)


def test_memory_over_generalises_on_transient_failure():
    """过度泛化的代价：一次瞬时就永久绕远路（动作数变多）。"""
    sc = by_name("transient_jam_latency_none")
    mem = run_scenario(sc, config_by_name("memory_only"), 42)
    ref = run_scenario(sc, config_by_name("memory_reflection"), 42)
    assert mem.avg_steps > ref.avg_steps            # 记忆臂绕远路
    assert ref.avg_steps == run_scenario(
        sc, config_by_name("planner_only"), 42).avg_steps   # 反思臂没被一次偶发带跑


def test_unfixable_scenario_stays_unfixable_and_teaches_nothing_wrong():
    """低电量不是路线问题 —— 学不到"避开某条路"的教训，也就不该乱改路线。"""
    sc = by_name("battery_low_start")
    for cfg in CONFIGS:
        r = run_scenario(sc, config_by_name(cfg.name), 42)
        assert r.success_rate == 0.0
    persistent = AgentMemory()
    planner_store, reflector = make_agent_parts(config_by_name("memory_reflection"), persistent)
    from argos.agent.interfaces import Action, ActionKind, FailReason
    reflector.record_failure(trigger="route:north", reason=FailReason.BATTERY_LOW, detail="电量低")
    reflector.record_failure(trigger="route:north", reason=FailReason.BATTERY_LOW, detail="电量低")
    assert reflector.consolidate() == []          # 不生成路线教训


# ---------- 报告 ----------

def test_report_has_all_sections():
    sc = build_scenarios()[:2]
    results = run_matrix(scenarios=sc, seeds=(42,))
    text = render_markdown(results, (42,))
    for section in ("## 1. 各组配置对比", "## 2. 分场景", "## 3. 学习速度",
                    "## 4. 结论（由数据自动推导）", "## 已知限制与负结果"):
        assert section in text
    assert "| 配置 | 任务成功率 | 平均重试 | 平均动作数 | 平均完成耗时(s) | 平均失败数 |" in text
