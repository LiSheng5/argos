"""RobotExecutor 协议 + 工厂。协议与 SimEntity / mujoco / 真机 SDK 共用同一套方法签名。"""
from __future__ import annotations

from typing import Dict, List

from argos.sim.stub import SimEntity


class RobotExecutor:
    def move_to(self, x: float, y: float, yaw: float = 0.0) -> bool: ...
    def navigate(self, waypoints: List[Dict]) -> bool: ...
    def grab(self, target: str) -> bool: ...
    def release(self) -> bool: ...
    def pose(self) -> Dict: ...
    def estop(self) -> None: ...


def build_executor(kind: str = "sim", **kw):
    if kind == "sim":
        return SimEntity(**kw)
    if kind == "mujoco":
        from argos.sim.mujoco import MujocoEntity
        return MujocoEntity(**kw)
    if kind == "dds":
        from argos.sim.dds_entity import DdsEntity
        return DdsEntity(**kw)    # DDS 电机级 + 物理仿真（v1 直线巡逻，见 dds_entity docstring）
    if kind == "real":
        from argos.real_sport import RealSportEntity
        return RealSportEntity(**kw)   # 高层 SportClient；无真机会在连接处抛错
    raise ValueError(f"未知执行器类型：{kind}")