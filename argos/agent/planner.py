"""Planner —— 真的会规划，也会重规划（Phase 4，旧系统最缺的一块）。

旧系统没有 Planner：`_plan_steps`（`brain.py:368`）只是把动作名展开成一两步的字典查表，
失败就终止 + 冷却 5 tick，从不换路。这里补上两件事：

  1. `plan()`  —— 目标 → 选路线 → 一串 ActionProposal（**只是提议，不碰世界**）；
  2. `replan()`—— 失败后**换一条路线**继续，而不是原地冷却。

Planner 读的是 `WorldView`（不可变投影）和 `Lesson`（反思产物）——
**这就是"Memory 被 Planner 消费"的落点**（旧系统里 recall 只用于措辞，`brain.py:272`）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from argos.agent.interfaces import (
    ActionKind,
    ActionProposal,
    EmbodimentCapabilities,
    Lesson,
    Pose,
)
from argos.world.mini_world import MiniWorld
from argos.world.state import WorldView

__all__ = ["Plan", "Planner"]

#: 中文/英文目标词 → 地点名（够用就好，不搞大模型意图识别）
GOAL_WORDS = {
    "充电站": "charger", "充电桩": "charger", "charger": "charger",
    "房间b": "room_b", "房b": "room_b", "b房间": "room_b", "room_b": "room_b",
    "房间a": "room_a", "房a": "room_a", "room_a": "room_a",
    "走廊": "hallway", "hallway": "hallway",
    "门口": "door", "门": "door", "door": "door",
}


@dataclass
class Plan:
    """一次规划结果。route 记下来，失败时才知道该避开哪条。"""
    route: str
    goal: str
    target: str
    proposals: List[ActionProposal] = field(default_factory=list)
    #: 这是不是一次"复核试探"（明知有教训仍故意走那条路，看它恢复了没）
    is_probe: bool = False


class Planner:
    def __init__(self, world: MiniWorld, max_retry: int = 2) -> None:
        self.world = world
        self.max_retry = int(max_retry)

    # ---- 目标 ----
    def resolve_target(self, goal: str) -> Optional[str]:
        """文本目标 → 地点名。认不出来就返回 None（诚实，不瞎猜）。"""
        if not goal:
            return None
        g = goal.strip()
        if g in GOAL_WORDS:
            return GOAL_WORDS[g]
        for name, _ in self.world.locations:
            if name == g or name in g:
                return name
        for word, name in GOAL_WORDS.items():
            if word in g:
                return name
        return None

    # ---- 路线 ----
    def choose_route(self, lessons: Sequence[Lesson],
                     exclude: Sequence[str] = ()) -> Optional[str]:
        """选一条**没被教训点名**、也不在 exclude 里的路线。"""
        avoided = {l.avoid for l in lessons}
        for r in self.world.route_names():
            if r in avoided or r in exclude:
                continue
            return r
        return None

    def avoided_route(self, lessons: Sequence[Lesson],
                      exclude: Sequence[str] = ()) -> Optional[str]:
        """取一条**当前被教训避开**的路线（用于复核试探）。"""
        avoided = {l.avoid for l in lessons}
        for r in self.world.route_names():
            if r in avoided and r not in exclude:
                return r
        return None

    def plan(self, goal: str, view: WorldView, lessons: Sequence[Lesson],
             caps: EmbodimentCapabilities, probe: bool = False) -> Optional[Plan]:
        target = self.resolve_target(goal)
        if target is None:
            return None

        # 复核：明知有教训，仍故意走一次那条路 —— 看环境是不是已经恢复。
        if probe:
            r = self.avoided_route(lessons)
            if r is not None:
                return Plan(route=r, goal=goal, target=target,
                            proposals=self._build(r, target, view, caps),
                            is_probe=True)

        route = self.choose_route(lessons)
        if route is None:
            return None
        proposals = self._build(route, target, view, caps)
        return Plan(route=route, goal=goal, target=target, proposals=proposals)

    def replan(self, plan: Plan, view: WorldView, lessons: Sequence[Lesson],
               caps: EmbodimentCapabilities,
               reason: Optional[str] = None) -> Optional[Plan]:
        """换一条路线重来 —— **从当前位置出发**，不是从头再来。"""
        exclude = (plan.route,)
        route = self.choose_route(lessons, exclude=exclude)
        if route is None:
            return None
        proposals = self._build(route, plan.target, view, caps)
        return Plan(route=route, goal=plan.goal, target=plan.target,
                    proposals=proposals)

    # ---- 内部 ----
    def _build(self, route: str, target: str, view: WorldView,
               caps: EmbodimentCapabilities) -> List[ActionProposal]:
        waypoints = list(self.world.route(route) or ())
        target_pose = self.world.location(target)
        if target_pose is None:
            return []
        # 路线终点不是目标 → 补一段
        if not waypoints or waypoints[-1] != target_pose:
            waypoints.append(target_pose)

        out: List[ActionProposal] = []
        start = view.robot
        first = waypoints[0]
        # 先转向（若身体支持）—— 提议而已，能不能转由闸门和世界说了算
        if caps.supports(ActionKind.TURN):
            yaw = math.atan2(first.y - start.y, first.x - start.x)
            out.append(ActionProposal(ActionKind.TURN, {"yaw": yaw},
                                      rationale=f"先朝向 {route} 路线第一个途经点"))
        for wp in waypoints:
            out.append(ActionProposal(
                ActionKind.MOVE, {"x": wp.x, "y": wp.y},
                rationale=f"沿 {route} 路线前进到 ({wp.x}, {wp.y})"))
        out.append(ActionProposal(ActionKind.STOP, {}, rationale="到达后停车"))
        return out
