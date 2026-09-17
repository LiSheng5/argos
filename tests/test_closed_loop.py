"""闭环测试（Phase 4，本轮最重要的一层）：

    Goal → Plan → Action → Failure → Reflection → Memory → Retrieval → **Different Plan**

钉的是指令第七、十六节要的那件事：**反思必须真的改变下一次计划**。
断言落到**坐标和路线名**上 —— 不接受"看起来像学到了"。
"""
import pytest

from argos.agent.brain import AgentBrain
from argos.agent.interfaces import FailReason, Pose
from argos.agent.memory_agent import LessonStore
from argos.agent.planner import Planner
from argos.agent.reflection import Reflector
from argos.backends.simulator_backend import SimulatorBackend

GOAL = "去充电站"


def _brain(store: LessonStore, reflector: Reflector, seed: int = 42):
    """每次都开一台**新的**仿真机器人（回到 Room A），但**记忆是同一份**。

    这才是"agent 带着上次的经验重新出发"，而不是"机器人本来就站在终点"。
    """
    backend = SimulatorBackend(seed=seed)
    planner = Planner(backend.world)
    return AgentBrain(backend, planner, reflector, store), backend


@pytest.fixture
def agent_pair():
    store = LessonStore()
    reflector = Reflector(store=store, alternatives={"north": "south", "south": "north"})
    return store, reflector


def test_first_attempt_hits_the_blocked_north_route(agent_pair):
    """第一次走北线 → 被 north_block 挡住 → 重规划到南线 → 最终到达。"""
    store, reflector = agent_pair
    brain, backend = _brain(store, reflector)
    r = brain.run(GOAL)

    assert r.ok is True
    assert r.failures >= 1
    assert r.replans >= 1
    assert any(t.reason == FailReason.OBSTACLE_BLOCKED.value for t in r.trace)
    assert (r.final_pose.x, r.final_pose.y) == (10.0, -2.0)   # 到了充电站（yaw 由转向决定，不断言）
    # 一次失败还不够形成教训（防一次偶发就永久绕行）
    assert store.active() == []


def test_second_failure_consolidates_into_a_lesson(agent_pair):
    """第二次再撞 → 累计够证据 → 产出结构化 Lesson（有 evidence、有置信度）。"""
    store, reflector = agent_pair
    _brain(store, reflector)[0].run(GOAL)          # 第一次
    r = _brain(store, reflector)[0].run(GOAL)      # 第二次

    lessons = store.active()
    assert len(lessons) == 1
    L = lessons[0]
    assert L.avoid == "north"
    assert L.prefer == "south"
    assert "north_block" in L.evidence             # 有真凭实据，不是编的
    assert 0.6 <= L.confidence <= 0.95             # 不假装绝对确定
    assert r.ok is True


def test_third_run_plans_a_different_route_from_the_start(agent_pair):
    """第三次：**从一开始就不走北线** —— 这才是"Memory 被 Planner 消费"的证据。"""
    store, reflector = agent_pair
    _brain(store, reflector)[0].run(GOAL)
    _brain(store, reflector)[0].run(GOAL)
    brain, backend = _brain(store, reflector)

    # 规划阶段就必须已经避开 north
    view0 = brain._view()
    plan = brain.planner.plan(GOAL, view0, store.active(), backend.capabilities())
    assert plan is not None
    assert plan.route == "south"

    r = brain.run(GOAL)
    assert r.ok is True
    assert r.failures == 0                          # 零失败到达
    assert r.replans == 0
    assert (r.final_pose.x, r.final_pose.y) == (10.0, -2.0)


def test_gate_rejection_is_not_learned_as_experience(agent_pair):
    """被闸拒不是世界的经验 —— 不许污染换线逻辑。"""
    store, reflector = agent_pair
    brain, backend = _brain(store, reflector)
    backend.estop(True)                             # 急停 → 闸拒绝
    r = brain.run(GOAL)

    assert r.ok is False
    assert r.failures == 0                          # 不算"真实失败"
    assert store.all() == []                        # 不产生任何 Lesson
    assert "安全闸" in r.stop_reason


def test_trace_is_complete_and_exportable(agent_pair):
    """可解释：每一步 goal/action/ok/reason 都在，能导出成行（Phase 8 的 trace 就用它）。"""
    store, reflector = agent_pair
    brain, _ = _brain(store, reflector)
    r = brain.run(GOAL)

    assert len(r.trace) == r.steps
    rows = r.as_rows()
    assert rows and all({"step", "action", "ok", "reason"} <= set(x) for x in rows)
    assert any(not x["ok"] for x in rows)           # 确实记录到了失败那一步


def test_unknown_goal_is_reported_honestly(agent_pair):
    """听不懂就直说，不硬编一条路线。"""
    store, reflector = agent_pair
    brain, _ = _brain(store, reflector)
    r = brain.run("去火星")
    assert r.ok is False
    assert "无法理解" in r.stop_reason
    assert r.steps == 0
