"""物理仿真里的**完整闭环**：一句话 → 落账 → DDS 电机级 → 真走 → 记账。

和 test_dds_walk 的区别：那个只测"走到一个点"，这个跑一整段剧情，
把各类结局都过一遍 —— 成功、漂出预算的诚实早停、能力缺失的诚实失败、
方向限制的诚实失败、急停拒绝。

地点表刻意全部摆在世界 -x 轴上（0 / -2 / -4），因为 v1 只会沿 -x 直线走。

子进程跑（cyclonedds 原生库解释器退出时段错误，不污染 pytest），认 DDS_LOOP_OK。
"""
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mujoco")
pytest.importorskip("unitree_sdk2py")

_ROOT = str(Path(__file__).resolve().parents[1])

_CHILD = r'''
import math
import sys
import time
sys.path.insert(0, ".")
from argos.brain import EV_DONE, EV_FAIL, RobotBrain
from argos.executor import build_executor
from argos.sim.dds_entity import MAX_LATERAL, WALK_TIMEOUT, arrived

# v1 只会沿 -x 走，所以三个地点全摆在负 x 轴上
PLACES = {"充电桩": (0.0, 0.0, 0.0), "桌边": (-2.0, 0.0, 0.0), "门口": (-4.0, 0.0, 0.0)}

ex = build_executor("dds")
# routine=()：不让自发日常插进来乱动位置，这段剧情才可控
brain = RobotBrain(executor=ex, memory_path=None, places=PLACES, routine=())

def mem(prefix):
    return [e["content"] for e in brain.memory if e["content"].startswith(prefix)]

def clear_cooldown():
    """失败冷却按**动作类型**计（BLOCK_AFTER_FAIL_TICKS=5），
    一个 move_to 漂了会连坐后面所有移动指令。这里空转 6 帧把它放过去。"""
    for _ in range(6):
        assert brain.tick() is None, "routine=() 时空闲 tick 不该产生事件"

def run_to_completion():
    """先 tick 一帧把 pending_task 转成 activity，之后才是逐点推进。
    （踩过两次的坑：book 只设 pending_task，activity 还是 None，
      直接 while activity 的循环一次都不进 —— 狗一动不动。）"""
    ev = brain.tick(); n = 1
    while brain.activity is not None and n < 10:
        brain.tick(); n += 1
    return ev, n

# ── 1) 去桌边 2m：结果**不保证**（见下），但必须走得像样 ──────────────
#
# ⚠ 重要实测（2026-08-29）：横向漂移是**随机的**，同一段 2m 路
#   两次跑出来漂 0.20m 和 0.57m。所以这里不断言成功与否 —— v1 的低层
#   步态就是走不稳，2 米都可能偏出半米（偏太多会被漂移预算拦下 → 诚实失败）。
#   能确定钉住的只有：不崩、不耗光超时、记账正确。
print("reply:", brain.try_command("去桌边"), flush=True)
t0 = time.perf_counter()
ev, n = run_to_completion()
elapsed = time.perf_counter() - t0
p = ex.pose()
print(f"桌边: ticks={n} x={p['x']:.3f} y={p['y']:.3f} 漂移={abs(p['y']):.3f}m "
      f"耗时={elapsed:.1f}s -> {ev}", flush=True)
assert abs(p["x"]) > 0.5, f"至少得往前走起来，实际 x={p['x']:.3f}"
assert elapsed < WALK_TIMEOUT, "漂超预算要早停，不该把 15s 超时耗光"
assert (ev or {}).get("completed") or (ev or {}).get("failed"), f"得有个明确结局：{ev}"
walked_ok = bool((ev or {}).get("completed"))

# ── 2) 漂移预算：给一个极小的预算，必须**立刻**停下并诚实失败 ────────────
# 直接调执行器（绕开大脑的失败冷却），小预算 = 确定性触发，
# 不受"走多远漂多少"的随机性影响 —— 这样才能钉住早停这条路径。
p0 = ex.pose()
t0 = time.perf_counter()
ok = ex.move_to(-6.0, 0.0, max_lateral=0.01)
elapsed = time.perf_counter() - t0
p = ex.pose()
print(f"极小预算(1cm): ok={ok} 耗时={elapsed:.2f}s "
      f"位移={abs(p['x'] - p0['x']):.3f}m", flush=True)
assert ok is False, "预算只有 1cm，应该判漂出并失败"
assert elapsed < 2.0, f"应该立刻返回，不该走起来（耗时 {elapsed:.2f}s）"
assert abs(p["x"] - p0["x"]) < 0.3, "一步都不该走"

# ── 3) 拿东西：没装手臂 → 执行层诚实失败 ─────────────────────────
clear_cooldown()
print("reply:", brain.try_command("拿小球"), flush=True)
ev, _ = run_to_completion()
print("grab:", ev, flush=True)
assert ev and "failed" in ev, "没手臂应该诚实失败"
assert any("拿小球" in m for m in mem(EV_FAIL)), "没做成要记账"

# ── 4) 掉头回充电桩：v1 不会倒着走 → 诚实失败 ──────────────────────
clear_cooldown()
print("reply:", brain.try_command("回充电桩"), flush=True)
ev, _ = run_to_completion()
print("back:", ev, flush=True)
assert ev and "failed" in ev, "要掉头应该诚实失败，不能硬走"

# ── 5) 急停：之后所有接单都要被闸门挡下 ──────────────────────────
brain.estop()
reply = brain.try_command("去桌边")
print("estop reply:", reply, flush=True)
assert "做不了" in reply and "急停" in reply, f"急停中不该接单，实际：{reply}"
assert brain.pending_task is None
assert brain.tick() is None, "急停中不该再选自发日常"

# ── 6) 全程没把流程搞崩 ──────────────────────────────────────
assert len(mem(EV_DONE)) == (1 if walked_ok else 0), (
    f"成功记录数应该和第一步是否走成一致，实际 {mem(EV_DONE)}")
assert len(mem(EV_FAIL)) >= (2 if walked_ok else 3), f"失败记录太少：{mem(EV_FAIL)}"
assert math.isfinite(ex.pose()["x"]) and math.isfinite(ex.pose()["y"]), "位姿不能是 NaN/inf"
print("DDS_LOOP_OK", flush=True)
'''


def test_full_closed_loop_in_physics_sim():
    r = subprocess.run([sys.executable, "-c", _CHILD], capture_output=True,
                       text=True, timeout=300, cwd=_ROOT)
    if "DDS_LOOP_OK" not in r.stdout:
        pytest.fail(f"物理仿真闭环未通过\nstdout:\n{r.stdout[-2500:]}"
                    f"\nstderr:\n{r.stderr[-2000:]}")
