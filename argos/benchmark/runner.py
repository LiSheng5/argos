"""Benchmark 执行器（Phase 7）。

**同一场景 + 同一 seed** 下跑四组配置，采集指令要求的五个指标：
  任务成功率 / 规划重试次数 / 动作数 / 完成耗时 / 失败次数。

"一个 episode" = agent 带着当前记忆去执行一次任务；
episode 之间**共享记忆**（这才叫"学过之后再来一次"）。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from argos.agent.brain import AgentBrain
from argos.agent.interfaces import FailReason
from argos.agent.memory_agent import LessonStore
from argos.agent.planner import Planner
from argos.benchmark.configs import CONFIGS, AgentConfig, make_agent_parts
from argos.benchmark.scenarios import Scenario, build_scenarios
from argos.sim.failure_injector import FailureInjector
from argos.sim.latency import get_profile
from argos.sim.mini_entity import MiniEntity
from argos.backends.simulator_backend import SimulatorBackend

__all__ = ["EpisodeResult", "ScenarioResult", "run_scenario", "run_matrix", "DEFAULT_SEEDS"]

DEFAULT_SEEDS = (42, 7, 2026)


@dataclass
class EpisodeResult:
    index: int
    ok: bool
    steps: int
    failures: int
    replans: int
    sim_time: float
    route: str


@dataclass
class ScenarioResult:
    scenario: str
    kind: str
    config: str
    seed: int
    episodes: List[EpisodeResult] = field(default_factory=list)

    # ---- 指标 ----
    @property
    def success_rate(self) -> float:
        return sum(1 for e in self.episodes if e.ok) / max(1, len(self.episodes))

    @property
    def avg_steps(self) -> float:
        return _mean([e.steps for e in self.episodes])

    @property
    def avg_failures(self) -> float:
        return _mean([e.failures for e in self.episodes])

    @property
    def avg_replans(self) -> float:
        return _mean([e.replans for e in self.episodes])

    @property
    def avg_time(self) -> float:
        return _mean([e.sim_time for e in self.episodes])

    @property
    def episodes_to_zero_failure(self) -> Optional[int]:
        """第几个 episode 开始不再失败（学得多快）。一直失败 → None。"""
        for e in self.episodes:
            if e.failures == 0:
                return e.index
        return None


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def run_scenario(scenario: Scenario, cfg: AgentConfig, seed: int) -> ScenarioResult:
    """在给定场景+seed 下，用某配置连续跑 `scenario.episodes` 次（记忆共享）。"""
    persistent = LessonStore()
    out = ScenarioResult(scenario=scenario.name, kind=scenario.kind,
                         config=cfg.name, seed=seed)

    # ⚠️ `(store, reflector)` 必须**在 episode 循环外只建一次**：
    #    Reflector 的失败计数就是"够不够证据"的账本，每 episode 重建会把账清零，
    #    于是 min_hits=2 的配置永远凑不满 → 会得出"反思毫无作用"的**假负结论**（踩过）。
    planner_store, reflector = make_agent_parts(cfg, persistent)

    for i in range(scenario.episodes):
        world = scenario.world()
        injector = FailureInjector(rng=random.Random(seed * 1000 + i))
        if scenario.transient_once and i == 0:
            injector.arm(FailReason.OBSTACLE_BLOCKED, once=True)
        latency = get_profile(scenario.latency) if scenario.latency else None
        entity = MiniEntity(world, battery=scenario.start_battery)
        backend = SimulatorBackend(world=world, entity=entity, injector=injector,
                                   latency=latency, seed=seed)
        planner = Planner(world)
        brain = AgentBrain(backend, planner, reflector, planner_store, max_retry=2,
                           lesson_threshold=cfg.min_confidence)

        r = brain.run(scenario.goal)
        out.episodes.append(EpisodeResult(
            index=i, ok=r.ok, steps=r.steps, failures=r.failures,
            replans=r.replans, sim_time=backend.state.sim_time,
            route=(r.trace[0].route if r.trace and r.trace[0].route else ""),
        ))
    return out


def run_matrix(
    scenarios: Optional[Sequence[Scenario]] = None,
    configs: Optional[Sequence[AgentConfig]] = None,
    seeds: Sequence[int] = DEFAULT_SEEDS,
) -> List[ScenarioResult]:
    """全矩阵：场景 × 配置 × seed。顺序固定 → 结果可复现。"""
    scenarios = scenarios or build_scenarios()
    configs = configs or CONFIGS
    results: List[ScenarioResult] = []
    for sc in scenarios:
        for cfg in configs:
            for seed in seeds:
                results.append(run_scenario(sc, cfg, seed))
    return results


def by_config(results: Sequence[ScenarioResult]) -> Dict[str, List[ScenarioResult]]:
    out: Dict[str, List[ScenarioResult]] = {}
    for r in results:
        out.setdefault(r.config, []).append(r)
    return out


def summarize(results: Sequence[ScenarioResult]) -> Dict[str, Dict[str, float]]:
    """按配置聚合五个指标（跨全部场景与 seed）。"""
    table: Dict[str, Dict[str, float]] = {}
    for name, rs in by_config(results).items():
        table[name] = {
            "success_rate": _mean([r.success_rate for r in rs]),
            "avg_retries": _mean([r.avg_replans for r in rs]),
            "avg_actions": _mean([r.avg_steps for r in rs]),
            "avg_time_s": _mean([r.avg_time for r in rs]),
            "avg_failures": _mean([r.avg_failures for r in rs]),
            "learned_fast": _mean([
                1.0 if (r.episodes_to_zero_failure not in (None, 0)) else 0.0 for r in rs
            ]),
        }
    return table
