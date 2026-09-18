"""SimulatorBackend —— 现在的**主运行后端**，不是"临时替代品"（Phase 1）。

⚠️ **这是仿真器，不是真机。** 不接任何硬件、不声称接入硬件。

它把三样东西缝在一起：
    MiniWorld（几何） + MiniEntity（机器人） + ActionGate（闸）
并对外只暴露 `EmbodimentBackend` 协议的四个方法。

未来接真机时：新增 `argos/backends/go2_backend.py` 实现同一协议，
**Brain / Planner / Memory / Reflector 一行不用改** —— 这就是"换身体不改大脑"。
"""
from __future__ import annotations

import dataclasses
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
from argos.agent.watchdog import AgentWatchdog, TRIGGER_TAG
from argos.sim.failure_injector import FailureInjector
from argos.sensors.base import SensorReading, SensorSuite
from argos.sim.latency import LatencyProfile
from argos.sim.mini_entity import MiniEntity
from argos.world.mini_world import MiniWorld, build_default_world
from argos.world.state import bump, from_observation, view

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
        latency: Optional[LatencyProfile] = None,
        watchdog: Optional[AgentWatchdog] = None,
        sensors: Optional[SensorSuite] = None,
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
        self.latency = latency
        self.watchdog = watchdog
        #: 感知层（可选）。不配 = 上帝视角直读实体，行为与从前逐字一致。
        self.sensors = sensors
        self.last_readings: List[SensorReading] = []
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

    def _sense(self):
        """读一遍传感器：返回 `(字段覆盖, 缺失名单, 逐项读数)`。

        ⚠️ **不写 WorldState** —— 感知是**投影**，不是写入。
        早先写成"感知结果写进 state"是错的：要么被 `_sync` 的真值冲掉、
        要么让 state 变成半真半假的混合体（实测踩到，改成现在这样）。
        """
        if self.sensors is None:
            return {}, (), []
        overrides, missing, readings = self.sensors.sense(self.entity, self.world)
        self.last_readings = readings
        return overrides, missing, readings

    def observe(self) -> Observation:
        """世界状态 → **经由传感器** → Brain 能看的 Observation。

        没配传感器 = 上帝视角直读（与从前逐字一致）；
        配了传感器 = 只能看到传感器读到的（可能有噪声、量化、范围限制、甚至读不到）。
        """
        v = view(self.state)
        overrides, missing, _ = self._sense()
        obs = Observation(
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
            missing=v.missing if self.sensors is None else missing,
        )
        if overrides:
            obs = dataclasses.replace(obs, **{
                k: val for k, val in overrides.items() if hasattr(obs, k)})
        return obs

    def apply(self, action: Action) -> ActionResult:
        """唯一动作出口：**看门狗 → 闸门 → 失败注入 → 延迟 → 执行器 → 写世界**。"""
        self.steps += 1
        before = self.entity.pose
        t0 = self.state.sim_time

        # 0) 先读一遍传感器：闸门要据此判断"数据可不可信"（缺数据 fail-closed）
        self._sense()

        # 1) 看门狗：跳闸后除 STOP 外一律拒绝（fail-closed，须显式 reset）
        #    心跳语义 = "距离上一次**成功完成**的动作过了多久"，所以这里只 check 不 beat；
        #    beat 放在动作完成之后（见第 6 步）。
        if self.watchdog is not None:
            if self.watchdog.tripped:
                # 已处于安全停止态：除 STOP（安全动作本身）外一律拒绝；
                # 也不再重复做超时判据 —— 都停住了，没有"跟不上"可言。
                if action.kind != ActionKind.STOP:
                    return self._record(ActionResult(
                        ok=False, reason=FailReason.ACTION_TIMEOUT,
                        detail="看门狗已跳闸，需显式 reset（安全停止中）",
                        pose_before=before, pose_after=before, sim_time=t0))
            else:
                lost = self.watchdog.check(t0)
                if lost:
                    return self._trip(lost, before)
                self.watchdog.begin_action(t0)

        # 1) 闸（不可绕过）
        # 闸门依据的是**感知**（不是真值）：拿不到数据就该拒绝，而不是凭真值放行
        ok, reason, detail = self.gate.check(action, from_observation(self.observe()))
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

        # 3) 模拟网络/时序延迟（走逻辑时钟，不做真实 sleep → benchmark 仍可复现）
        if self.latency is not None:
            d_ms = self.latency.sample_ms(self.rng)
            self.entity.advance(d_ms / 1000.0)
            if self.latency.drops(self.rng):
                res = ActionResult(
                    ok=False, reason=FailReason.NETWORK_DELAY,
                    detail=f"模拟丢包（{self.latency.name}，{d_ms:.0f}ms）",
                    pose_before=before, pose_after=before,
                    sim_time=self.entity.sim_time)
                self._sync(res)
                return self._record(res)

        # 4) 真的执行
        res = self.entity.apply(action)

        # 5) 只有这里能写世界
        self._sync(res)

        # 6) 看门狗事后判"这次动作是不是太慢了"，然后给这一步打个心跳
        if self.watchdog is not None and not self.watchdog.tripped:
            over = self.watchdog.check_action(self.state.sim_time)
            if over:
                return self._trip(over, self.entity.pose)
            self.watchdog.end_action(self.state.sim_time)
            self.watchdog.beat(self.state.sim_time)
        return self._record(res)

    def reset_watchdog(self) -> None:
        """显式复位（跳闸后不会自动恢复 —— 断过一次就该停下来被人看一眼）。"""
        if self.watchdog is not None:
            self.watchdog.reset()

    def advance_time(self, seconds: float, sync: bool = True) -> None:
        """让世界空转一段逻辑时间（两次动作之间的间隔 / 卡顿）。

        `sync=True` 时把 entity 的时间镜像进 WorldState —— 保证"世界只有一个时钟"。
        """
        self.entity.advance(float(seconds))
        if sync:
            self._sync(ActionResult(ok=True, sim_time=self.entity.sim_time))

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

    def _trip(self, why: str, pose) -> ActionResult:
        """跳闸：记录 WATCHDOG_TRIGGERED + 强制安全停止 + 返回可学习失败。"""
        if self.watchdog is not None:
            self.watchdog.trip(why)
        self.entity.safe_stop()
        # 收速必须落进 WorldState，否则"停下来"只停在 entity 里、对外观察仍是旧速度
        self._sync(ActionResult(ok=False, reason=FailReason.ACTION_TIMEOUT,
                                sim_time=self.entity.sim_time))
        self.state.events.append(f"{TRIGGER_TAG}: {why}")
        return ActionResult(
            ok=False, reason=FailReason.ACTION_TIMEOUT,
            detail=f"看门狗跳闸：{why}",
            pose_before=pose, pose_after=pose, sim_time=self.state.sim_time)

    def _record(self, res: ActionResult) -> ActionResult:
        return res


def build_simulator(seed: int = 42, **kw) -> SimulatorBackend:
    """便捷构造：固定 seed（默认 42），保证同 seed 可复现。"""
    return SimulatorBackend(seed=seed, **kw)
