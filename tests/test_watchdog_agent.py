"""AgentWatchdog 测试（Phase 5）。

指令第十二节：模拟心跳 / 动作超时 / 执行器超时 / 后端超时，
**last_heartbeat > timeout 时必须安全停止并记录 WATCHDOG_TRIGGERED**。

旧 `watchdog.py` 的病是"跳闸了也不拦动作"（只活在 RealSportEntity 里，与闸无联动）。
这里钉住新行为：跳闸 → 强制安全停止 + 后续动作被拒 + 事件留痕 + **不自动恢复**。
"""
import pytest

from argos.agent.interfaces import Action, ActionKind, FailReason
from argos.agent.watchdog import AgentWatchdog, TRIGGER_TAG
from argos.backends.simulator_backend import SimulatorBackend
from argos.sim.latency import get_profile


def _move(x=0.2):
    return Action(ActionKind.MOVE, {"x": x, "y": 0.0})


def test_heartbeat_timeout_trips_and_records_event():
    """距离上一次完成的动作太久 → 跳闸 + WATCHDOG_TRIGGERED + 安全停止。"""
    wd = AgentWatchdog(heartbeat_timeout_s=1.0, action_timeout_s=999.0)
    b = SimulatorBackend(seed=1, watchdog=wd)
    assert b.apply(_move()).ok is True

    # 让世界空转很久（模拟"循环卡住了，没人打心跳"）
    b.advance_time(50.0)
    res = b.apply(_move(0.4))

    assert res.ok is False
    assert res.reason is FailReason.ACTION_TIMEOUT
    assert wd.tripped is True
    assert any(TRIGGER_TAG in e for e in b.state.events)
    assert any(TRIGGER_TAG in e for e in wd.events)


def test_action_timeout_trips_when_latency_makes_step_too_slow():
    """very_slow 剖面（1s 往返）配 0.5s 动作预算 → 必须判超时。"""
    wd = AgentWatchdog(heartbeat_timeout_s=999.0, action_timeout_s=0.5)
    b = SimulatorBackend(seed=1, watchdog=wd, latency=get_profile("very_slow"))
    res = b.apply(_move())
    assert res.ok is False
    assert res.reason is FailReason.ACTION_TIMEOUT
    assert wd.tripped is True


def test_tripped_rejects_motion_but_allows_stop():
    """fail-closed：跳闸后除 STOP 外一律拒绝。"""
    wd = AgentWatchdog(heartbeat_timeout_s=1.0, action_timeout_s=999.0)
    b = SimulatorBackend(seed=1, watchdog=wd)
    b.apply(_move())
    b.advance_time(50.0)
    b.apply(_move(0.4))                      # 触发跳闸

    blocked = b.apply(_move(0.6))
    assert blocked.ok is False
    assert "跳闸" in blocked.detail

    # STOP 仍然放行（安全动作不被自己挡住）
    assert b.apply(Action(ActionKind.STOP, {})).ok is True


def test_does_not_auto_recover_until_reset():
    wd = AgentWatchdog(heartbeat_timeout_s=1.0, action_timeout_s=999.0)
    b = SimulatorBackend(seed=1, watchdog=wd)
    b.apply(_move())
    b.advance_time(50.0)
    b.apply(_move(0.4))
    assert b.apply(_move(0.6)).ok is False

    b.reset_watchdog()
    assert wd.tripped is False
    assert b.apply(_move(0.6)).ok is True


def test_trip_clears_velocity():
    """跳闸必须真的让它停下 —— 不是只写个标志位。"""
    wd = AgentWatchdog(heartbeat_timeout_s=1.0, action_timeout_s=999.0)
    b = SimulatorBackend(seed=1, watchdog=wd)
    b.apply(Action(ActionKind.MOVE, {"x": 2.0, "y": 0.0}))   # 有速度分量
    assert b.observe().robot_pose.vx != 0.0
    b.advance_time(50.0)
    b.apply(_move(0.4))
    p = b.observe().robot_pose
    assert (p.vx, p.vy, p.vyaw) == (0.0, 0.0, 0.0)


def test_no_watchdog_keeps_old_behaviour():
    """回归锚：不挂看门狗时行为与之前逐字一致。"""
    b = SimulatorBackend(seed=1)
    assert b.watchdog is None
    b.entity.advance(50.0)
    assert b.apply(_move()).ok is True
    assert not any(TRIGGER_TAG in e for e in b.state.events)


def test_backend_timeout_is_checked():
    wd = AgentWatchdog(heartbeat_timeout_s=999.0, action_timeout_s=999.0, backend_timeout_s=1.0)
    wd.begin_action(0.0)
    assert wd.check_backend(0.5) is None
    assert "后端超时" in (wd.check_backend(30.0) or "")
