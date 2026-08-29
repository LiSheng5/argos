"""机器人安全闸门 SafetyGate 测试 — 对应 npc 的 test_reviewer/test_security。"""
from robot.safety import SafetyGate


def test_whitelist_rejects_unknown_action():
    gate = SafetyGate()
    ok, reason = gate.check("delete", {}, {"battery_pct": 100})
    assert not ok and "不允许" in reason


def test_forbidden_fields_rejected():
    gate = SafetyGate()
    ok, _ = gate.check("move_to", {"x": 1, "y": 2, "file": "x"}, {"battery_pct": 100})
    assert not ok


def test_estop_blocks_all():
    gate = SafetyGate()
    gate.set_estop(True)
    ok, reason = gate.check("move_to", {"x": 1, "y": 2}, {"battery_pct": 100})
    assert not ok and "急停" in reason


def test_battery_gate_limits_navigate():
    gate = SafetyGate()
    assert gate.check("navigate", {"waypoints": [{"x": 5, "y": 5}]}, {"battery_pct": 15})[0] is False
    assert gate.check("move_to", {"x": 1, "y": 1}, {"battery_pct": 8})[0] is True  # 低电量仍允许安全原语


def test_boundary_rejects_out_of_range():
    gate = SafetyGate()
    ok, _ = gate.check("move_to", {"x": 99, "y": 0}, {"battery_pct": 100})
    assert not ok