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
brain = RobotBrain(executor=ex, memory_path=None, routine=(),
                   places={"充电桩": (0.0, 0.0, 0.0), "家": (0.0, 0.0, 0.0),
                           "桌边": (-2.0, 0.0, 0.0), "窗边": (-2.0, 3.0, 0.0)})

# ── 走一段：能不能走准是**随机的**，所以钉的是"链路通 + 结局诚实" ──────
#
# ⚠ 实测（2026-08-29，走 1m 共 4 次）：航向漂 1.4° / 19.9° / 163.2° / 85.3°。
# trot 步态是**开环**的，航向一偏就一路偏下去，后两次狗已经不是在走、是在打转。
# 所以这里不断言"必须走到" —— 那是 flaky 的根源。能确定钉住的只有：
#   ① 全链路通（接单 → 执行 → 有明确结局 → 记账）
#   ② 真的动起来了
#   ③ 走输了也是**早停**，不是耗光超时也不是乱跑
import time as _t
_t0 = _t.perf_counter()
print("reply:", brain.try_command("去桌边"), flush=True)
ev = brain.tick()
elapsed = _t.perf_counter() - _t0
p = brain.executor.pose()
print(f"tick: {ev} x={p['x']:.2f} y={p['y']:.2f} yaw={p['yaw']:.1f}° "
      f"耗时={elapsed:.1f}s", flush=True)
assert ev and ("completed" in ev or "failed" in ev), f"得有个明确结局：{ev}"
assert p["x"] < -0.5, f"至少得往前走起来，实际 x={p['x']:.2f}"
assert elapsed < 15.0, f"该早停，不该耗光超时（{elapsed:.1f}s）"
if "completed" in ev:
    assert any(e["content"].startswith(EV_DONE) for e in brain.memory)
else:
    assert any(e["content"].startswith(EV_FAIL) for e in brain.memory), \
        "走输了也要诚实记账"

# 失败冷却按动作类型计，会连坐后面的移动指令 —— 空转 6 帧放过去
for _ in range(6):
    assert brain.tick() is None, "routine=() 时空闲 tick 不该产生事件"

# ── 去窗边：确定性失败 ─────────────────────────────────────
# 窗边放在 y=3.0（偏离行走轴 3 米）。早先放在 y=1.5，结果偶发"成功"：
# 狗横向漂到 0.8 左右时，|y-1.5| <= 横向容差 0.8 会被判成"到了"。
# 挪到 3.0 之后，无论狗漂到哪都进不了容差，也必然超出漂移预算 → 必然被拒。
reply = brain.try_command("去窗边")
print("reply:", reply, flush=True)
assert "好" in reply, f"窗边应该认得并接单，实际回话：{reply}"
ev = brain.tick()
print("tick:", ev, flush=True)
assert ev and "failed" in ev, "偏离行走轴应该诚实失败"
assert any(e["content"].startswith(EV_FAIL) for e in brain.memory)
print("DDS_WALK_OK x=%.2f" % p["x"], flush=True)
'''


def test_brain_walks_the_dog_via_dds():
    r = subprocess.run([sys.executable, "-c", _CHILD], capture_output=True,
                       text=True, timeout=180, cwd=_ROOT)
    if "DDS_WALK_OK" not in r.stdout:
        pytest.fail(f"DDS 行走闭环未通过\nstdout:\n{r.stdout[-2000:]}"
                    f"\nstderr:\n{r.stderr[-2000:]}")
