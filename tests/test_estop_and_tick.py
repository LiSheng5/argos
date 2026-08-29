"""评审 P0/P1 的回归钉：急停必须到达执行器 + tick 不得阻塞事件循环 + 三处加固。

这些 bug 的共同点：stub 执行器是**瞬移**的，把所有跟时间有关的问题都藏起来了，
所以这里的假执行器会真的耗时（仿 DdsEntity 那种"一个动作走十几秒"的长任务）。
"""
import asyncio
import threading
import time

from argos.brain import EV_FAIL, RobotBrain
from argos.safety import SafetyGate
from argos.server import _tick_loop
from argos.sim.stub import SimEntity


class SlowRobot(SimEntity):
    """会耗时的执行器：move_to 分段推进，每段检查急停（仿 DdsEntity 的长动作）。"""

    def __init__(self, segment: float = 0.05, segments: int = 20) -> None:
        super().__init__()
        self.segment = segment
        self.segments = segments
        self.estop_called = False
        self.cleared = False

    def move_to(self, x: float, y: float, yaw: float = 0.0) -> bool:
        for _ in range(self.segments):
            if self._estop:                   # 段内检查：急停不必等这一整段跑完
                return False
            time.sleep(self.segment)
        return super().move_to(x, y, yaw)

    def estop(self) -> None:
        self.estop_called = True
        self._estop = True

    def clear_estop(self) -> None:
        self.cleared = True
        self._estop = False


# ── P0-1：急停必须到达执行器，并能中断正在跑的长动作 ──────

def test_estop_reaches_executor_and_interrupts_running_move():
    ex = SlowRobot(segment=0.05, segments=40)      # 单次 move_to ≈ 2s
    b = RobotBrain(executor=ex, memory_path=None)
    assert "门口" in b.try_command("去门口") and b.pending_task is not None

    done = {}
    t = threading.Thread(target=lambda: done.setdefault("ev", b.tick()))
    t0 = time.perf_counter()
    t.start()
    time.sleep(0.2)                                # tick 正在跑
    b.estop()                                      # 真机上就是 POST /api/estop
    t.join(timeout=3)
    elapsed = time.perf_counter() - t0

    assert ex.estop_called, "急停没到执行器（P0-1）"
    # 没中断的话这动作要跑满 2s；中断了应该在 0.2~0.5s 就退出来
    assert elapsed < 1.0, f"急停后长动作没有提前退出，耗时 {elapsed:.2f}s（狗还在往前走）"
    ev = done.get("ev") or {}
    assert "failed" in ev, f"急停中断应如实记账，实际事件：{ev}"
    assert any(e["content"].startswith(EV_FAIL) for e in b.memory)


def test_release_estop_clears_both_gate_and_executor():
    ex = SlowRobot()
    b = RobotBrain(executor=ex, memory_path=None)
    b.estop()
    assert b.backend.gate.estop is True and ex.estop_called
    b.estop(False)
    assert ex.cleared and ex._estop is False and b.backend.gate.estop is False
    assert "门口" in b.try_command("去门口")          # 解除后能重新接单


# ── P0-2：tick 不得阻塞事件循环（否则急停按不下去）────────

def test_tick_loop_does_not_block_event_loop():
    """事件循环里挂一个心跳，测的是**阻塞期间**的响应间隔。

    （第一版写错了：在阻塞结束后才去测，卡死 1s 也照样通过。现在看心跳的最大间隔。）
    """
    ex = SlowRobot(segment=0.05, segments=20)      # 单次 move_to ≈ 1s
    b = RobotBrain(executor=ex, memory_path=None)
    # 明确下单，别让 tick 去抽自发日常 —— 抽到 rest 这测试就空转了（又是随机性）
    ok, reason = b.book({"action": "move_to", "x": 4.0, "y": 4.0, "yaw": 0.0})
    assert ok, reason

    async def _probe() -> float:
        loop = asyncio.get_running_loop()
        last, gaps = loop.time(), []

        async def _heartbeat():
            nonlocal last
            while True:
                await asyncio.sleep(0.05)
                now = loop.time()
                gaps.append(now - last)
                last = now

        hb = asyncio.create_task(_heartbeat())
        task = asyncio.create_task(_tick_loop(b))
        await asyncio.sleep(0.6)                   # 覆盖住一次阻塞的 move_to
        for t in (task, hb):
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
        return max(gaps) if gaps else 999.0

    worst = asyncio.run(_probe())
    assert worst < 0.3, (
        f"tick 阻塞了事件循环，心跳最大间隔 {worst:.2f}s"
        "（P0-2：这段时间 /api/estop 是打不进去的）")


# ── P1-4：禁触字段递归扫描（waypoints 内部也要扫）─────────

def test_forbidden_tokens_inside_waypoints_rejected():
    gate = SafetyGate()
    ok, _ = gate.check(
        "navigate", {"waypoints": [{"x": 1, "y": 1, "file": "x"}]},
        {"battery_pct": 100})
    assert not ok, "waypoints 里嵌禁触字段不能放行（P1-4）"


# ── P1-6：电量未知必须 fail-closed ──────────────────

def test_unknown_battery_fails_closed():
    gate = SafetyGate()
    ok, reason = gate.check("navigate", {"waypoints": [{"x": 1, "y": 1}]}, {})
    assert not ok and "电量未知" in reason
    assert gate.check("grab", {"target": "杯子"}, {})[0] is False
    assert gate.check("move_to", {"x": 1, "y": 1}, {})[0] is True   # 安全原语仍放行


# ── P1-5：坏记忆卡改名留证，不让服务起不来 ────────────────

def test_corrupt_memory_card_is_quarantined(tmp_path):
    p = tmp_path / "robot_memory.json"
    p.write_text('{"a": 1}', encoding="utf-8")     # 手改坏 / 写盘中断
    b = RobotBrain(executor=SimEntity(), memory_path=p)
    assert b.memory == []
    b.remember("醒了")
    assert b.memory and b.memory[0]["content"] == "醒了"
    assert list(tmp_path.glob("*.bad-*.json")), "坏卡应改名留证，而不是直接覆盖掉"
