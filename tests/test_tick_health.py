"""tick 健康门测试（借鉴 Microduck：看循环有没有跟上频率，而不是进程还活着）。

纯逻辑用假时钟（不用真等超时）；端点用例走 build_console_app 装配
（/api/system/health 是 web 层 register 的端点）；最后一条钉"接线真的通了"。
"""
import time

from fastapi.testclient import TestClient

from argos.brain import RobotBrain
from argos.sim.stub import SimEntity
from argos.web.gateway import build_console_app
from argos.web.health import TickTracker


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _tracker(clock=None, window: int = 60) -> TickTracker:
    return TickTracker(window=window, clock=clock or FakeClock())


# ── 四态判定 ──────────────────────────────────────────

def test_idle_before_first_frame():
    """还没跑过帧 → idle（不能谎报 ok）。"""
    t = _tracker()
    assert t.status() == "idle"
    snap = t.snapshot()
    assert snap["lastTickAgeMs"] is None
    assert snap["lastFrameMs"] is None
    assert snap["slowFrames"] == 0


def test_ok_when_frames_beat_the_interval():
    clock = FakeClock()
    t = _tracker(clock)
    t.record(12.0, 3000.0)          # 12ms 远小于 3s 间隔
    clock.advance(1.0)
    assert t.status() == "ok"
    snap = t.snapshot()
    assert snap["lastFrameMs"] == 12.0
    assert snap["intervalMs"] == 3000.0
    assert snap["slowFrames"] == 0
    assert snap["lastTickAgeMs"] == 1000.0


def test_degraded_after_a_slow_frame():
    clock = FakeClock()
    t = _tracker(clock)
    t.record(5000.0, 3000.0)        # 单帧 5s > 3s 间隔 → 慢帧
    clock.advance(1.0)
    assert t.status() == "degraded"
    assert t.snapshot()["slowFrames"] == 1


def test_stalled_when_no_frame_for_too_long():
    clock = FakeClock()
    t = _tracker(clock)
    t.record(10.0, 3000.0)
    clock.advance(9.1)              # 超过 3 × 3s 没出帧
    assert t.status() == "stalled"


def test_record_ignores_bad_input():
    """脏数据不写进统计，也不会把 tracker 弄崩。"""
    t = _tracker()
    t.record(None, 3000.0)
    t.record("nope", 3000.0)
    assert t.status() == "idle"


def test_window_keeps_recent_frames_only():
    t = _tracker(window=3)
    for ms in (1.0, 2.0, 3.0, 4.0):
        t.record(ms, 3000.0)
    snap = t.snapshot()
    assert snap["window"] == 3
    assert snap["lastFrameMs"] == 4.0
    assert snap["avgFrameMs"] == 3.0             # (2+3+4)/3


# ── 端点（走真实装配）─────────────────────────────────

def _console(tmp_path, tracker=None) -> TestClient:
    brain = RobotBrain(executor=SimEntity(), memory_path=None)
    app = build_console_app(brain=brain, db_path=str(tmp_path / "console.db"),
                            tracker=tracker)
    return TestClient(app)


def test_health_endpoint_reports_tracker(tmp_path):
    clock = FakeClock()
    tracker = TickTracker(clock=clock)
    tracker.record(20.0, 3000.0)
    clock.advance(1.0)
    body = _console(tmp_path, tracker).get("/api/system/health").json()
    assert body["status"] == "ok"
    assert body["lastFrameMs"] == 20.0
    assert body["slowFrames"] == 0


def test_health_endpoint_keeps_old_shape_without_tracker(tmp_path):
    """回归钉：未启用健康门时端点仍是旧形状，老调用方不受影响。"""
    c = _console(tmp_path)
    c.app.state.tick_tracker = None
    body = c.get("/api/system/health").json()
    assert body["status"] == "ok"
    assert set(body.keys()) == {"status", "ts"}


def test_tick_loop_feeds_tracker(tmp_path, monkeypatch):
    """接线钉：tick 循环真的在喂 tracker（不是只挂了个空对象）。"""
    monkeypatch.setenv("ROBOT_TICK_INTERVAL", "0.02")
    tracker = TickTracker()
    c = _console(tmp_path, tracker)
    with c:                                   # 进 with → lifespan 启动 tick 循环
        time.sleep(0.5)
        body = c.get("/api/system/health").json()
    assert body["window"] >= 1
    assert body["status"] in ("ok", "degraded")


def test_console_health_reflects_tracker(tmp_path):
    """Console.health() 把 tracker 的状态透出去（WS 推给前端的就是它）。"""
    clock = FakeClock()
    tracker = TickTracker(clock=clock)
    brain = RobotBrain(executor=SimEntity(), memory_path=None)
    app = build_console_app(brain=brain, db_path=str(tmp_path / "c.db"),
                            tracker=tracker)
    console = app.state.console
    assert console.health()["status"] == "idle"        # 还没跑过一帧
    tracker.record(10.0, 3000.0)
    clock.advance(1.0)
    body = console.health()
    assert body["status"] == "ok"
    assert body["lastFrameMs"] == 10.0


def test_console_health_unknown_without_tracker(tmp_path):
    """没挂 tracker → unknown（诚实，不谎报 ok）。"""
    brain = RobotBrain(executor=SimEntity(), memory_path=None)
    app = build_console_app(brain=brain, db_path=str(tmp_path / "c.db"))
    app.state.console.tick_tracker = None
    assert app.state.console.health()["status"] == "unknown"
