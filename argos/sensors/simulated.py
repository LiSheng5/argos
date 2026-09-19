"""仿真传感器（Wave 3 / 指令 §19）—— 全部是**模拟**，不接任何真实硬件驱动。

四个传感器对应指令点名的那几个：

| 传感器 | 负责的观测字段 | 可配的"不完美" |
|---|---|---|
| `SimPoseSensor` | `robot_pose` | 噪声（米）、失灵概率 |
| `SimBatterySensor` | `battery` | 量化步长（读数跳变）、失灵概率 |
| `SimObstacleSensor` | `obstacles` | **探测半径**（看不见远处的东西）|
| `SimVisionSensor` | `objects` / `locations` | **探测半径** |

⚠️ 感知范围故意做成可配的：看不见远处的障碍时，agent 会在**真正撞上**那一刻才学到东西 ——
这正是"只能靠试错学"的成立条件，也是反思闭环存在意义的直接来源。
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field as dc_field
from typing import Optional, Tuple

from argos.agent.interfaces import Pose
from argos.world.mini_world import Rect

__all__ = [
    "SimPoseSensor", "SimBatterySensor", "SimObstacleSensor", "SimVisionSensor",
    "simulated_suite",
]


def _dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


@dataclass
class SimPoseSensor:
    """定位传感器。

    两条**刻意**的建模选择（都吃过亏）：

    * **噪声 = 整轮固定的标定偏差**，不是每次读重新抖动。
      真实传感器不会"读一次抖一次"；而且"每次读都掷骰子"会让观测结果取决于
      **你读了几次** —— `_view()` 读一次、闸门再读一次，两次结果不同，
      于是"这一步缺不缺数据"变成了调用次数的偶然函数（实测踩到：闸门恰好没掷中）。
    * **失灵是粘性的**：坏了就坏这一轮（新的一轮会新建传感器，自然恢复）。
      不粘的话会出现"忽好忽坏"，闸门时好时坏，行为不可解释。
    """
    name: str = "pose"
    obs_field: str = "robot_pose"
    noise_m: float = 0.0          # 定位偏差（米），整轮固定
    dropout: float = 0.0          # 整轮失灵概率（每轮只掷一次）
    rng: random.Random = dc_field(default_factory=lambda: random.Random(0))
    _bias: Optional[Tuple[float, float]] = None
    _dead: bool = False

    def read(self, entity, world) -> Optional[Pose]:
        if self._dead:
            return None                      # 粘性：坏了就一直是坏的
        if self.dropout > 0 and self.rng.random() < self.dropout:
            self._dead = True
            return None
        p = entity.pose
        if self.noise_m <= 0:
            return p
        if self._bias is None:               # 只掷一次 → 整轮同一个偏差
            self._bias = (self.rng.uniform(-self.noise_m, self.noise_m),
                          self.rng.uniform(-self.noise_m, self.noise_m))
        return Pose(x=p.x + self._bias[0], y=p.y + self._bias[1], yaw=p.yaw,
                    vx=p.vx, vy=p.vy, vyaw=p.vyaw)


@dataclass
class SimBatterySensor:
    name: str = "battery"
    obs_field: str = "battery"
    step_pct: float = 0.0         # 量化步长：电量读数只会按 1% / 5% 跳
    dropout: float = 0.0          # 整轮失灵概率（粘性，同 SimPoseSensor）
    rng: random.Random = dc_field(default_factory=lambda: random.Random(0))
    _dead: bool = False

    def read(self, entity, world) -> Optional[float]:
        if self._dead:
            return None
        if self.dropout > 0 and self.rng.random() < self.dropout:
            self._dead = True
            return None
        b = float(entity.battery)
        if self.step_pct > 0:
            b = math.floor(b / self.step_pct) * self.step_pct
        return round(b, 6)


@dataclass
class SimObstacleSensor:
    """探测半径受限：半径外的东西**看不见**（但世界照样会挡你）。"""
    name: str = "obstacle"
    obs_field: str = "obstacles"
    radius_m: float = 5.0
    rng: random.Random = dc_field(default_factory=lambda: random.Random(0))

    def read(self, entity, world) -> Tuple[Rect, ...]:
        """只看得见**中心落在半径内**的障碍。

        注意 `Rect` 的 `x/y` 是角点，中心要自己算（`x + w/2`）—— 别当成 min/max。
        """
        p = entity.pose
        return tuple(r for r in world.obstacles
                     if _dist(p.x, p.y, r.x + r.w / 2.0, r.y + r.h / 2.0) <= self.radius_m)

    def sees(self, entity, world, rect: Rect) -> bool:
        p = entity.pose
        return _dist(p.x, p.y, rect.x + rect.w / 2.0, rect.y + rect.h / 2.0) <= self.radius_m


@dataclass
class SimVisionSensor:
    """视觉：看得见范围内的**房间**与**地点**（范围外看不见）。

    迷你世界里没有额外"物体"，房间本身就是看得见的东西 —— 不硬造一个假的 objects 列表。
    """
    name: str = "vision"
    obs_field: str = "objects"
    radius_m: float = 6.0
    rng: random.Random = dc_field(default_factory=lambda: random.Random(0))

    def read(self, entity, world) -> Tuple:
        p = entity.pose
        rooms = tuple(r.name for r in world.rooms
                      if _dist(p.x, p.y, r.x + r.w / 2.0, r.y + r.h / 2.0) <= self.radius_m)
        spots = tuple(name for name, pose in world.locations
                      if _dist(p.x, p.y, pose.x, pose.y) <= self.radius_m)
        return rooms + spots

    def read_locations(self, entity, world):
        p = entity.pose
        return tuple((name, pose) for name, pose in world.locations
                     if _dist(p.x, p.y, pose.x, pose.y) <= self.radius_m)


def simulated_suite(*, seed: int = 42, pose_noise: float = 0.0, pose_dropout: float = 0.0,
                    battery_step: float = 0.0, battery_dropout: float = 0.0,
                    obstacle_radius: float = 5.0, vision_radius: float = 6.0):
    """装配一套仿真传感器（`sensors` 包向外暴露的入口）。"""
    return (
        SimPoseSensor(noise_m=pose_noise, dropout=pose_dropout, rng=random.Random(seed)),
        SimBatterySensor(step_pct=battery_step, dropout=battery_dropout,
                         rng=random.Random(seed + 1)),
        SimObstacleSensor(radius_m=obstacle_radius, rng=random.Random(seed + 2)),
        SimVisionSensor(radius_m=vision_radius, rng=random.Random(seed + 3)),
    )
