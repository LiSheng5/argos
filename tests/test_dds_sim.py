"""DDS 电机级闭环冒烟：子进程跑 `dds_sim --selftest`，认 stdout 的 DDS_STAND_OK。

场景：无头 DdsSim（unitree_mujoco 官方桥）+ rt/lowcmd 站立序列 → 物理仿真起立
→ rt/lowstate 关节逼近目标（官方 stand_go2 同款序列与增益）。
独立子进程的原因：cyclonedds 原生库在解释器退出时段错误（线程清理老毛病），
测试结果不受影响，但不让它弄脏 pytest 的退出码。
"""
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mujoco")
pytest.importorskip("unitree_sdk2py")

_ROOT = str(Path(__file__).resolve().parents[1])   # D:/ArgOS（argos 包的上级）


def test_dds_lowcmd_stands_the_dog_up():
    r = subprocess.run(
        [sys.executable, "-m", "argos.sim.dds_sim", "--selftest"],
        capture_output=True, text=True, timeout=120, cwd=_ROOT,
    )
    if "DDS_STAND_OK" not in r.stdout:
        pytest.fail(f"DDS 闭环自检未通过\nstdout:\n{r.stdout[-2000:]}"
                    f"\nstderr:\n{r.stderr[-2000:]}")
