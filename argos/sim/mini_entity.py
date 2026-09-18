"""MiniEntity —— 迷你世界里那台"机器人"（Phase 3）。

**它是仿真器，不是真机**：没有电机、没有 DDS、没有摄像头。
它只做三件诚实的事：
  1. 按几何算"能不能走过去"（撞障碍就 OBSTACLE_BLOCKED，**并且真的不移动**）；
  2. 推进**逻辑时钟** `sim_time`（不用 `time.time()`，保证同 seed 可复现）；
  3. 消耗电量、报告结构化的 `ActionResult`（失败有分类，不是裸 False）。

没有机械臂 → `grab/release` 诚实返回 EXECUTOR_FAILURE，不假装成功。
"""
from __future__ import annotations

from typing import Optional

from argos.agent.interfaces import (
    Action,
    ActionKind,
    ActionResult,
    FailReason,
    Pose,
)
from argos.world.mini_world import MiniWorld

__all__ = ["MiniEntity"]


class MiniEntity:
    def __init__(
        self,
        world: MiniWorld,
        pose: Pose = Pose(),
        battery: float = 100.0,
        speed: float = 0.5,          # m/s
        turn_rate: float = 1.0,      # rad/s
        drain_per_m: float = 0.4,    # 每米耗电 %
        drain_per_s: float = 0.05,   # 每秒耗电 %
        dt: float = 0.5,             # 基础时间片（wait/inspect 用）
        has_arm: bool = False,
    ) -> None:
        self.world = world
        self._pose = pose
        self.battery = float(battery)
        self.speed = float(speed)
        self.turn_rate = float(turn_rate)
        self.drain_per_m = float(drain_per_m)
        self.drain_per_s = float(drain_per_s)
        self.dt = float(dt)
        self.has_arm = bool(has_arm)
        self.sim_time = 0.0

    # ---- 读 ----
    @property
    def pose(self) -> Pose:
        return self._pose

    # ---- 外部可用的时间推进（延迟剖面 / watchdog 打点用；只推进时钟，不产生动作）----
    def advance(self, seconds: float) -> None:
        self._advance(seconds)

    def safe_stop(self) -> None:
        """强制收速：清掉速度分量（watchdog 跳闸时用）。"""
        p = self._pose
        self._pose = Pose(p.x, p.y, p.yaw, 0.0, 0.0, 0.0)

    # ---- 写（只有本类和 backend 能改）----
    def apply(self, action: Action) -> ActionResult:
        before = self._pose
        kind = action.kind
        p = action.params or {}

        if kind == ActionKind.MOVE:
            return self._move(before, p)
        if kind == ActionKind.TURN:
            return self._turn(before, p)
        if kind == ActionKind.STOP:
            self._advance(self.dt)
            self._pose = Pose(self._pose.x, self._pose.y, self._pose.yaw)
            return self._ok(before, "已停止")
        if kind == ActionKind.WAIT:
            d = float(p.get("duration", self.dt))
            self._advance(d)
            return self._ok(before, f"等待 {d:.2f}s")
        if kind == ActionKind.INSPECT:
            self._advance(self.dt)
            room = self.world.room_of(self._pose.x, self._pose.y)
            return self._ok(before, f"观察到：{room or '未知区域'}")
        if kind in (ActionKind.GRAB, ActionKind.RELEASE):
            if not self.has_arm:
                return ActionResult(
                    ok=False, reason=FailReason.EXECUTOR_FAILURE,
                    detail="当前身体没有机械臂（诚实失败，不假装成功）",
                    pose_before=before, pose_after=before, sim_time=self.sim_time,
                )
            self._advance(self.dt)
            return self._ok(before, f"{kind.value} 完成")

        return ActionResult(
            ok=False, reason=FailReason.EXECUTOR_FAILURE,
            detail=f"执行器不认识该动作：{kind}",
            pose_before=before, pose_after=before, sim_time=self.sim_time,
        )

    # ---- 各动作 ----
    def _move(self, before: Pose, p: dict) -> ActionResult:
        tx, ty = float(p["x"]), float(p["y"])
        dist = before.dist_to(Pose(tx, ty, 0.0))
        if dist < 1e-9:
            return self._ok(before, "已在目标点")

        hit = self.world.blocked(before.x, before.y, tx, ty)
        if hit is not None:
            # 被挡住 = **真的没动**。诚实比"挪一半"重要。
            return ActionResult(
                ok=False, reason=FailReason.OBSTACLE_BLOCKED,
                detail=f"路径被 {hit} 挡住",
                pose_before=before, pose_after=before, sim_time=self.sim_time,
            )

        sp = float(p.get("speed", self.speed)) or self.speed
        dur = dist / sp
        vx, vy = (tx - before.x) / dur, (ty - before.y) / dur
        self._pose = Pose(tx, ty, before.yaw, vx, vy, 0.0)
        self._advance(dur, dist)
        return self._ok(before, f"移动 {dist:.2f}m")

    def _turn(self, before: Pose, p: dict) -> ActionResult:
        yaw = float(p["yaw"])
        delta = abs(yaw - before.yaw)
        self._pose = Pose(before.x, before.y, yaw, 0.0, 0.0, 0.0)
        self._advance(delta / (self.turn_rate or 1.0))
        return self._ok(before, f"转向 {yaw:.2f}rad")

    # ---- 内部 ----
    def _advance(self, seconds: float, meters: float = 0.0) -> None:
        self.sim_time += float(seconds)
        self.battery = max(0.0, self.battery - meters * self.drain_per_m - seconds * self.drain_per_s)

    def _ok(self, before: Pose, detail: str) -> ActionResult:
        return ActionResult(
            ok=True, reason=FailReason.OK, detail=detail,
            pose_before=before, pose_after=self._pose, sim_time=self.sim_time,
        )
