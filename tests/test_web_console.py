"""ArgOS Web Console 测试（Step 3-8）。

钉三件事：
  1. **原有四个端点与大脑行为没被破坏**（这是"不为 Web 重构 ArgOS"的保险丝）；
  2. Run 全链路：指令 → 落账 → tick 推进 → completed / rejected 都如实记录；
  3. 控制路径必须过 SafetyGate：急停置位后下单必定被拒。

用临时 SQLite 库，测完不留脏数据。TestClient 不进 with 上下文 → 不启动
tick 循环，帧由测试手动推（确定性，与 test_server.py 同款取舍）。
"""
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from argos.brain import RobotBrain
from argos.sim.stub import SimEntity
from argos.web.gateway import build_console_app


@pytest.fixture()
def env(tmp_path):
    brain = RobotBrain(executor=SimEntity(), memory_path=None)
    db = str(tmp_path / "console.db")
    app = build_console_app(brain=brain, db_path=db)
    client = TestClient(app)
    return client, app.state.console, brain


# ── 原有行为没被破坏 ────────────────────────────────────

def test_legacy_endpoints_still_work(env):
    c, console, brain = env
    r = c.post("/api/command", json={"text": "去门口"})
    assert r.status_code == 200 and "门口" in r.json()["reply"]
    st = c.get("/api/state").json()
    assert st["state"] == "idle"
    assert isinstance(c.get("/api/memory").json()["entries"], list)
    assert c.post("/api/estop", json={"on": False}).json()["ok"] is True


def test_backend_wrapped_but_behaviour_identical(env):
    """包装 brain.backend 只为埋点，执行结果必须一模一样。"""
    c, console, brain = env
    assert brain.backend.__class__.__name__ == "InstrumentedBackend"
    ok, reason = brain.backend.apply("move_to", {"x": 1.0, "y": 2.0})
    assert ok is True
    assert (brain.executor.pose()["x"], brain.executor.pose()["y"]) == (1.0, 2.0)


# ── Run 全链路 ──────────────────────────────────────────

def test_command_creates_run_and_completes(env):
    c, console, brain = env
    r = c.post("/api/runs", json={"text": "去门口"})
    assert r.status_code == 200
    run = r.json()
    assert run["status"] == "running"
    assert run["command"] == "去门口"
    stages = {s["key"]: s["status"] for s in run["stages"]}
    assert stages["input"] == "done"
    assert stages["brain"] == "done"
    assert stages["safety"] == "done"
    assert stages["task"] == "running"
    # 没配 key 时 LLM 这一节必须如实标 skipped，不能假装调用过
    assert stages["llm"] == "skipped"

    console.tick_sink(brain.tick())            # 手动推一帧
    got = c.get(f"/api/runs/{run['id']}").json()
    assert got["run"]["status"] == "completed"
    assert {s["key"]: s["status"] for s in got["run"]["stages"]}["robot"] == "done"
    assert got["events"]                        # 有事件留存


def test_unknown_command_is_rejected_honestly(env):
    c, console, brain = env
    run = c.post("/api/runs", json={"text": "写个文件"}).json()
    assert run["status"] == "rejected"
    assert "我不认识" in (run["reply"] or "")


def test_run_list_and_events_persist(env):
    c, console, brain = env
    c.post("/api/runs", json={"text": "去门口"})
    console.tick_sink(brain.tick())
    assert len(c.get("/api/runs").json()["runs"]) >= 1
    types = [e["type"] for e in c.get("/api/events").json()["events"]]
    assert "command.received" in types
    assert "task.completed" in types


# ── 控制必须过 SafetyGate ───────────────────────────────

def test_estop_blocks_new_runs_and_reaches_executor(env):
    c, console, brain = env
    c.post("/api/safety/estop", json={"on": True})
    assert brain.backend.gate.estop is True         # 闸门
    assert brain.executor.pose()["estop"] is True   # 执行器也收到（P0-1）
    run = c.post("/api/runs", json={"text": "巡逻一圈"}).json()
    assert run["status"] == "rejected"
    assert "急停" in (run["reply"] or "")
    c.post("/api/safety/estop", json={"on": False})


# ── 机器人外观图 ────────────────────────────────────────

def test_robot_image_upload_replace_and_remove(env):
    c, console, brain = env
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    up = c.post("/api/robot/image", files={"file": ("dog.png", png, "image/png")})
    assert up.status_code == 200
    url = up.json()["imageUrl"]
    assert url.startswith("/api/robot/image/")

    bad = c.post("/api/robot/image",
                 files={"file": ("x.png", b"definitely not an image", "image/png")})
    assert bad.status_code == 400                     # magic bytes 不认

    assert c.get(url).status_code == 200              # 能取回
    assert c.delete("/api/robot/image").json()["imageUrl"] is None


# ── 遥测：没有的数据就是 null ────────────────────────────

def test_telemetry_reports_null_for_missing_sensors(env):
    c, console, brain = env
    st = c.get("/api/robot/state").json()
    assert st["battery"] is not None                 # 执行器有电量
    assert st["temperature"] is None                 # 没有这个传感器
    assert st["cpu"] is None
    assert st["connection"]["status"] == "connected"


# ── WebSocket ───────────────────────────────────────────

def test_websocket_snapshot_and_events(env):
    c, console, brain = env
    with c.websocket_connect("/api/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"
        assert "robot" in msg["data"] and "safety" in msg["data"]
        console.bus.emit("system.online", "System", "test event")
        # telemetry 也在 5Hz 推 robot.state，所以这里要挑出事件那条
        got = None
        for _ in range(10):
            msg = ws.receive_json()
            if msg["type"] == "event.created":
                got = msg
                break
        assert got is not None and got["data"]["type"] == "system.online"


def test_camera_none_by_default(env):
    c, console, brain = env
    st = c.get("/api/camera").json()
    assert st["mode"] == "none" and st["available"] is False
    assert c.get("/api/camera/stream.mjpg").status_code == 404
