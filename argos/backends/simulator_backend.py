"""SimulatorBackend —— 现在的**主运行后端**，不是"临时替代品"（Phase 1）。

⚠️ **这是仿真器，不是真机。** 不接任何硬件、不声称接入硬件。

它把三样东西缝在一起：
    MiniWorld（几何） + MiniEntity（机器人） + ActionGate（闸）
并对外只暴露 `EmbodimentBackend` 协议的四个方法。

未来接真机时：新增 `argos/backends/go2_backend.py` 实现同一协议，
**Brain / Planner / Memory / Reflector 一行不用改** —— 这就是"换身体不改大脑"。
"""
from __future__ import annotations

import random
from typing import Optional

from argos.agent.gate import ActionGate
from argos.agent.interfaces import (
    Action,
    ActionKind,
    ActionResult,
    EmbodimentCapabilities,
    FailReason,
    Observation,
    Pose,
    WorldState,
)
from argos.sim.failure_injector import FailureInjector
from argos.sim.mini_entity import MiniEntity
from argos.world.mini_world import MiniWorld, build_default_world
from argos.world.state import bump, view

__all__ = ["SimulatorBackend", "build_simulator"]


class SimulatorBackend:
    """唯一的写世界者：`apply()` 内部改 WorldState，外界只能读 `observe()`。"""

    def __init__(
        self,
        world: Optional[MiniWorld] = None,
        entity: Optional[MiniEntity] = None,
        gate: Optional[ActionGate] = None,
        injector: Optional[FailureInjector] = None,
        seed: Optional[int] = None,
        start_at: Optional[str] = "room_a",
    ) -> None:
        self.world = world or build_default_world()
        self.rng = random.Random(seed)
        self.seed = seed

        start_pose = (self.world.location(start_at) if start_at else None) or Pose()
        self.entity = entity or MiniEntity(self.world, pose=start_pose)

        self.caps = EmbodimentCapabilities(
            actions=(ActionKind.MOVE, ActionKind.TURN, ActionKind.STOP,
                     ActionKind.WAIT, ActionKind.INSPECT)
            + ((ActionKind.GRAB, ActionKind.RELEASE) if self.entity.has_arm else ()),
            has_arm=self.entity.has_arm,
            max_speed=self.entity.speed,
            can_localize=True,
        )
        self.gate = gate or ActionGate(self.caps)
        self.injector = injector or FailureInjector(rng=self.rng)
        self.steps = 0
        self.state = WorldState(
            robot=self.entity.pose,
            battery=self.entity.battery,
            obstacles={o.name: o for o in self.world.obstacles},
            objects={},
            locations={k: v for k, v in self.world.locations},
            people={},
            events=[],
            tasks=[],
            sim_time=0.0,
            version=0,
        )

    # ---- 协议 ----
    def capabilities(self) -> EmbodimentCapabilities:
        return self.caps

    def observe(self) -> Observation:
        """只读投影：把当前 WorldState 变成 Brain 能看的 Observation。"""
        v = view(self.state)
        return Observation(
            robot_pose=v.robot,
            battery=v.battery,
            obstacles=tuple(x[1] for x in v.obstacles),
            objects=tuple(x[1] for x in v.objects),
            locations=v.locations,
            people=tuple(x[1] for x in v.people),
            events=v.events,
            tasks=v.tasks,
            sim_time=v.sim_time,
            version=v.version,
        )

    def apply(self, action: Action) -> ActionResult:
        """唯一动作出口：**闸门 → 失败注入 → 执行器 → 写世界**。"""
        self.steps += 1
        before = self.entity.pose

        # 1) 闸（不可绕过）
        ok, reason, detail = self.gate.check(action, self.state)
        if not ok:
            return self._record(ActionResult(
                ok=False, reason=reason, detail=detail,
                pose_before=before, pose_after=before, sim_time=self.state.sim_time,
            ))

        # 2) 主动失败注入（研究用）
        inj = self.injector.maybe_inject(action, self.state)
        if inj is not None:
            return self._record(ActionResult(
                ok=False, reason=inj, detail="注入的失败（实验用，非真实故障）",
                pose_before=before, pose_after=before, sim_time=self.state.sim_time,
            ))

        # 3) 真的执行
        res = self.entity.apply(action)

        # 4) 只有这里能写世界
        self._sync(res)
        return self._record(res)

    def estop(self, on: bool = True) -> None:
        self.gate.set_estop(on)

    # ---- 内部 ----
    def _sync(self, res: ActionResult) -> None:
        bump(self.state,
             robot=self.entity.pose,
             battery=self.entity.battery,
             sim_time=self.entity.sim_time)
        if not res.ok:
            self.state.events.append(f"{res.reason.value}: {res.detail}")

    def _record(self, res: ActionResult) -> ActionResult:
        return res


def build_simulator(seed: int = 42, **kw) -> SimulatorBackend:
    """便捷构造：固定 seed（默认 42），保证同 seed 可复现。"""
    return SimulatorBackend(seed=seed, **kw)
