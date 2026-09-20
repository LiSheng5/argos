"""教训复核测试 —— 治「一次偶发被当成永久教训，从此绕远路」。

三道防线各钉一层：
  1. **独立证据**：同一次 episode 内的重复失败只算 1 条（否则连撞两次就"学"了）；
  2. **周期复核**：被避开的路线要定期主动试探，不能永久绕路；
  3. **反证削弱**：试探成功后教训降级直至撤销，不是只增不减。
"""
import pytest

from argos.agent.brain import AgentBrain
from argos.agent.interfaces import Action, ActionKind, FailReason, Lesson, Pose
from argos.agent.memory_agent import LessonStore
from argos.agent.planner import Planner
from argos.agent.reflection import Reflector
from argos.backends.simulator_backend import SimulatorBackend
from argos.benchmark.configs import config_by_name
from argos.benchmark.runner import run_scenario
from argos.benchmark.scenarios import by_name
from argos.world.state import from_observation, view
from argos.agent.interfaces import Observation


# ---------- 1. 证据独立性 ----------

def test_repeated_failure_in_one_episode_counts_once():
    """一次运行时连撞两次 ≠ 两次独立尝试 —— 否则 min_hits=2 形同虚设。"""
    r = Reflector(min_hits=2, alternatives={"north": "south"})
    r.begin_episode()
    assert r.record_failure(trigger="route:north", reason=FailReason.OBSTACLE_BLOCKED) == 1
    assert r.record_failure(trigger="route:north", reason=FailReason.OBSTACLE_BLOCKED) == 1
    assert r.consolidate() == []                    # 还不够，不该生成教训

    r.begin_episode()                               # 下一次独立尝试
    assert r.record_failure(trigger="route:north", reason=FailReason.OBSTACLE_BLOCKED) == 2
    assert len(r.consolidate()) == 1


def test_different_episodes_do_accumulate():
    r = Reflector(min_hits=2, alternatives={"north": "south"})
    for _ in range(2):
        r.begin_episode()
        r.record_failure(trigger="route:north", reason=FailReason.OBSTACLE_BLOCKED)
    assert len(r.consolidate()) == 1


# ---------- 2. 周期复核 ----------

def test_revalidate_schedule():
    r = Reflector(revalidate_every=2)
    assert r.should_revalidate() is False           # episode 0，还没 begin
    r.begin_episode(); assert r.should_revalidate() is False   # 1
    r.begin_episode(); assert r.should_revalidate() is True    # 2
    r.begin_episode(); assert r.should_revalidate() is False   # 3
    r.begin_episode(); assert r.should_revalidate() is True    # 4


def test_no_revalidation_by_default():
    """回归锚：默认不复核，行为与从前逐字一致。"""
    r = Reflector()
    for _ in range(10):
        r.begin_episode()
        assert r.should_revalidate() is False


def test_probe_plan_targets_the_avoided_route():
    """复核 = 明知有教训，仍故意走那条路。"""
    backend = SimulatorBackend(seed=1)
    planner = Planner(backend.world)
    lesson = Lesson(id="l", trigger="route:north", avoid="north", prefer="south",
                    evidence="e", confidence=0.9, hits=3)
    v = view(from_observation(backend.observe()))

    normal = planner.plan("去充电站", v, [lesson], backend.capabilities())
    assert normal.route == "south" and normal.is_probe is False

    probe = planner.plan("去充电站", v, [lesson], backend.capabilities(), probe=True)
    assert probe.route == "north" and probe.is_probe is True


# ---------- 3. 反证削弱 ----------

def test_weaken_lowers_confidence_then_invalidates_without_deleting():
    """反证：先降级，归零后**标记失效**——而不是删掉（要留审计轨迹）。"""
    store = LessonStore()
    store.add(Lesson(id="l", trigger="route:north", avoid="north", prefer="south",
                     evidence="e", confidence=0.67, hits=2))
    l1 = store.weaken("north", episode=3)
    assert l1.hits == 1 and l1.status == "active"
    assert l1.confidence < 0.67
    assert "反证" in l1.evidence

    l2 = store.weaken("north", episode=4)
    assert l2 is not None
    assert l2.status == "invalidated"          # 失效，但**还在库里**
    assert store.all() != []
    assert store.active() == []                # 不再参与规划
    assert [l.id for l in store.invalidated()] == ["l"]
    assert "counter_evidence@ep4" in l2.history

    # 已经失效的条目不会被反复削弱
    assert store.weaken("north") is None


def test_invalidated_lesson_can_be_reinstated_with_fresh_evidence():
    """环境又变回去了 → 失效的教训可以复活（失效 ≠ 永久作废）。"""
    store = LessonStore()
    store.add(Lesson(id="l", trigger="route:north", avoid="north", prefer="south",
                     evidence="e", confidence=0.67, hits=2), episode=1)
    store.weaken("north", episode=2)
    store.weaken("north", episode=3)
    assert store.get("l").status == "invalidated"

    again = Lesson(id="l", trigger="route:north", avoid="north", prefer="south",
                   evidence="e2", confidence=0.67, hits=2)
    back = store.add(again, episode=9)
    assert back.status == "active"
    assert "reinstate@ep9" in back.history
    assert back.created_episode == 1 and back.updated_episode == 9


