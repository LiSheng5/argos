"""RealSportEntity 的闭环逻辑测试 —— 无真机也能跑，所以现在就得测。

高层接口只有"速度" Move(vx, vy, vyaw)，没有"走到坐标"。所以"走到某点"
是我们自己写的一个闭环：读位姿 → 算速度 → 读到点为止。这里用一只
**假狗**（按收到的速度积分出位姿）把整套闭环跑起来看它收不收敛。

覆盖：转向方向、角度归一化、到点判据、卡住放弃、超时放弃、急停中断。
真机连接那几行（connect_sport / sportmode_pose_source）**不在此测试范围内** ——
没真机，验不了，接口上标了未验证。
"""
import math

from robot.real_sport import DriveCfg, RealSportEntity, _norm_deg, plan_drive


def _norm(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


class FakeDog:
    """一只假狗：按收到的速度积分出位姿（无噪声）。"""

    def __init__(self, x: float = 0.0, y: float = 0.0, yaw: float = 0.0) -> None:
        self.x, self.y, self.yaw = x, y, yaw

    def step(self, vx: float, vy: float, vyaw: float, dt: float) -> None:
        self.yaw = _norm(self.yaw + math.degrees(vyaw) * dt)
        r = math.radians(self.yaw)
        self.x += (vx * math.cos(r) - vy * math.sin(r)) * dt
        self.y += (vx * math.sin(r) + vy * math.cos(r)) * dt

    def pose(self) -> dict:
        return {"x": self.x, "y": self.y, "yaw": self.yaw, "battery_pct": 100.0}


class FakeSport:
    """假执行器：记下每条速度指令，并把狗往前推进一步。"""

    def __init__(self, dog: FakeDog, dt: float = 0.05) -> None:
        self.dog, self.dt = dog, dt
        self.cmds = []
        self.stopped = 0

    def Move(self, vx: float, vy: float, vyaw: float) -> None:
        self.cmds.append((vx, vy, vyaw))
        self.dog.step(vx, vy, vyaw, self.dt)

    def StopMove(self) -> None:
        self.stopped += 1


def _entity(dog: FakeDog, dt: float = 0.05, **cfg_kw) -> tuple:
    sport = FakeSport(dog, dt)
    cfg = DriveCfg(dt=dt, **cfg_kw)
    return RealSportEntity(sport=sport, pose=dog.pose, cfg=cfg,
                           sleep=lambda _s: None), sport


# ── plan_drive：纯逻辑 ────────────────────────────────

def test_facing_target_drives_straight():
    cmd = plan_drive({"x": 0, "y": 0, "yaw": 0}, 2.0, 0.0, 0.0)
    assert cmd is not None and cmd[0] > 0 and abs(cmd[2]) < 1e-6   # 前进、不转


def test_target_behind_turns_first():
    cmd = plan_drive({"x": 0, "y": 0, "yaw": 0}, -2.0, 0.0, 0.0)
    assert cmd is not None and cmd[0] == 0.0 and abs(cmd[2]) > 0   # 先原地转


def test_at_position_only_aligns_yaw():
    assert plan_drive({"x": 0, "y": 0, "yaw": 0}, 0.0, 0.0, 90.0)[2] > 0
    assert plan_drive({"x": 0, "y": 0, "yaw": 90}, 0.0, 0.0, 90.0) is None


def test_yaw_error_is_normalized():
    # 350° → 10° 应该转 +20°，不是 -340°
    cmd = plan_drive({"x": 0, "y": 0, "yaw": 350}, 0.0, 0.0, 10.0)
    assert cmd is not None and cmd[2] > 0
    assert _norm_deg(10 - 350) == 20.0


def test_speed_and_yaw_are_capped():
    cfg = DriveCfg()
    cmd = plan_drive({"x": 0, "y": 0, "yaw": 0}, 100.0, 0.0, 0.0, cfg)
    assert cmd[0] <= cfg.max_speed
    cmd = plan_drive({"x": 0, "y": 0, "yaw": 0}, 0.0, 100.0, 0.0, cfg)
    assert abs(cmd[2]) <= cfg.max_yaw_rate


# ── 闭环：喂假狗，看它收不收敛 ──────────────────────────

def test_closed_loop_walks_to_target():
    dog = FakeDog()
    e, sport = _entity(dog)
    assert e.move_to(2.0, 0.0, 0.0) is True
    assert math.hypot(dog.x - 2.0, dog.y) <= DriveCfg().arrive_tol
    assert sport.stopped >= 1                       # 到点确实停了


def test_closed_loop_turns_around_when_target_is_behind():
    dog = FakeDog(yaw=0.0)
    e, _ = _entity(dog)
    assert e.move_to(-2.0, 0.0, 180.0) is True
    assert abs(dog.x - (-2.0)) <= DriveCfg().arrive_tol
    assert abs(_norm(dog.yaw - 180.0)) <= DriveCfg().yaw_tol


def test_closed_loop_reaches_diagonal_target():
    dog = FakeDog()
    e, _ = _entity(dog)
    assert e.move_to(2.0, 2.0, 0.0) is True
    assert math.hypot(dog.x - 2.0, dog.y - 2.0) <= DriveCfg().arrive_tol


def test_navigate_walks_every_waypoint():
    dog = FakeDog()
    e, _ = _entity(dog)
    assert e.navigate([{"x": 1.0, "y": 0.0}, {"x": 1.0, "y": 1.0}]) is True
    assert math.hypot(dog.x - 1.0, dog.y - 1.0) <= DriveCfg().arrive_tol


# ── 失败路径：都要诚实停下并返回 False ────────────────────

def test_stuck_gives_up_and_stops():
    class FrozenDog(FakeDog):
        def step(self, vx, vy, vyaw, dt):
            pass                                   # 推不动（撞墙 / 被卡住）
    dog = FrozenDog()
    e, sport = _entity(dog, stuck_frames=5)
    assert e.move_to(5.0, 0.0) is False
    assert sport.stopped >= 1                      # 放弃了但记得停下


def test_timeout_gives_up_and_stops():
    dog = FakeDog()
    e, sport = _entity(dog, timeout=0.0)           # 时限 0 → 一帧都走不了
    assert e.move_to(5.0, 0.0) is False
    assert sport.stopped >= 1


def test_estop_interrupts_the_walk():
    dog = FakeDog()
    sport = FakeSport(dog, 0.05)
    box, calls = {}, [0]

    def pose():
        calls[0] += 1
        if calls[0] >= 3:
            box["e"].estop()                       # 走到第三步按下急停
        return dog.pose()

    e = RealSportEntity(sport=sport, pose=pose, sleep=lambda _s: None)
    box["e"] = e
    assert e.move_to(5.0, 0.0) is False
    assert sport.stopped >= 1                      # 急停必须真的把速度收掉
    assert e.pose()["estop"] is True


def test_estop_blocks_further_moves_until_cleared():
    dog = FakeDog()
    e, sport = _entity(dog)
    e.estop()
    assert e.move_to(2.0, 0.0) is False
    e.clear_estop()
    assert e.move_to(2.0, 0.0) is True


# ── 没装的东西要诚实说没有 ──────────────────────────────

def test_grab_release_honestly_fail_without_arm():
    dog = FakeDog()
    e, _ = _entity(dog)
    assert e.grab("杯子") is False and e.release() is False
