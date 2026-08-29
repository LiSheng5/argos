"""RobotExecutor 协议 + 工厂。协议与 SimEntity / mujoco / 真机 SDK 共用同一套方法签名。"""
from __future__ import annotations

from typing import Dict, List

from robot.sim.stub import SimEntity


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
        from robot.sim.mujoco import MujocoEntity
        return MujocoEntity(**kw)
    if kind == "dds":
        from robot.sim.dds_entity import DdsEntity
        return DdsEntity(**kw)    # DDS 电机级 + 物理仿真（v1 直线巡逻，见 dds_entity docstring）
    if kind == "real":
        raise NotImplementedError("真机 SDK 桥为 M3（需授权/实物），见 架构.md 第 4 节")
    raise ValueError(f"未知执行器类型：{kind}")