def test_history_records_support_events():
    store = LessonStore()
    store.add(Lesson(id="l", trigger="route:north", avoid="north", prefer="south",
                     evidence="e", confidence=0.5, hits=1), episode=1)
    l = store.add(Lesson(id="l", trigger="route:north", avoid="north", prefer="south",
                         evidence="e", confidence=0.67, hits=2), episode=2)
    assert l.history == ("support@ep1", "support@ep2")
    assert l.hits == 2


def test_weaken_unknown_route_is_noop():
    store = LessonStore()
    assert store.weaken("不存在的路线") is None


def test_record_success_weakens_by_route_name():
    """反证要**连续两次**成功复核（D-02）—— 一次成功只是累计证据，不动教训。"""
    r = Reflector(store=LessonStore())
    r.store.add(Lesson(id="l", trigger="route:north", avoid="north", prefer="south",
                       evidence="e", confidence=0.67, hits=2))
    # 第 1 次成功：只记账，不削弱
    assert r.record_success("route:north") is None
    assert r.store.get("l").hits == 2
    assert r.store.get("l").status == "active"
    assert r.probe_streak("north") == 1
    # 第 2 次连续成功：才真的降级
    assert r.record_success("route:north") is not None
    assert r.store.get("l").hits == 1
    assert r.probe_streak("north") == 0          # 用掉之后清零，下次要重新数两次


def test_probe_success_streak_resets_after_route_failure():
    """中途该路线又失败 → 连续成功计数清零，必须重新连续两次。"""
    r = Reflector(store=LessonStore(), min_hits=2,
                  alternatives={"north": "south"})
    r.store.add(Lesson(id="l", trigger="route:north", avoid="north", prefer="south",
                       evidence="e", confidence=0.67, hits=2))
    assert r.record_success("route:north") is None
    assert r.record_failure(trigger="route:north",
                            reason=FailReason.OBSTACLE_BLOCKED) == 1
    assert r.probe_streak("north") == 0
    assert r.store.get("l").hits == 2            # 教训没被削弱
    # 一次新的成功不足以推翻；必须重新连续两次成功。
    assert r.record_success("route:north") is None
    assert r.record_success("route:north") is not None
    assert r.store.get("l").hits == 1


def test_non_route_failure_does_not_reset_probe_streak():
    """非路线类失败（低电量/定位漂移…）不该断掉"这条路通了"的连续成功计数。"""
    r = Reflector(store=LessonStore(), min_hits=2)
    r.store.add(Lesson(id="l", trigger="route:north", avoid="north", prefer="south",
                       evidence="e", confidence=0.67, hits=2))
    assert r.record_success("route:north") is None
    assert r.record_failure(trigger="route:north", reason=FailReason.BATTERY_LOW) == 0
    assert r.probe_streak("north") == 1
    assert r.record_success("route:north") is not None


def _open_world():
    """默认世界的路线拓扑，但**把障碍拿掉** —— 北线是通的。

    直接用 `SimulatorBackend(seed=42)` 会带上默认世界里的 `north_block`
    （那是 demo 的失败源），于是"探针成功"根本构造不出来。
    """
    from argos.world.mini_world import MiniWorld, build_default_world
    base = build_default_world()
    return MiniWorld(name="probe_open", rooms=base.rooms, obstacles=(),
                     locations=base.locations, routes=base.routes, bounds=base.bounds)


def _probe_setup(hits: int, revalidate_every: int):
    """造一个"有教训 + 又有旧滑窗"的局面，用来验探针成功之后的接线。

    返回 `(store, memory, brain)`。滑窗先塞两次失败 → `soft_penalty()` 一定对 north 生效。
    """
    from argos.agent.memory_agent import AgentMemory, EpisodeEvent
    from argos.agent.planner import Planner
    from argos.backends.simulator_backend import SimulatorBackend

    store = LessonStore()
    store.add(Lesson(id="l", trigger="route:north", avoid="north", prefer="south",
                     evidence="e", confidence=0.9, hits=hits), episode=1)
    memory = AgentMemory(procedural=store)
    for i in range(2):
        memory.record_episode(EpisodeEvent(episode=i, goal="g", route="north",
                                           route_ok=False, episode_ok=False))
    reflector = Reflector(store=store, revalidate_every=revalidate_every,
                          alternatives={"north": "south", "south": "north"})
    be = SimulatorBackend(world=_open_world(), seed=42)
    return store, memory, AgentBrain(be, Planner(be.world), reflector, memory=memory)


