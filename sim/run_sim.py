"""unitree_mujoco 仿真实例。

已完成（M2）：robot/sim/mujoco.py::MujocoEntity 直接加载官方 go2 mjcf 做无头
物理步进（装 mujoco 即可），build_executor("mujoco") 一键接入，test_sim_smoke 通过。

电机级控制（已打通，2026-08-28；本 docstring 里"DDS 需源码编译、Windows 较繁"
的旧说法已作废 —— cyclonedds 11.0.1 在 Py3.13/Windows 上 pip 直装可用，详见
requirements.txt）：
    python -m pip install -e sim/unitree_sdk2_python --no-deps
    python -m robot.sim.dds_sim --selftest        # 站立闭环自检
    python -m robot.server --executor dds         # 一句话 → 物理仿真真走
上游目录自带 .git，不在本仓库里，换机器按 requirements.txt 第 4 节重拉。

免安装快速验证（已接入）：pytest tests/test_sim_smoke.py
"""
from __future__ import annotations


def smoke() -> str:
    from robot.executor import build_executor
    e = build_executor("mujoco")          # go2/scene.xml，无头物理
    e.step(frames=30)
    return f"mujoco sim ok, pose={e.pose()}"