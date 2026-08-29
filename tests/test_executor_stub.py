"""RobotBackend + SimEntity(stub) 冒烟 — 离线跑通落账后单步执行 + 安全闸。"""
from robot.backend import RobotBackend
from robot.safety import SafetyGate
from robot.sim.stub import SimEntity


def test_backend_moves_and_poses():
    e = SimEntity(start=(0, 0, 0))
    b = RobotBackend(e)
    ok, _ = b.apply("move_to", {"x": 3, "y": 4, "yaw": 90})
    assert ok and b.observe()["x"] == 3.0


def test_backend_grab_release():
    e = SimEntity()
    b = RobotBackend(e)
    assert b.apply("grab", {"target": "bunzi"})[0]
    assert e.pose()["gripper"] == "bunzi"
    assert b.apply("release", {})[0]
    assert e.pose()["gripper"] is None


def test_backend_gate_blocks_on_estop():
    e = SimEntity()
    g = SafetyGate(); g.set_estop(True)
    b = RobotBackend(e, gate=g)
    ok, reason = b.apply("move_to", {"x": 1, "y": 1})
    assert not ok and "急停" in reason      # 原来这里还留了个 "ji" 拼音兜底分支


def test_backend_estop_reaches_executor():
    """评审 P0-1：急停必须同时置闸门和执行器，不能只置闸门。"""
    e = SimEntity()
    b = RobotBackend(e)
    b.estop()
    assert b.gate.estop is True and e.pose()["estop"] is True
    b.estop(False)
    assert b.gate.estop is False and e.pose()["estop"] is False


def test_navigate_sets_final_pose():
    e = SimEntity(start=(0, 0, 0))
    b = RobotBackend(e)
    assert b.apply("navigate", {"waypoints": [{"x": 1, "y": 1}, {"x": 2, "y": 2}]})[0]
    p = e.pose()
    assert (p["x"], p["y"]) == (2.0, 2.0)