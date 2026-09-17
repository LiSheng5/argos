"""SimulatorBackend 测试（Phase 1 + 3）。

覆盖：能力声明 / 观察 / 移动 / 撞障碍 / 转向 / 等待 / 观察环境 / 无机械臂诚实失败 /
急停经闸 / **同 seed 可复现** / 两条路线的通行性。

⚠️ 全部是**仿真**，不碰任何硬件。
"""
from argos.agent.interfaces import Action, ActionKind, FailReason, Pose
from argos.backends.simulator_backend import SimulatorBackend
from argos.world.mini_world import build_default_world


def _backend(**kw):
    return SimulatorBackend(seed=42, **kw)


def test_capabilities_are_declared():
    """Brain 不许假设能力，只能读 —— 这里确认读得到。"""
    caps = _backend().capabilities()
    assert ActionKind.MOVE in caps.actions
    assert caps.has_arm is False          # 迷你世界没有手臂，如实声明
    assert caps.max_speed > 0


def test_observe_returns_readonly_projection():
    obs = _backend().observe()
    assert obs.robot_pose == Pose(0.0, 0.0, 0.0)   # 起点 room_a
    assert obs.battery == 100.0
    assert obs.obstacles                             # 世界里有障碍


def test_move_changes_pose_and_advances_time():
    b = _backend()
    v0 = b.state.version
    res = b.apply(Action(ActionKind.MOVE, {"x": 2.0, "y": 0.0}))
    assert res.ok is True
    assert b.observe().robot_pose.x == 2.0
    assert b.state.sim_time > 0
    assert b.state.version > v0            # 写过世界，版本号必须涨


def test_move_blocked_by_obstacle_and_does_not_move():
    """撞障碍 → OBSTACLE_BLOCKED，而且**真的没动**（诚实）。"""
    b = _backend()
    before = b.observe().robot_pose
    # north_block 占 x∈[4,6], y∈[1.25,2.75]；从 (3,2) 走到 (7,2) 必撞
    b.entity._pose = Pose(3.0, 2.0, 0.0)
    res = b.apply(Action(ActionKind.MOVE, {"x": 7.0, "y": 2.0}))
    assert res.ok is False
    assert res.reason is FailReason.OBSTACLE_BLOCKED
    assert b.observe().robot_pose == Pose(3.0, 2.0, 0.0)
    assert res.learnable is True          # 值得学习的失败


def test_turn_changes_yaw():
    b = _backend()
    res = b.apply(Action(ActionKind.TURN, {"yaw": 1.5708}))
    assert res.ok is True
    assert abs(b.observe().robot_pose.yaw - 1.5708) < 1e-6


def test_wait_advances_sim_time():
    b = _backend()
    t0 = b.state.sim_time
    b.apply(Action(ActionKind.WAIT, {"duration": 2.0}))
    assert b.state.sim_time >= t0 + 2.0


def test_inspect_reports_current_room():
    b = _backend()
    res = b.apply(Action(ActionKind.INSPECT, {}))
    assert res.ok is True
    assert "room_a" in res.detail


def test_grab_fails_honestly_without_arm():
    """没手臂就如实说，不假装成功（对齐旧 real_sport 的诚实传统）。"""
    b = _backend()
    res = b.apply(Action(ActionKind.GRAB, {"target": "cup"}))
    assert res.ok is False
    assert res.reason is FailReason.SAFETY_REJECTED   # 闸门先拦：能力白名单里没有


def test_estop_goes_through_gate():
    b = _backend()
    b.estop(True)
    res = b.apply(Action(ActionKind.MOVE, {"x": 1.0, "y": 0.0}))
    assert res.ok is False
    assert res.reason is FailReason.SAFETY_REJECTED
    assert res.learnable is False          # 被闸拒 ≠ 世界给的经验


def test_north_route_blocked_south_route_open():
    """世界几何成立：北线有障碍，南线通 —— 这是反思换路线的物理前提。"""
    w = build_default_world()
    north = w.route("north")
    south = w.route("south")
    assert north and south
    # 北线第二段 (2,2)→(5,2) 撞 north_block
    assert w.blocked(2.0, 2.0, 5.0, 2.0) == "north_block"
    # 南线全程畅通
    pts = [(0.0, 0.0)] + [(p.x, p.y) for p in south]
    for a, bb in zip(pts, pts[1:]):
        assert w.blocked(a[0], a[1], bb[0], bb[1]) is None


def test_same_seed_is_reproducible():
    """同 seed 两次跑出完全一样的 sim_time —— benchmark 可重复的前提。"""
    def run():
        b = SimulatorBackend(seed=7)
        b.apply(Action(ActionKind.MOVE, {"x": 2.0, "y": 0.0}))
        b.apply(Action(ActionKind.TURN, {"yaw": 1.0}))
        b.apply(Action(ActionKind.WAIT, {"duration": 1.0}))
        return round(b.state.sim_time, 9), round(b.state.battery, 9)
    assert run() == run()


def test_out_of_bounds_move_rejected_by_gate():
    b = _backend()
    res = b.apply(Action(ActionKind.MOVE, {"x": 999.0, "y": 0.0}))
    assert res.ok is False
    assert res.reason is FailReason.SAFETY_REJECTED
