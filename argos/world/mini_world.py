"""Mini Robot World —— 一个够小、够真、够可复现的世界（Phase 3）。

刻意做小：Room A / Room B / Hallway / Door / Obstacle / Charging Station，
机器人只有 position / velocity / battery，动作只有 move / turn / stop / wait / inspect。
这些已经足够研究 planning / memory / reflection / safety / replanning。

几何是**纯数据 + 纯函数**，无随机、无 I/O —— 同 seed 复现的前提。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from argos.agent.interfaces import Pose

__all__ = ["Rect", "MiniWorld", "build_default_world"]


@dataclass(frozen=True)
class Rect:
    """轴对齐矩形（矩形中心 + 宽高）。"""
    name: str
    x: float      # 中心 x
    y: float      # 中心 y
    w: float
    h: float

    @property
    def x0(self) -> float: return self.x - self.w / 2.0

    @property
    def x1(self) -> float: return self.x + self.w / 2.0

    @property
    def y0(self) -> float: return self.y - self.h / 2.0

    @property
    def y1(self) -> float: return self.y + self.h / 2.0

    def contains(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1


@dataclass(frozen=True)
class MiniWorld:
    name: str
    rooms: Tuple[Rect, ...] = ()
    obstacles: Tuple[Rect, ...] = ()
    locations: Tuple[Tuple[str, Pose], ...] = ()
    routes: Tuple[Tuple[str, Tuple[Pose, ...]], ...] = ()
    bounds: Rect = Rect("bounds", 0, 0, 40.0, 40.0)

    def location(self, name: str) -> Optional[Pose]:
        for k, v in self.locations:
            if k == name:
                return v
        return None

    def route(self, name: str) -> Optional[Tuple[Pose, ...]]:
        for k, v in self.routes:
            if k == name:
                return v
        return None

    def route_names(self) -> Tuple[str, ...]:
        return tuple(k for k, _ in self.routes)

    def room_of(self, x: float, y: float) -> Optional[str]:
        for r in self.rooms:
            if r.contains(x, y):
                return r.name
        return None

    def blocked(self, x0: float, y0: float, x1: float, y1: float,
                step: float = 0.05) -> Optional[str]:
        """线段 (x0,y0)→(x1,y1) 是否撞到障碍；撞到返回障碍名，否则 None。

        用固定步长采样：**确定性**（不引入随机，便于同 seed 复现）。
        """
        dx, dy = x1 - x0, y1 - y0
        dist = (dx * dx + dy * dy) ** 0.5
        n = int(dist / step) + 1
        for i in range(n + 1):
            t = i / n
            px, py = x0 + dx * t, y0 + dy * t
            for ob in self.obstacles:
                if ob.contains(px, py):
                    return ob.name
        return None


def build_default_world() -> MiniWorld:
    """默认迷你世界（本轮所有 demo / benchmark 都用它）。

    布局（俯视，+x 向右，+y 向上）：

        Room A          Hallway            Room B
      [-3,3]×[-3,3]   [3,7]×[-1,1]     [7,13]×[-3,3]
          ·room_a(0,0)   ·hallway(5,0)   ·room_b(10,0)
                          ·door(7,0)     ·charger(10,-2)   ← 目标：充电站

    两条路线：
      * `north` —— 走 y=+2，**会被 `north_block` 挡住**（这是 demo 的失败源）
      * `south` —— 走 y=-2，畅通（这是反思后要改走的路）
    """
    rooms = (
        Rect("room_a", 0.0, 0.0, 6.0, 6.0),
        Rect("hallway", 5.0, 0.0, 4.0, 2.0),
        Rect("room_b", 10.0, 0.0, 6.0, 6.0),
    )
    obstacles = (
        Rect("north_block", 5.0, 2.0, 2.0, 1.5),   # x∈[4,6], y∈[1.25,2.75]
    )
    locations = (
        ("room_a", Pose(0.0, 0.0, 0.0)),
        ("hallway", Pose(5.0, 0.0, 0.0)),
        ("door", Pose(7.0, 0.0, 0.0)),
        ("room_b", Pose(10.0, 0.0, 0.0)),
        ("charger", Pose(10.0, -2.0, 0.0)),
    )
    routes = (
        ("north", (Pose(2.0, 2.0, 0.0), Pose(5.0, 2.0, 0.0), Pose(9.0, 2.0, 0.0), Pose(10.0, -2.0, 0.0))),
        ("south", (Pose(2.0, -2.0, 0.0), Pose(5.0, -2.0, 0.0), Pose(9.0, -2.0, 0.0), Pose(10.0, -2.0, 0.0))),
    )
    bounds = Rect("bounds", 5.0, 0.0, 40.0, 40.0)
    return MiniWorld(
        name="mini_world",
        rooms=rooms,
        obstacles=obstacles,
        locations=locations,
        routes=routes,
        bounds=bounds,
    )
