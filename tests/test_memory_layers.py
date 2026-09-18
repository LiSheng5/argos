"""记忆三层测试（Wave 2 / 指令 §9）。

钉的是三件事：
  1. **Episodic** 记原始事件，且**成败都记**（没有分母就算不出失败率）；
  2. **Semantic** 用**滑窗**统计（旧证据会自然淡出），且**观测数不够不许影响决策**；
  3. **Procedural** 是硬策略（可被反证失效），与 Semantic 的软降权**语义不同**。
"""
import pytest

from argos.agent.brain import AgentBrain
from argos.agent.memory_agent import (
    AgentMemory,
    EpisodeEvent,
    MemoryKind,
    RouteStats,
)
from argos.agent.planner import Planner
from argos.agent.reflection import Reflector
from argos.backends.simulator_backend import SimulatorBackend


def _event(ep, route, ok, **kw):
    return EpisodeEvent(episode=ep, goal="去充电站", route=route,
                        route_ok=ok, episode_ok=ok, **kw)


# ---------- Episodic ----------

def test_episodic_records_both_success_and_failure():
    """成功也要记 —— 否则"走 1 次失败 1 次"和"走 5 次失败 1 次"分不清。"""
    m = AgentMemory()
    m.record_episode(_event(0, "north", ok=False, reason="obstacle_blocked"))
    m.record_episode(_event(1, "north", ok=True))
    assert len(m.episodic) == 2
    assert [e.route_ok for e in m.episodic] == [False, True]
    assert m.episodic[0].kind is MemoryKind.EPISODIC
    assert "obstacle_blocked" in m.describe()["episodic"][0]


def test_route_ok_and_episode_ok_are_different_things():
    """走 north 被挡、换 south 到达：route_ok=False（north 确实有问题）但 episode_ok=True。"""
    m = AgentMemory()
    m.record_episode(EpisodeEvent(episode=0, goal="g", route="north",
                                  route_ok=False, episode_ok=True, failures=1))
    assert m.windows["north"] == [False]          # 统计用的是 route_ok
    assert m.episodic[0].episode_ok is True


def test_episode_without_route_is_not_counted_in_windows():
    m = AgentMemory()
    m.record_episode(EpisodeEvent(episode=0, goal="g", route=None,
                                  route_ok=False, episode_ok=False))
    assert m.windows == {}
    assert len(m.episodic) == 1


# ---------- Semantic（滑窗）----------

def test_semantic_window_forgets_old_evidence():
    """滑窗：只保留最近 window 次 —— 这就是"记忆会淡出"。"""
    m = AgentMemory(window=3)
    for i in range(5):
        m.record_episode(_event(i, "north", ok=False))
    m.record_episode(_event(5, "north", ok=True))
    st = m.semantic()[0]
    assert st.attempts == 3                        # 只留最近 3 次
    assert st.failures == 2                        # 最旧那两次失败已被挤出去
    assert st.kind is MemoryKind.SEMANTIC
    assert "最近 3 次" in st.describe()


def test_soft_penalty_requires_min_observations():
    """**一次失败不许改道** —— 这正是我们要避免的"把偶发当规律"。"""
    m = AgentMemory(min_observations=2)
    m.record_episode(_event(0, "north", ok=False))
    assert m.soft_penalty() == {}                  # 只观测到 1 次 → 不降权
    m.record_episode(_event(1, "north", ok=False))
    assert m.soft_penalty() == {"north": 1.0}      # 2 次都失败 → 降权


def test_one_failure_out_of_two_is_not_enough_to_change_route():
    """`[失败, 成功]` 不许降权 —— 失败次数门槛（=2）就是为了挡这种情况。

    实测踩到过：少了这道门槛，一次瞬时故障之后（窗口变成 [失败, 成功]）
    软降权立刻生效，agent 从此绕远路 —— 又变回了"把偶发当规律"。
    """
    m = AgentMemory(window=3, min_observations=2, min_failures=2)
    m.record_episode(_event(0, "north", ok=False))
    m.record_episode(_event(1, "north", ok=True))
    assert m.soft_penalty() == {}                  # 失败率 0.5，但只失败过 1 次 → 不降权
    m.record_episode(_event(2, "north", ok=False))
    # 窗口 [失败,成功,失败]：失败 2 次、失败率 2/3 → 两条门槛都过了，才降权
    assert m.soft_penalty() == {"north": pytest.approx(2 / 3)}


def test_soft_penalty_requires_failure_rate_threshold():
    """阈值语义是「达到即降权」（>=）。"""
    m = AgentMemory(min_observations=2, soft_threshold=0.6)
    m.record_episode(_event(0, "north", ok=False))
    m.record_episode(_event(1, "north", ok=True))
    assert m.soft_penalty() == {}                  # 失败率 0.5 < 0.6 → 不降权
    m.record_episode(_event(2, "north", ok=False))
    assert m.soft_penalty() == {"north": pytest.approx(2 / 3)}   # 2/3 ≥ 0.6 → 降权


def test_soft_penalty_only_reorders_never_eliminates():
    """软降权只改**先后顺序**，不淘汰候选 —— 这是它能"回头"的原因。"""
    be = SimulatorBackend(seed=1)
    p = Planner(be.world)                          # routes: north(先) / south
    from argos.world.state import from_observation, view
    v = view(from_observation(be.observe()))

    assert p.choose_route([], soft_penalty=None) == "north"
    assert p.choose_route([], soft_penalty={"north": 1.0}) == "south"
    # 两条都被降权时仍有候选可选（不会像硬避开那样返回 None）
    assert p.choose_route([], soft_penalty={"north": 1.0, "south": 1.0}) == "north"


def test_procedural_is_hard_and_semantic_is_soft():
    """语义不同：Procedural 会让候选**消失**，Semantic 只让它**排后面**。"""
    from argos.agent.interfaces import Lesson
    from argos.world.state import from_observation, view
    be = SimulatorBackend(seed=1)
    p = Planner(be.world)
    lesson = Lesson(id="l", trigger="route:north", avoid="north", prefer="south",
                    evidence="e", confidence=0.9, hits=3)
    assert p.choose_route([lesson]) == "south"
    assert p.choose_route([lesson], soft_penalty={"south": 1.0}) == "south"   # 硬避开优先
    assert p.choose_route([], soft_penalty={"south": 1.0}) == "north"        # 软的会回头


# ---------- 端到端：三层一起用 ----------

def _brain(memory, reflector, seed=42):
    be = SimulatorBackend(seed=seed)
    return AgentBrain(be, Planner(be.world), reflector, memory=memory), be


def test_end_to_end_memory_fills_all_three_layers():
    memory = AgentMemory()
    reflector = Reflector(store=memory.procedural,
                          alternatives={"north": "south", "south": "north"})
    for _ in range(3):
        brain, _ = _brain(memory, reflector)
        brain.run("去充电站")

    snap = memory.describe()
    assert snap["episodic"]                              # 有原始事件
    assert snap["semantic"]                              # 有滑窗规律
    assert snap["procedural"]                            # 有硬策略
    assert any("north" in s for s in snap["semantic"])
    assert memory.procedural.active()


def test_memory_clear_resets_all_layers():
    memory = AgentMemory()
    memory.record_episode(_event(0, "north", ok=False))
    memory.clear()
    assert memory.episodic == [] and memory.windows == {}
    assert memory.procedural.all() == []
