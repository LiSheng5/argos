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

from argos.agent.memory_agent import AgentMemory, LessonStore
from argos.agent.reflection import Reflector

#: 路线之间的替代关系（Lesson 里 prefer 的来源）
ALTERNATIVES = {"north": "south", "south": "north"}


@dataclass(frozen=True)
class AgentConfig:
    name: str
    label: str
    persist: bool            # 记忆是否跨 episode 保留
    consume: bool            # Planner 是否读 **Procedural**（硬避开策略）
    min_hits: int
    min_confidence: float
    description: str
    revalidate_every: int = 0    # 每隔几个 episode 复核一次被避开的路线（0 = 不复核）
    #: 只用 **Semantic**（滑窗失败率 → 软降权），不消费 Procedural 硬策略。
    #: 用来回答"软降权能不能替代硬避开"。
    semantic_only: bool = False


CONFIGS: Tuple[AgentConfig, ...] = (
    AgentConfig("planner_only", "仅规划", persist=False, consume=False,
                min_hits=999, min_confidence=1.0,
                description="无记忆、无反思：每次从零开始，同样的错反复犯"),
    AgentConfig("semantic_only", "规划+语义记忆", persist=True, consume=False,
                min_hits=999, min_confidence=1.0, semantic_only=True,
                description="只用 Semantic 层的滑窗失败率做**软降权**（不升级为硬避开）——"
                            "回答「软降权能不能替代硬策略」"),
    AgentConfig("memory_only", "规划+记忆", persist=True, consume=True,
                min_hits=1, min_confidence=0.0,
                description="记忆即教训：一次失败就永久避开（学得快，也容易过度泛化）"),
    AgentConfig("reflection_only", "规划+反思(不读)", persist=True, consume=False,
                min_hits=2, min_confidence=0.6,
                description="反思只写不读（旧系统的病）——预期与仅规划持平，负结果臂"),
    AgentConfig("memory_reflection", "规划+记忆+反思", persist=True, consume=True,
                min_hits=2, min_confidence=0.6,
                description="完整闭环：够证据才形成教训，且教训真的被规划消费"),
    AgentConfig("memory_reflection_revalidate", "规划+记忆+反思+复核", persist=True,
                consume=True, min_hits=2, min_confidence=0.6, revalidate_every=2,
                description="在上一臂基础上，每 2 个 episode 主动复核一次被避开的路线 —— "
                            "治「环境已恢复、教训还在」的永久绕路"),
)


def config_by_name(name: str) -> AgentConfig:
    for c in CONFIGS:
        if c.name == name:
            return c
    raise KeyError(f"未知配置：{name}；可用：{[c.name for c in CONFIGS]}")


def make_reflector(cfg: AgentConfig, persistent: AgentMemory) -> Reflector:
    """**只建一次**（跨 episode）—— 反思器里的失败计数就是"够不够证据"的账本，
    每 episode 重建会把账清零，`min_hits=2` 永远凑不满（踩过）。"""
    reflector_store = persistent.procedural if cfg.persist else LessonStore()
    return Reflector(
        store=reflector_store,
        alternatives=dict(ALTERNATIVES),
        min_hits=cfg.min_hits,
        min_confidence=cfg.min_confidence,
        revalidate_every=cfg.revalidate_every,
    )


def make_memory(cfg: AgentConfig, persistent: AgentMemory) -> AgentMemory:
    """**每个 episode 取一次** —— 记忆要不要跨 episode 由配置决定，不能顺手共享。

    踩过的坑：把本函数和 `make_reflector` 合成一个、还在循环外调用，
    结果连 Semantic 窗口也跨 episode 共享了 —— `planner_only`（本该零记忆）
    居然也"学会了"绕开被挡的路，等于给无记忆臂偷偷开了软降权。
    """
    # Procedural（硬避开）：只有「跨 episode 保留 **且** planner 会读」才生效
    procedural = persistent.procedural if (cfg.persist and cfg.consume) else LessonStore()

    # Semantic（软降权）：跨 episode 保留，且（读硬策略 或 显式只开语义）才生效。
    # 共享同一个 windows 字典对象 → 窗口跨 episode 生效。
    use_semantic = cfg.persist and (cfg.consume or cfg.semantic_only)
    windows = persistent.windows if use_semantic else {}

    return AgentMemory(procedural=procedural, windows=windows,
                       window=persistent.window,
                       min_observations=persistent.min_observations,
                       min_failures=persistent.min_failures,
                       soft_threshold=persistent.soft_threshold)


def make_agent_parts(cfg: AgentConfig, persistent: AgentMemory):
    """兼容包装：`(memory, reflector)`。

    ⚠️ 只应在**单 episode** 场景用；跑多 episode 请显式用 `make_reflector`（循环外）
    + `make_memory`（循环内），否则会把记忆也共享出去。

    两个负结果臂的机制都在这里：

    * `reflection_only` —— 反思照写进 persistent，但 planner 读的是**每次新建的空 procedural**
      → "写了没人读"被真实复现；
    * `semantic_only` —— **窗口共享**（Semantic 持久生效），但 procedural 每次全新
      → 只剩软降权，没有硬策略。
    """
    return make_memory(cfg, persistent), make_reflector(cfg, persistent)