def test_first_probe_success_does_not_clear_the_semantic_window():
    """**D-02 的接线钉**：只有反证成立（教训真被削弱）才允许清该路线的 Semantic 滑窗。

    第一次成功若就把滑窗清了，两层会打架：Procedural 还压着这条路（教训还在），
    Semantic 却已不再对它降权 —— 下一步 agent 又走回被避开的路。
    """
    store, memory, brain = _probe_setup(hits=3, revalidate_every=1)
    assert memory.soft_penalty() == {"north": 1.0}

    r1 = brain.run("去充电站")
    assert r1.trace and r1.trace[0].route == "north" and r1.ok and r1.failures == 0
    # 第 1 次探针成功 → 教训没动，滑窗也没清
    assert store.get("l").hits == 3
    assert memory.windows.get("north") is not None

    r2 = brain.run("去充电站")
    assert r2.trace[0].route == "north" and r2.failures == 0
    # 第 2 次连续成功 → 教训被削弱（hits 3→2）+ 滑窗被重置
    assert store.get("l").hits == 2
    assert memory.windows.get("north") in (None, [True])
    assert memory.soft_penalty() == {}


# ---------- 4. 端到端：复核确实省了动作 ----------

def test_revalidation_cuts_the_detour_cost_end_to_end():
    """靶场景：北线连撞两次后恢复。不复核的 agent 会永久绕远路。"""
    sc = by_name("two_strikes_then_clear_none")
    frozen = run_scenario(sc, config_by_name("memory_reflection"), 42)
    rev = run_scenario(sc, config_by_name("memory_reflection_revalidate"), 42)

    assert frozen.success_rate == 1.0 and rev.success_rate == 1.0
    assert rev.avg_steps < frozen.avg_steps          # 复核把绕路成本压下来了
    # 复核之后应该回到北线（最优），而不是一直绕
    assert rev.episodes[-1].route == "north"
    assert frozen.episodes[-1].route == "south"      # 不复核则一直绕
    # 复核回来的那一次是**零失败**的最优路径（不是"回到北线又被挡一次"）
    assert any(e.route == "north" and e.failures == 0 for e in rev.episodes[2:])


def test_probe_success_clears_the_semantic_window():
    """反证**成立**之后 → 该路线的滑窗重置，两层不再打架。

    不这样做会出现两层打架：Procedural 已被反证撤销，Semantic 的滑窗却还压着这条路，
    结果探针明明验通了、agent 下一步又绕回远路（实测踩到过）。

    ⚠️ 这条测试原先**是空断言**（`if r.trace and r.trace[0].route == "north":`）——
    而当时默认世界带 `north_block`、软降权又把 south 排到前面，
    条件恒为假 → 断言根本没跑过。现在换成"无障碍世界 + 每轮探针"，是真在验。
    """
    store, memory, brain = _probe_setup(hits=2, revalidate_every=1)
    assert memory.soft_penalty() == {"north": 1.0}

    r1 = brain.run("去充电站")
    assert r1.trace[0].route == "north" and r1.ok and r1.failures == 0
    assert store.get("l").hits == 2                      # 第 1 次成功不削弱
    assert memory.windows.get("north") is not None       # 滑窗也不清

    r2 = brain.run("去充电站")
    assert r2.trace[0].route == "north" and r2.failures == 0
    # 反证成立：hits 2→1 → confidence 0.5 < 0.6 → 退出「生效中」= 不再硬避开
    assert store.get("l").status == "active"             # 没被删，只是不再生效
    assert store.active() == []
    assert memory.windows.get("north") in (None, [True])  # 滑窗已重置
    assert memory.soft_penalty() == {}

    # 撤干净之后，下一步自然就走北线（不必再靠探针）
    r3 = brain.run("去充电站")
    assert r3.trace[0].route == "north" and r3.ok


def test_revalidation_costs_at_most_one_probe_failure():
    """复核不是白捡的：试探那一次可能失败，但代价要有上限。"""
    sc = by_name("two_strikes_then_clear_none")
    frozen = run_scenario(sc, config_by_name("memory_reflection"), 42)
    rev = run_scenario(sc, config_by_name("memory_reflection_revalidate"), 42)
    assert rev.avg_failures <= frozen.avg_failures + 1


# ---------- 5. 故障必须绑在位置上 ----------

def test_injected_failure_can_be_scoped_to_a_location():
    """回归钉：故障属于世界的位置，不是"agent 当时选的那条路"。

    早期版本不绑位置：agent 改走绕路时被挡 → 把绕路也记成不能走 → 两条路全禁、无路可走。
    """
    from argos.sim.failure_injector import FailureInjector
    import random

    inj = FailureInjector(rng=random.Random(0))
    inj.arm(FailReason.OBSTACLE_BLOCKED, once=False,
            where=lambda a, w: float((a.params or {}).get("y", -99.0)) >= 1.0)

    north = Action(ActionKind.MOVE, {"x": 5.0, "y": 2.0})
    south = Action(ActionKind.MOVE, {"x": 5.0, "y": -2.0})
    assert inj.maybe_inject(north, None) is FailReason.OBSTACLE_BLOCKED
    assert inj.maybe_inject(south, None) is None      # 绕路不该被连坐
