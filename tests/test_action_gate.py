"""ActionGate 测试（Phase 1）。

钉的是"指令第十一条"要的东西：白名单 / 参数范围 / 速度上限 / 超时 / 电量门限 /
急停 / 工作边界，以及最要紧的一条 —— **缺字段必须 fail-closed 拒绝**（旧闸靠 KeyError 兜底）。
"""
import pytest

from argos.agent.gate import ActionGate
from argos.agent.interfaces import (
    Action,
    ActionKind,
    EmbodimentCapabilities,
    FailReason,
    Pose,
    WorldState,
)


def _caps(*kinds, arm=False, speed=0.5):
    return EmbodimentCapabilities(actions=tuple(kinds), has_arm=arm, max_speed=speed)


def _gate(**kw):
    caps = kw.pop("caps", None) or _caps(ActionKind.MOVE, ActionKind.TURN,
                                         ActionKind.STOP, ActionKind.WAIT, ActionKind.INSPECT)
    return ActionGate(caps, **kw)


def _world(**kw):
    base = dict(robot=Pose(), battery=100.0)
    base.update(kw)
    return WorldState(**base)


def test_unknown_action_rejected():
    """不在能力白名单里的动作 → 拒绝（不兜底、不猜测）。"""
    g = _gate(caps=_caps(ActionKind.MOVE))
    ok, reason, _ = g.check(Action(ActionKind.TURN, {"yaw": 1.0}), _world())
    assert ok is False
    assert reason is FailReason.SAFETY_REJECTED


def test_missing_required_field_is_rejected_not_defaulted():
    """缺 y 必须拒绝 —— 绝不能像旧闸那样 `pt.get("y", 0.0)` 默认补 0。"""
    g = _gate()
    ok, reason, detail = g.check(Action(ActionKind.MOVE, {"x": 1.0}), _world())
    assert ok is False
    assert reason is FailReason.INVALID_PARAMS
    assert "y" in detail


def test_non_numeric_param_rejected():
    g = _gate()
    ok, reason, _ = g.check(Action(ActionKind.MOVE, {"x": "abc", "y": 1.0}), _world())
    assert ok is False
    assert reason is FailReason.INVALID_PARAMS


def test_out_of_bounds_rejected():
    g = _gate(boundaries={"x_min": -5, "x_max": 5, "y_min": -5, "y_max": 5})
    ok, reason, _ = g.check(Action(ActionKind.MOVE, {"x": 99.0, "y": 0.0}), _world())
    assert ok is False
    assert reason is FailReason.SAFETY_REJECTED


def test_speed_limit_enforced():
    g = _gate(caps=_caps(ActionKind.MOVE, speed=0.5))
    ok, reason, _ = g.check(Action(ActionKind.MOVE, {"x": 1.0, "y": 0.0, "speed": 3.0}), _world())
    assert ok is False
    assert reason is FailReason.SAFETY_REJECTED


def test_timeout_limit_enforced():
    g = _gate(max_duration=2.0)
    ok, reason, _ = g.check(Action(ActionKind.WAIT, {"duration": 99.0}), _world())
    assert ok is False
    assert reason is FailReason.SAFETY_REJECTED


def test_estop_rejects_everything():
    g = _gate()
    g.set_estop(True)
    ok, reason, _ = g.check(Action(ActionKind.MOVE, {"x": 1.0, "y": 0.0}), _world())
    assert ok is False
    assert reason is FailReason.SAFETY_REJECTED


def test_low_battery_is_learnable_not_gate_rejection():
    """低电量是**世界的真实状态**，要能被学习 —— 不能归成 safety_rejected。"""
    g = _gate(battery_min=10.0)
    ok, reason, _ = g.check(Action(ActionKind.MOVE, {"x": 1.0, "y": 0.0}), _world(battery=5.0))
    assert ok is False
    assert reason is FailReason.BATTERY_LOW
    assert reason is not FailReason.SAFETY_REJECTED


def test_forbidden_field_rejected():
    """禁触字段递归扫描（复用旧闸的 _scan_forbidden）。"""
    g = _gate()
    ok, reason, _ = g.check(
        Action(ActionKind.MOVE, {"x": 1.0, "y": 0.0, "file": "/etc/passwd"}), _world())
    assert ok is False
    assert reason is FailReason.SAFETY_REJECTED


def test_valid_action_passes():
    g = _gate()
    ok, reason, detail = g.check(Action(ActionKind.MOVE, {"x": 1.0, "y": 0.0}), _world())
    assert ok is True
    assert reason is FailReason.OK
    assert detail == ""


def test_no_arm_cannot_grab():
    g = _gate(caps=_caps(ActionKind.MOVE, ActionKind.GRAB, arm=False))
    ok, reason, _ = g.check(Action(ActionKind.GRAB, {"target": "cup"}), _world())
    assert ok is False
    assert reason is FailReason.SAFETY_REJECTED
