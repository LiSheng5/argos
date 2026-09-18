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
    r = Reflector(store=LessonStore())
    r.store.add(Lesson(id="l", trigger="route:north", avoid="north", prefer="south",
                       evidence="e", confidence=0.67, hits=2))
    assert r.record_success("route:north") is not None
    assert r.store.get("l").hits == 1


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
