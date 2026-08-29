"""unitree_mujoco 物理仿真冒烟：模型可加载且无头步进不崩（M2 sim 层）。"""
import math

import pytest

from robot.executor import build_executor

pytest.importorskip("mujoco")


def test_mujoco_loads_and_steps_finite():
    e = build_executor("mujoco")            # go2/scene.xml
    e.step(frames=30)
    p = e.pose()
    assert math.isfinite(p["x"]) and math.isfinite(p["y"])


def test_mujoco_pose_after_many_steps():
    e = build_executor("mujoco")
    e.step(frames=300)
    p = e.pose()
    assert math.isfinite(p["x"]) and math.isfinite(p["yaw"])