"""无 3D 的最小仿真实体 SimEntity：纯逻辑移动/抓取状态，离线可测。

三层一致原则（见 架构.md 第 4 节）：
  SimEntity(stub) -> 真 unitree_mujoco -> 真机 unitree_sdk2，
三者实现同一 RobotExecutor 协议，切换只改一处注入。
"""
from __future__ import annotations

from typing import Dict, List


class SimEntity:
    def __init__(self, start=(0.0, 0.0, 0.0), battery_pct: float = 100.0) -> None:
        self._x, self._y, self._yaw = map(float, start)
        self._gripper = None            # 当前抓取目标名
        self._battery_pct = float(battery_pct)
        self._estop = False

    def pose(self) -> Dict:
        return {"x": self._x, "y": self._y, "yaw": self._yaw,
                "battery_pct": self._battery_pct, "estop": self._estop,
                "gripper": self._gripper}

    def move_to(self, x: float, y: float, yaw: float = 0.0) -> bool:
        if self._estop:
            return False
        self._x, self._y, self._yaw = float(x), float(y), float(yaw)
        return True

    def navigate(self, waypoints: List[Dict]) -> bool:
        if self._estop:
            return False
        if not waypoints:
            return True
        last = waypoints[-1]
        self._x = float(last["x"]); self._y = float(last["y"])
        self._yaw = float(last.get("yaw", self._yaw))
        return True

    def grab(self, target: str) -> bool:
        if self._estop:
            return False
        self._gripper = target
        return True

    def release(self) -> bool:
        self._gripper = None
        return True

    def estop(self) -> None:
        self._estop = True

    def clear_estop(self) -> None:
        """解除急停（评审 P0-1 配套：闸门与执行器必须能一起解除）。"""
        self._estop = False