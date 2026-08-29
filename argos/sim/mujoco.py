"""unitree_mujoco 物理仿真接入：MujocoEntity 实现 RobotExecutor 协议（无头物理步进）。

直接以 mujoco 加载 unitree_mujoco 官方机器人 mjcf（如 go2/scene.xml）并做无头
物理步进（不依赖渲染/DDS），验证模型与仿真可跑。真实步态控制走 DDS/M2 后续。
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List

_REPO = Path(__file__).resolve().parent / "unitree_mujoco"


class MujocoEntity:
    def __init__(self, robot: str = "go2", scene: str = "scene.xml") -> None:
        try:
            import mujoco as mj
        except ImportError as exc:
            raise RuntimeError("未安装 mujoco，先执行：python -m pip install mujoco") from exc
        self._mj = mj
        xml = _REPO / "unitree_robots" / robot / scene
        if not xml.exists():
            raise FileNotFoundError(f"未找到仿真模型：{xml}")
        self.model = mj.MjModel.from_xml_path(str(xml))
        self.data = mj.MjData(self.model)
        self._gripper = None
        self._estop = False

    def step(self, frames: int = 1) -> None:
        for _ in range(frames):
            self._mj.mj_step(self.model, self.data)

    def pose(self) -> Dict:
        q = self.data.qpos
        x, y = float(q[0]), float(q[1])
        qw, qx, qy, qz = float(q[3]), float(q[4]), float(q[5]), float(q[6])
        yaw = math.degrees(math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz)))
        return {"x": x, "y": y, "yaw": yaw, "battery_pct": 100.0,
                "estop": self._estop, "gripper": self._gripper}

    def move_to(self, x: float, y: float, yaw: float = 0.0) -> bool:
        # 无头物理模式：真实步态控制走 DDS/M2；此处仅保证接口可用
        return not self._estop

    def navigate(self, waypoints: List[Dict]) -> bool:
        return not self._estop

    def grab(self, target: str) -> bool:
        self._gripper = target
        return True

    def release(self) -> bool:
        self._gripper = None
        return True

    def estop(self) -> None:
        self._estop = True

    def clear_estop(self) -> None:
        self._estop = False