"""四组 Agent 配置（Phase 7）—— 指令第八节要求的那张对比表就是它们之间的比较。

| 配置 | 记忆跨 episode | Planner 读 Lesson | 反思门槛 | 预期 |
|---|---|---|---|---|
| `planner_only`     | ✗ | ✗ | — | 能完成，但**每次都犯同一个错** |
| `memory_only`      | ✓ | ✓ | min_hits=1，无置信度门槛 | 学得快，但**一次偶发就永久绕行**（过度泛化）|
| `reflection_only`  | ✓ | ✗ | min_hits=2 | **反思只写不读**（旧系统的病）→ 应与 planner_only 相同，属预期负结果 |
| `memory_reflection`| ✓ | ✓ | min_hits=2 + confidence≥0.6 | 完整闭环，期望"学得稳" |

⚠️ `reflection_only` 是**故意留的负结果臂**：如果它和 `memory_reflection` 打平，
说明"反思"这件事本身没有价值 —— 那就必须如实写在报告里。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from argos.agent.memory_agent import LessonStore
from argos.agent.reflection import Reflector

#: 路线之间的替代关系（Lesson 里 prefer 的来源）
ALTERNATIVES = {"north": "south", "south": "north"}


@dataclass(frozen=True)
class AgentConfig:
    name: str
    label: str
    persist: bool            # 记忆是否跨 episode 保留
    consume: bool            # Planner 是否读 Lesson
    min_hits: int
    min_confidence: float
    description: str


CONFIGS: Tuple[AgentConfig, ...] = (
    AgentConfig("planner_only", "仅规划", persist=False, consume=False,
                min_hits=999, min_confidence=1.0,
                description="无记忆、无反思：每次从零开始，同样的错反复犯"),
    AgentConfig("memory_only", "规划+记忆", persist=True, consume=True,
                min_hits=1, min_confidence=0.0,
                description="记忆即教训：一次失败就永久避开（学得快，也容易过度泛化）"),
    AgentConfig("reflection_only", "规划+反思(不读)", persist=True, consume=False,
                min_hits=2, min_confidence=0.6,
                description="反思只写不读（旧系统的病）——预期与仅规划持平，负结果臂"),
    AgentConfig("memory_reflection", "规划+记忆+反思", persist=True, consume=True,
                min_hits=2, min_confidence=0.6,
                description="完整闭环：够证据才形成教训，且教训真的被规划消费"),
)


def config_by_name(name: str) -> AgentConfig:
    for c in CONFIGS:
        if c.name == name:
            return c
    raise KeyError(f"未知配置：{name}；可用：{[c.name for c in CONFIGS]}")


def make_agent_parts(cfg: AgentConfig, persistent: LessonStore):
    """按配置组装 `(planner 读的 store, reflector)`。

    `reflection_only` 的关键：反思写进 persistent，但 planner 读的是**每次新建的空 store**
    —— 于是"写了没人读"这件事被真实复现出来。
    """
    planner_store = persistent if (cfg.persist and cfg.consume) else LessonStore()
    reflector_store = persistent if cfg.persist else planner_store
    reflector = Reflector(
        store=reflector_store,
        alternatives=dict(ALTERNATIVES),
        min_hits=cfg.min_hits,
        min_confidence=cfg.min_confidence,
    )
    return planner_store, reflector
