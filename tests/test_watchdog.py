"""链路看门狗 + 真机执行器的"任何异常都要先收速"保证。

场景：高层 Move(vx, vy, vyaw) 是**持续生效**的。链路一断，狗收不到"停"，
会沿着最后一条速度一直走。软件急停救不了这个（没人发得了），
所以必须有"多久没收到状态帧就自己停"的兜底。

时钟全部注入假时钟 —— 不真的等超时，测试跑得快也不会偶发失败。
"""
import math
import time

from argos.real_sport import DriveCfg, RealSportEntity
from argos.watchdog import LinkWatchdog


class Clock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class Dog:
    def __init__(self) -> None:
        self.x = self.y = self.yaw = 0.0

    def step(self, vx, vy, vyaw, dt) -> None:
        self.yaw += math.degrees(vyaw) * dt
        r = math.radians(self.yaw)
        self.x += (vx * math.cos(r) - vy * math.sin(r)) * dt
        self.y += (vx * math.sin(r) + vy * math.cos(r)) * dt

    def pose(self) -> dict:
        return {"x": self.x, "y": self.y, "yaw": self.yaw, "battery_pct": 100.0}


class Sport:
    def __init__(self, dog: Dog) -> None:
        self.dog, self.stopped, self.last = dog, 0, (0.0, 0.0, 0.0)

    def Move(self, vx, vy, vyaw) -> None:
        self.last = (vx, vy, vyaw)
        self.dog.step(vx, vy, vyaw, 0.05)

    def StopMove(self) -> None:
        self.stopped += 1
        self.last = (0.0, 0.0, 0.0)


# ── LinkWatchdog 本体 ────────────────────────────────

def test_alive_while_beating():
    clk = Clock()
    wd = LinkWatchdog(timeout=1.0, clock=clk)
    for _ in range(5):
        clk.advance(0.3)
        wd.beat()
        assert wd.check() is True


def test_trip_after_silence_calls_on_trip_once():
    clk, trips = Clock(), []
    wd = LinkWatchdog(timeout=1.0, on_trip=lambda: trips.append(1), clock=clk)
    wd.beat()
    clk.advance(1.5)
    assert wd.check() is False
    assert wd.check() is False                 # 再查也不重复触发
    assert len(trips) == 1                     # on_trip 只调一次


def test_trip_is_sticky_until_explicit_reset():
    """跳闸后不会自己恢复 —— 断过一次就该停下来等人来看。

    （第一版是 beat() 自动解除，跟"不建议自动恢复行走"的原则自相矛盾，已改掉。）
    """
    clk, trips = Clock(), []
    wd = LinkWatchdog(timeout=1.0, on_trip=lambda: trips.append(1), clock=clk)
    wd.beat()
    clk.advance(2.0)
    assert wd.check() is False

    wd.beat()                                  # 链路回来了，但…
    assert wd.check() is False                 # …不该自己恢复
    assert wd.alive() is True

    wd.reset()                                 # 人确认安全后才复位
    assert wd.check() is True
    clk.advance(2.0)
    assert wd.check() is False
    assert len(trips) == 2                     # 再断还能再触发


def test_on_trip_exception_does_not_propagate():
    clk = Clock()
    wd = LinkWatchdog(timeout=0.5, on_trip=lambda: (_ for _ in ()).throw(
        RuntimeError("回调炸了")), clock=clk)
    wd.beat()
    clk.advance(1.0)
    assert wd.check() is False                 # 兜底自己不能把调用方带崩


def test_rejects_non_positive_timeout():
    try:
        LinkWatchdog(timeout=0)
    except ValueError:
        return
    raise AssertionError("timeout <= 0 应该被拒")


# ── 接进执行器：断链要停，崩了也要停 ────────────────────

def _entity_with_watchdog(dog, sport, clk, timeout=0.5):
    wd = LinkWatchdog(timeout=timeout, clock=clk)
    e = RealSportEntity(sport=sport, pose=dog.pose, watchdog=wd,
                        sleep=lambda _s: None)
    return e, wd


def test_link_loss_stops_the_dog_mid_walk():
    """走一半链路断了 → 必须停下并诚实返回 False，不能继续走。"""
    dog, sport, clk = Dog(), Sport(Dog()), Clock()
    sport.dog = dog
    e, wd = _entity_with_watchdog(dog, sport, clk, timeout=0.5)
    wd.beat()
    # 让 pose 源在第一帧之后就不再打卡（模拟状态帧停了）
    clk.advance(1.0)
    assert e.move_to(5.0, 0.0) is False
    assert sport.stopped >= 1
    assert sport.last == (0.0, 0.0, 0.0)       # 速度确实收掉了


def test_exception_still_halts():
    """循环中途炸了，finally 也要把速度收掉 —— 否则狗带着最后一条速度狂奔。"""

    class ExplodingSport(Sport):
        def __init__(self, dog, after: int):
            super().__init__(dog)
            self.n, self.after = 0, after

        def Move(self, vx, vy, vyaw) -> None:
            self.n += 1
            super().Move(vx, vy, vyaw)
            if self.n >= self.after:
                raise RuntimeError("链路异常")

    dog = Dog()
    sport = ExplodingSport(dog, after=2)
    e = RealSportEntity(sport=sport, pose=dog.pose, sleep=lambda _s: None)
    try:
        e.move_to(5.0, 0.0)
        raise AssertionError("应该把异常抛出来")
    except RuntimeError:
        pass
    assert sport.stopped >= 1                  # 关键：炸了也停了


def test_watchdog_off_by_default_when_injected():
    """注入假执行器（测试场景）默认不开看门狗，不然所有测试都会被超时打断。"""
    dog = Dog()
    sport = Sport(dog)
    e = RealSportEntity(sport=sport, pose=dog.pose, sleep=lambda _s: None)
    assert e._wd is None
    assert e.move_to(1.0, 0.0) is True
