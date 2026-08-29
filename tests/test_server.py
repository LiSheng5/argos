"""server 冒烟：四个端点 + Origin 校验。
tick 循环在 lifespan 里，TestClient 不进 with 上下文则不启动（确定性），
需要推进时直接打 app.state.brain.tick()。
"""
from fastapi.testclient import TestClient

from argos.brain import RobotBrain
from argos.server import build_app
from argos.sim.stub import SimEntity


def _client() -> TestClient:
    brain = RobotBrain(executor=SimEntity(), memory_path=None)
    return TestClient(build_app(brain))


def test_command_books_and_state_shows_pose():
    c = _client()
    r = c.post("/api/command", json={"text": "去门口"})
    assert r.status_code == 200
    assert "门口" in r.json()["reply"]
    c.app.state.brain.tick()               # 手动推一帧
    st = c.get("/api/state").json()
    assert (st["pose"]["x"], st["pose"]["y"]) == (4.0, 4.0)
    assert st["tick"] == 1


def test_state_and_memory_endpoints():
    c = _client()
    c.post("/api/command", json={"text": "拿小球"})
    c.app.state.brain.tick()
    st = c.get("/api/state").json()
    assert st["state"] == "idle" and any("小球" in m["content"] for m in st["memory"])
    mem = c.get("/api/memory").json()["entries"]
    assert any(m["content"].startswith("完成: ") for m in mem)


def test_command_rejects_empty_text():
    c = _client()
    assert c.post("/api/command", json={"text": "  "}).status_code == 400
    assert c.post("/api/command", content=b"not json",
                  headers={"Content-Type": "application/json"}).status_code == 400


def test_command_accepts_gbk_body():
    # Windows shell 把中文发成 GBK 字节 —— 服务端兜底解码，skill 的 curl 才能直接用
    c = _client()
    r = c.post("/api/command", content='{"text":"去门口"}'.encode("gbk"),
               headers={"Content-Type": "application/json"})
    assert r.status_code == 200 and "门口" in r.json()["reply"]


def test_estop_blocks_new_commands():
    c = _client()
    assert c.post("/api/estop", json={"on": True}).json()["estop"] is True
    assert "做不了" in c.post("/api/command", json={"text": "去门口"}).json()["reply"]
    assert c.post("/api/estop", json={"on": False}).json()["estop"] is False
    assert "门口" in c.post("/api/command", json={"text": "去门口"}).json()["reply"]


def test_origin_check():
    c = _client()
    assert c.get("/api/state",
                 headers={"Origin": "http://evil.com"}).status_code == 403
    assert c.get("/api/state",
                 headers={"Origin": "http://127.0.0.1:5500"}).status_code == 200
    assert c.get("/api/state").status_code == 200     # 无 Origin(curl/脚本)放行
