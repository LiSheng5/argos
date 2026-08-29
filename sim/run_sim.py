"""unitree_mujoco 仿真实例。

已完成（M2）：robot/sim/mujoco.py::MujocoEntity 直接加载官方 go2 mjcf 做无头
物理步进（装 mujoco 即可），build_executor("mujoco") 一键接入，test_sim_smoke 通过。

待办（电机级控制 / sim-to-real 闭环）：
  - DDS 控制库需源码安装：cd robot/sim/unitree_sdk2_python && pip install -e .
    （依赖编译 CycloneDDS，Windows 上较繁；Linux 直通）
  - 装好后可跑 unitree_mujoco/simulate_python/unitree_mujoco.py 起仿真，
    并用 unitree_mujoco/example/python/stand_go2.py 发 LowCmd 让机器人起立/趴下。

免安装快速验证（已接入）：pytest tests/test_sim_smoke.py
"""
from __future__ import annotations


def smoke() -> str:
    from robot.executor import build_executor
    e = build_executor("mujoco")          # go2/scene.xml，无头物理
    e.step(frames=30)
    return f"mujoco sim ok, pose={e.pose()}"