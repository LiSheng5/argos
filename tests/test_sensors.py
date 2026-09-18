"""感知层测试（Wave 3 / 指令 §19）。

钉两件事，都是原来测不了的：

  1. **传感器会失灵 → 闸门 fail-closed**：拿不到定位/电量就不许移动（宁可不动，不猜）；
  2. **感知有范围 → 只能撞了才知道**：看不见的障碍**照样会挡住你**，
     这正是"只能靠试错学"成立的条件（也就是反思闭环存在的理由）。
"""
import pytest

from argos.agent.gate import ActionGate
from argos.agent.interfaces import Action, ActionKind, FailReason
from argos.backends.simulator_backend import SimulatorBackend
from argos.sensors import (
    SimBatterySensor,
    SimObstacleSensor,
    SimPoseSensor,
    SimVisionSensor,
    simulated_suite,
    suite_of,
)
from argos.sensors.base import SensorSuite


def _move(x=1.0, y=0.0):
    return Action(ActionKind.MOVE, {"x": x, "y": y})


def _stop():
    return Action(ActionKind.STOP, {})


# ---------- 回归锚：不配传感器 = 从前的行为 ----------

def test_no_sensors_means_ground_truth_observation():
    b = SimulatorBackend(seed=1)
    assert b.sensors is None
    obs = b.observe()
    assert obs.missing == ()
    assert obs.obstacles                    # 上帝视角：看得见障碍
    assert b.apply(_move()).ok is True


def test_missing_field_defaults_empty_everywhere():
    from argos.agent.interfaces import Observation, WorldState
    from argos.world.state import from_observation, view
    assert Observation().missing == ()
    assert WorldState().missing == ()
    assert view(WorldState()).missing == ()
    assert from_observation(Observation()).missing == ()


# ---------- 传感器失灵 → 闸门 fail-closed ----------

def test_pose_dropout_blocks_motion_but_allows_stop():
    suite = SensorSuite(sensors=[SimPoseSensor(dropout=1.0)])
    b = SimulatorBackend(seed=1, sensors=suite)

    res = b.apply(_move())
    assert res.ok is False
    assert res.reason is FailReason.SAFETY_REJECTED
    assert "pose" in res.detail and "fail-closed" in res.detail
    # 安全动作不能被自己锁死
    assert b.apply(_stop()).ok is True


def test_battery_dropout_blocks_motion():
    suite = SensorSuite(sensors=[SimBatterySensor(dropout=1.0)])
    b = SimulatorBackend(seed=1, sensors=suite)
    res = b.apply(_move())
    assert res.ok is False
    assert "battery" in res.detail


def test_inspect_and_wait_are_not_blocked_by_missing_data():
    suite = suite_of(SimPoseSensor(dropout=1.0), SimBatterySensor(dropout=1.0))
    b = SimulatorBackend(seed=1, sensors=suite)
    assert b.apply(Action(ActionKind.INSPECT, {})).ok is True
    assert b.apply(Action(ActionKind.WAIT, {"duration": 0.5})).ok is True


def test_gate_rejects_motion_when_data_missing():
    """闸门单独测：缺数据是 fail-closed，且**不归成"低电量"**（未知 ≠ 低）。"""
    from argos.agent.interfaces import Pose, WorldState
    gate = ActionGate(SimulatorBackend(seed=1).capabilities())
    w = WorldState(robot=Pose(), battery=100.0, missing=("pose",))
    ok, reason, detail = gate.check(_move(), w)
    assert (ok, reason) == (False, FailReason.SAFETY_REJECTED)
    assert "缺数据" in detail


def test_missing_is_visible_to_brain_and_planner_view():
    """缺数据要能一路传到 Planner 的只读视图里 —— 别让它以为一切正常。"""
    from argos.world.state import from_observation, view
    from argos.agent.interfaces import Observation
    v = view(from_observation(Observation(missing=("obstacle",))))
    assert v.missing == ("obstacle",)


# ---------- 感知有范围：撞了才知道 ----------

def test_range_limited_perception_hides_far_obstacle_but_world_still_blocks():
    """★ 关键一条：看不见 ≠ 挡不住。agent 必须靠试错学（这正是闭环的存在理由）。"""
    suite = suite_of(SimObstacleSensor(radius_m=1.0))      # 只看得见 1 米内
    b = SimulatorBackend(seed=1, sensors=suite)

    assert b.observe().obstacles == ()                     # 起点看不见 north_block
    # 但世界照样挡：北线第二个途经点在障碍里
    b.apply(_move(2.0, 2.0))
    res = b.apply(_move(5.0, 2.0))
    assert res.ok is False
    assert res.reason is FailReason.OBSTACLE_BLOCKED


def test_perception_radius_boundary_is_exact():
    """半径边界要精确：从 (2,2) 到 north_block 中心 (6, 2.75) 约 4.07m。

    （半径怎么算写在传感器里：障碍用**中心点**距离，不是最近边距离。）
    """
    def see(radius: float) -> bool:
        b = SimulatorBackend(seed=1, sensors=suite_of(SimObstacleSensor(radius_m=radius)))
        b.apply(_move(2.0, 2.0))
        return bool(b.observe().obstacles)

    assert see(4.0) is False        # 4.0 < 4.07 → 差一点，看不见
    assert see(4.5) is True         # 够近了，看得见


def test_vision_is_range_limited_and_returns_visible_spots():
    suite = suite_of(SimVisionSensor(radius_m=1.0))
    b = SimulatorBackend(seed=1, sensors=suite)
    near = b.observe().objects
    assert any("room_a" in str(x) for x in near)           # 脚下的房间看得见
    assert not any("room_b" in str(x) for x in near)       # 远处房间看不见


# ---------- 传感器"不完美"要可复现 ----------

def test_pose_noise_is_seed_reproducible():
    def run(seed):
        b = SimulatorBackend(seed=seed, sensors=suite_of(SimPoseSensor(noise_m=0.2)))
        b.apply(Action(ActionKind.WAIT, {"duration": 0.1}))
        return round(b.observe().robot_pose.x, 9)
    assert run(7) == run(7)


def test_battery_quantisation_steps():
    b = SimulatorBackend(seed=1, sensors=suite_of(SimBatterySensor(step_pct=5.0)))
    b.apply(Action(ActionKind.MOVE, {"x": 1.0, "y": 0.0}))
    val = b.observe().battery
    assert val % 5.0 == 0.0


def test_suite_records_per_sensor_readings():
    suite = suite_of(SimPoseSensor(dropout=1.0), SimBatterySensor())
    b = SimulatorBackend(seed=1, sensors=suite)
    b.apply(_stop())
    names = {r.name: r.ok for r in b.last_readings}
    assert names == {"pose": False, "battery": True}
    assert "pose" in b.observe().missing and "battery" not in b.observe().missing


def test_simulated_suite_has_the_four_declared_sensors():
    names = [s.name for s in simulated_suite(seed=1)]
    assert names == ["pose", "battery", "obstacle", "vision"]


def test_missing_is_recomputed_each_action():
    """上一轮读到了、这一轮没读到 → missing 必须跟着变（不能粘住）。"""
    suite = suite_of(SimVisionSensor(radius_m=1.0))
    b = SimulatorBackend(seed=1, sensors=suite)
    b.apply(_stop())
    assert b.observe().missing == ()
