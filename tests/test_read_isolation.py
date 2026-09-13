"""读端点隔离测试（借鉴 Microduck）：last-value 快照优先 + 超时降级。

钉三件事：
  1. tick 每帧写快照，读端点只读它 —— 不再反复戳执行器；
  2. 从未 tick 过（旧装配/刚启动）仍然如实回落实时读，不破坏旧行为；
  3. executor 卡死时读接口不永久挂起，返回诚实的断连骨架（HTTP 仍 200）。
"""
import asyncio
import time

from fastapi.testclient import TestClient

from argos.brain import RobotBrain
from argos.sim.stub import SimEntity
from argos.web.api import _read_or
from argos.web.gateway import build_console_app


class CountingEntity(SimEntity):
    """数 pose() 被调几次 —— 用来证明读端点没有去戳执行器。"""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.pose_calls = 0

    def pose(self):
        self.pose_calls += 1
        return super().pose()


class HangingEntity(SimEntity):
    """pose() 卡住 —— 模拟真机上执行器无响应（睡短一点，别拖慢测试退出）。"""

    def pose(self):
        time.sleep(1.5)
        return super().pose()


def _app(entity, tmp_path):
    brain = RobotBrain(executor=entity, memory_path=None)
    app = build_console_app(brain=brain, db_path=str(tmp_path / "c.db"))
    return TestClient(app), app.state.console, brain


# ── TODO 2：last-value 快照 ────────────────────────────

def test_read_endpoints_use_snapshot_not_executor(tmp_path):
    """tick 写过快照之后，读端点一次都不再戳执行器。"""
    c, console, brain = _app(CountingEntity(), tmp_path)
    console.tick_sink(brain.tick())            # 一帧 → 写快照
    before = brain.executor.pose_calls
    assert before >= 1
    assert c.get("/api/robot/state").status_code == 200
    assert c.get("/api/robot/telemetry").status_code == 200
    assert brain.executor.pose_calls == before


def test_snapshot_falls_back_to_live_read_without_tick(tmp_path):
    """回归：从没 tick 过 → 仍如实返回执行器数据（旧行为不变）。"""
    c, _, _ = _app(SimEntity(), tmp_path)
    st = c.get("/api/robot/state").json()
    assert st["battery"] is not None
    assert st["connection"]["status"] == "connected"


def test_snapshot_reflects_latest_frame(tmp_path):
    """快照每帧刷新：动了之后读到的就是新位置。"""
    c, console, brain = _app(SimEntity(), tmp_path)
    console.tick_sink(None)                    # 记下原点
    brain.executor.move_to(1.5, 2.5, 0.0)
    console.tick_sink(None)                    # 再记一帧
    body = c.get("/api/robot/state").json()
    assert body["pose"]["x"] == 1.5
    assert body["pose"]["y"] == 2.5


def test_snapshot_keeps_honest_nulls(tmp_path):
    """加了快照也不能补假值：没有的传感器仍是 null。"""
    c, console, brain = _app(SimEntity(), tmp_path)
    console.tick_sink(brain.tick())
    body = c.get("/api/robot/telemetry").json()
    assert body["battery"] is not None
    assert body["temperature"] is None
    assert body["cpu"] is None


# ── TODO 3：读超时降级 ────────────────────────────────

def test_read_endpoint_degrades_when_executor_hangs(tmp_path, monkeypatch):
    """executor 卡死 → 端点返回断连骨架（HTTP 200），不是 500、也不是真实数据。

    ⚠️ 这里**故意不断言端到端耗时**：TestClient 是同步封装，请求收尾会等那个
    被取消、却仍在跑的 to_thread 线程，把 0.2s 的超时放大成 executor 的完整卡顿
    时长。超时"是否真的不等"由下面那条直接调 `_read_or` 的用例来钉。
    """
    monkeypatch.setenv("ARGOS_READ_TIMEOUT", "0.2")
    c, _, _ = _app(HangingEntity(), tmp_path)
    r = c.get("/api/robot/state")
    assert r.status_code == 200
    body = r.json()
    assert body["connection"]["status"] == "disconnected"     # 走的是降级骨架
    assert body["battery"] is None


def test_read_or_times_out_without_waiting(monkeypatch):
    """钉超时本身：`_read_or` 不等慢读完成就返回降级值。"""
    monkeypatch.setenv("ARGOS_READ_TIMEOUT", "0.2")

    def slow():
        time.sleep(1.5)
        return "live"

    async def scenario():
        """在 loop **内部**量耗时 —— `asyncio.run` 收尾会 join 默认线程池
        （等 slow 跑完），在外面量会把 0.2s 的超时错测成 1.5s。"""
        t0 = time.time()
        got = await _read_or(slow, lambda: "fallback")
        return got, time.time() - t0

    got, elapsed = asyncio.run(scenario())
    assert got == "fallback"
    assert elapsed < 0.9


def test_telemetry_endpoint_degrades_to_nulls(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_READ_TIMEOUT", "0.2")
    c, _, _ = _app(HangingEntity(), tmp_path)
    body = c.get("/api/robot/telemetry").json()
    assert body["battery"] is None
    assert body["temperature"] is None


def test_estop_unaffected_by_hanging_executor(tmp_path, monkeypatch):
    """回归钉：执行器卡死时急停仍立刻可用 —— 读端点被卡不能拖住安全路径。"""
    monkeypatch.setenv("ARGOS_READ_TIMEOUT", "0.2")
    c, _, brain = _app(HangingEntity(), tmp_path)
    t0 = time.time()
    r = c.post("/api/safety/estop", json={"on": True})
    assert r.status_code == 200
    assert time.time() - t0 < 1.0
    assert brain.backend.gate.estop is True
