"""端到端闭环：大脑一句话 → DdsEntity（DDS 电机级）→ 物理仿真里真的走过去。

  去桌边(-2,0) → 起立 → trot 直线走 ~2m → 到点 → 完成+记忆；
  去窗边(-2,1.5) → 落账成功，但要转弯（y 偏离行走轴 1.5m）→ v1 诚实失败+记忆。

2026-08-29 评审修订（P1-3）：第二段原来写的是"去门口"，而这份 places 里根本
没有"门口"，compile_command 返回 None → 走的是"听不懂"路径，压根没落账；
断言的"failed"实际是靠自发日常**随机**撞出来的（navigate 3/6 会失败，去桌边
2/6 因狗已在 -2 附近 dist≤0.25 直接成功，rest 1/6 成功）—— 约 50% 概率误报。
改成"表里就有、但偏离行走轴"的地点，落账必然成功、执行必然拒绝，断言才确定。
子进程跑（cyclonedds 原生库解释器退出时段错误，不污染 pytest），认 DDS_WALK_OK。
"""
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mujoco")
pytest.importorskip("unitree_sdk2py")

_ROOT = str(Path(__file__).resolve().parents[2])

_CHILD = r'''
import sys
sys.path.insert(0, ".")
from robot.brain import RobotBrain, EV_DONE, EV_FAIL
from robot.executor import build_executor

ex = build_executor("dds")     # v1 直线巡逻员：只会沿行走轴(-x)走，见 dds_entity docstring
brain = RobotBrain(executor=ex, memory_path=None,
                   places={"充电桩": (0.0, 0.0, 0.0), "家": (0.0, 0.0, 0.0),
                           "桌边": (-2.0, 0.0, 0.0), "窗边": (-2.0, 1.5, 0.0)})
print("reply:", brain.try_command("去桌边"), flush=True)
ev = brain.tick()
print("tick:", ev, flush=True)
x = brain.executor.pose()["x"]
assert ev and ev.get("completed") == "去桌边", "没走到桌边"
assert -2.6 <= x <= -1.4, f"终点偏差过大: x={x:.2f}"
assert any(e["content"].startswith(EV_DONE) for e in brain.memory)

# 窗边在表里 → 必然落账成功；但 y 偏离行走轴 1.5m → 执行器必然诚实拒绝
reply = brain.try_command("去窗边")
print("reply:", reply, flush=True)
assert "好" in reply, f"窗边应该认得并接单，实际回话：{reply}"
ev = brain.tick()
print("tick:", ev, flush=True)
assert ev and "failed" in ev, "不会转弯应诚实失败"
assert any(e["content"].startswith(EV_FAIL) for e in brain.memory)
print("DDS_WALK_OK x=%.2f" % x, flush=True)
'''


def test_brain_walks_the_dog_via_dds():
    r = subprocess.run([sys.executable, "-c", _CHILD], capture_output=True,
                       text=True, timeout=180, cwd=_ROOT)
    if "DDS_WALK_OK" not in r.stdout:
        pytest.fail(f"DDS 行走闭环未通过\nstdout:\n{r.stdout[-2000:]}"
                    f"\nstderr:\n{r.stderr[-2000:]}")
