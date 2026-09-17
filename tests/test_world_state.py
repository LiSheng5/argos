"""WorldState 测试（Phase 2）。

钉两条边界：
  1. WorldState 是唯一真相源，含指令要求的字段，写入 bump 版本号；
  2. **给 Planner 的一律是不可变投影**（改就抛错）—— 这是旧系统"谁都能改世界"的解药。
"""
import dataclasses

import pytest

from argos.agent.interfaces import Observation, Pose
from argos.world.state import from_observation, view
from argos.world.mini_world import build_default_world


def test_world_state_has_required_fields():
    """指令第五节要求的字段：robot/battery/obstacles/objects/locations/people/events/tasks/time。"""
    w = build_default_world()
    st = from_observation(Observation(robot_pose=Pose(0, 0, 0), battery=80.0))
    assert st.robot == Pose(0, 0, 0)
    assert st.battery == 80.0
    for name in ("obstacles", "objects", "locations", "people", "events", "tasks"):
        assert hasattr(st, name)
    assert st.sim_time == 0.0
    assert w.name == "mini_world"


def test_write_bumps_version():
    st = from_observation(Observation())
    v0 = st.version
    st.robot = Pose(1.0, 2.0, 0.0)
    st.touch()
    assert st.version == v0 + 1


def test_view_is_frozen():
    """Planner 拿到的投影改不了 —— 想改世界必须先经过 backend。"""
    st = from_observation(Observation(robot_pose=Pose(0, 0, 0)))
    v = view(st)
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.robot = Pose(9, 9, 0)


def test_view_downgrades_dicts_to_tuples():
    st = from_observation(Observation())
    st.obstacles["o1"] = "rect"
    st.locations["home"] = Pose()
    v = view(st)
    assert isinstance(v.obstacles, tuple)
    assert isinstance(v.locations, tuple)


def test_view_location_lookup_returns_none_when_missing():
    """查不到就返回 None，不抛、不瞎猜坐标。"""
    v = view(from_observation(Observation()))
    assert v.location("不存在的地点") is None


def test_from_observation_roundtrip():
    obs = Observation(robot_pose=Pose(1.0, 2.0, 0.5), battery=55.0, sim_time=3.0,
                      events=("a",), tasks=("t",))
    st = from_observation(obs)
    back = view(st)
    assert back.robot == Pose(1.0, 2.0, 0.5)
    assert back.battery == 55.0
    assert back.sim_time == 3.0
    assert back.events == ("a",)
