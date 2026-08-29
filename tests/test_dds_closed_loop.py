"""物理仿真里的**完整闭环**：一句话 → 落账 → DDS 电机级 → 真走 → 记账。

和 test_dds_walk 的区别：那个只测"走到一个点"，这个跑一整段剧情，
把四类结局都过一遍 —— 成功、能力缺失的诚实失败、方向限制的诚实失败、急停拒绝。

地点表刻意全部摆在世界 -x 轴上（0 / -2 / -4），因为 v1 只会沿 -x 直线走。
这样"巡逻一圈"能真的走完（默认地点表做不到，见 架构.md §9 的已知副作用）。

子进程跑（cyclonedds 原生库解释器退出时段错误，不污染 pytest），认 DDS_LOOP_OK。
"""
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mujoco")
pytest.importorskip("unitree_sdk2py")

_ROOT = str(Path(__file__).resolve().parents[2])

_CHILD = r'''
import math
import sys
sys.path.insert(0, ".")
from robot.brain import EV_DONE, EV_FAIL, RobotBrain
from robot.executor import build_executor

# v1 只会沿 -x 走，所以三个地点全摆在负 x 轴上
PLACES = {"充电桩": (0.0, 0.0, 0.0), "桌边": (-2.0, 0.0, 0.0), "门口": (-4.0, 0.0, 0.0)}

ex = build_executor("dds")
brain = RobotBrain(executor=ex, memory_path=None, places=PLACES)

def mem(prefix):
    return [e["content"] for e in brain.memory if e["content"].startswith(prefix)]

# ── 1) 巡逻一圈：从原点走 0 → -2 → -4（逐点推进，要 3 帧）──────────
print("reply:", brain.try_command("巡逻一圈"), flush=True)
# 先 tick 一帧把 pending_task 转成 activity，之后才是逐点推进
# （第一版漏了这一帧：book 只设 pending_task，activity 还是 None，循环直接不进）
brain.tick(); ticks = 1
while brain.activity is not None and ticks < 10:
    brain.tick(); ticks += 1
p = ex.pose()
drift = abs(p["y"])
print(f"patrol ticks={ticks} x={p['x']:.2f} y={p['y']:.2f} 侧向漂移={drift:.2f}m", flush=True)
# 漂移只记录不断言（物理仿真有波动，钉死数值会 flaky）。
# 实测基线（2026-08-29）：走 2m 漂 ~0.2m，累计 4m 漂 ~1.2m —— 是**加速累积**的。
# ⚠ 注意：move_to 的到点判据**只看 x 轴**，所以巡逻会"成功"，
#   但 y 方向已经偏出 1 米多了。这不是成功，是判据太松。见 架构.md §9。
assert ticks == len(PLACES), f"巡逻应逐点走 {len(PLACES)} 帧，实际 {ticks}"
assert mem(EV_DONE), "巡逻走完应该记账（来自用户的单才记账）"
done_before = len(mem(EV_DONE))

# ── 2) 拿东西：没装手臂 → 执行层诚实失败 ─────────────────────────
print("reply:", brain.try_command("拿小球"), flush=True)
ev = brain.tick()
print("grab tick:", ev, flush=True)
assert ev and "failed" in ev, "没手臂应该诚实失败"
assert any("拿小球" in m for m in mem(EV_FAIL)), "没做成要记账"

# ── 3) 掉头回充电桩：v1 不会倒着走 → 诚实失败 ──────────────────────
print("reply:", brain.try_command("回充电桩"), flush=True)
ev = brain.tick()
print("back tick:", ev, flush=True)
assert ev and "failed" in ev, "要掉头应该诚实失败，不能硬走"

# ── 4) 急停：之后所有接单都要被闸门挡下 ──────────────────────────
brain.estop()
reply = brain.try_command("去桌边")
print("estop reply:", reply, flush=True)
assert "做不了" in reply and "急停" in reply, f"急停中不该接单，实际：{reply}"
assert brain.pending_task is None
assert brain.tick() is None, "急停中不该再选自发日常"

# ── 5) 全程没把流程搞崩：成功记一条、失败记两条 ────────────────────
assert len(mem(EV_DONE)) == done_before, "急停后不该再有新的成功记录"
assert len(mem(EV_FAIL)) >= 2, f"失败记录太少：{mem(EV_FAIL)}"
assert math.isfinite(ex.pose()["x"]), "位姿不能是 NaN/inf"
print("DDS_LOOP_OK", flush=True)
'''


def test_full_closed_loop_in_physics_sim():
    r = subprocess.run([sys.executable, "-c", _CHILD], capture_output=True,
                       text=True, timeout=300, cwd=_ROOT)
    if "DDS_LOOP_OK" not in r.stdout:
        pytest.fail(f"物理仿真闭环未通过\nstdout:\n{r.stdout[-2500:]}"
                    f"\nstderr:\n{r.stderr[-2000:]}")
