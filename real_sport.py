"""真机执行器 RealSportEntity：走宇树高层 SportClient（狗自带小脑负责行走与转向）。

## 为什么需要这个文件

高层接口给的是**速度**不是坐标：
```python
SportClient.Move(vx, vy, vyaw)      # 前/侧移 m/s，转向 rad/s
```
狗不会"走到 (2,0)"，只会"按这个速度动"。所以"走到某点"必须自己闭环：

    读位姿 → 算差多少 → 发速度 → 读位姿 → …… → 到了就停

## 为什么控制逻辑要抽成纯函数

`plan_drive()` 不碰硬件、不 sleep、不读时钟 —— 输入"当前位姿 + 目标"，
输出"这一帧该发什么速度"。于是整套闭环逻辑**现在就能单测**（喂假位姿），
不用等真机。`RealSportEntity` 只负责三件脏活：取真位姿、发真速度、管超时/卡住/急停。

## 现在能验 vs 要等真机

| 部分 | 状态 |
|---|---|
| `plan_drive()` 闭环逻辑 + `RealSportEntity` 的超时/卡住/急停 | ✅ 有单测（喂假位姿 + 假狗） |
| `connect_sport()` / `sportmode_pose_source()` 里那几行连接代码 | ❌ 没真机，未验证；真机到手第一件事就是核字段与单位 |

## 硬件门槛（2026-08-29 查证，宇树官网支持页）

Go2 只有 **X（基础支持）/ EDU（支持）** 开放二次开发，**AIR / PRO 官方不开放**。
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

from robot.watchdog import LinkWatchdog

# ── 闭环参数（真机到手后按实测调；现在的值是保守起步值）──────────


@dataclass(frozen=True)
class DriveCfg:
    arrive_tol: float = 0.25        # 到点判据（米）
    yaw_tol: float = 6.0            # 到位后的朝向容差（度）
    turn_first_tol: float = 15.0    # 朝向差超过这个值就先原地转，不边走边转
    max_speed: float = 0.4          # 最大前进速度 m/s（官方示例用 0.3，保守起步）
    max_yaw_rate: float = 0.8       # 最大转向 rad/s（官方示例用 0.5）
    k_v: float = 0.6                # 距离 → 速度 的比例增益
    k_yaw: float = 0.02             # 朝向误差(度) → 角速度(rad/s)
    dt: float = 0.05                # 闭环周期（秒）
    timeout: float = 30.0           # 单次 move_to 总时限（秒）
    stuck_eps: float = 0.01         # 卡住判据：一帧位移小于它算没动
    stuck_frames: int = 40          # 连续这么多帧没动 → 认定卡住，诚实放弃


def _norm_deg(a: float) -> float:
    """角度归一到 (-180, 180]，避免 350° 的误差被当成 +350 而不是 -10。"""
    return (float(a) + 180.0) % 360.0 - 180.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def plan_drive(cur: Dict, tx: float, ty: float, tyaw: float,
               cfg: DriveCfg = DriveCfg()) -> Optional[Tuple[float, float, float]]:
    """纯逻辑：当前位姿 + 目标 → 这一帧该发的速度 (vx, vy, vyaw)。

    返回 None = 已到位（位置和朝向都在容差内），调用方应停下。
    策略是"先转后走"：朝向差大就原地转，转到位了再直线走、边走边微调朝向。
    侧移（vy）恒为 0 —— 全向横移留给以后，先保证简单可靠。
    """
    dx, dy = tx - float(cur.get("x", 0.0)), ty - float(cur.get("y", 0.0))
    dist = math.hypot(dx, dy)
    yaw_err = _norm_deg(tyaw - float(cur.get("yaw", 0.0)))

    if dist <= cfg.arrive_tol:                       # 位置到了，只剩朝向
        if abs(yaw_err) <= cfg.yaw_tol:
            return None
        return 0.0, 0.0, _clamp(yaw_err * cfg.k_yaw,
                                -cfg.max_yaw_rate, cfg.max_yaw_rate)

    bearing_err = _norm_deg(math.degrees(math.atan2(dy, dx))
                            - float(cur.get("yaw", 0.0)))
    yaw_cmd = _clamp(bearing_err * cfg.k_yaw, -cfg.max_yaw_rate, cfg.max_yaw_rate)
    if abs(bearing_err) > cfg.turn_first_tol:        # 先转，别斜着走
        return 0.0, 0.0, yaw_cmd
    speed = _clamp(dist * cfg.k_v, 0.0, cfg.max_speed)
    return speed, 0.0, yaw_cmd


# ── 真机连接（未验证，等真机）──────────────────────────


def connect_sport(nic: Optional[str] = None):
    """连真机高层接口。没真机会直接抛异常 —— 不静默假装连上了。"""
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    from unitree_sdk2py.go2.sport.sport_client import SportClient
    ChannelFactoryInitialize(0, nic or "")
    sc = SportClient()
    sc.Init()
    return sc


def sportmode_pose_source(
        on_frame: Optional[Callable[[], None]] = None) -> Callable[[], Dict]:
    """订阅 rt/sportmodestate 拿位姿。

    ⚠ 未接真机验证过。已知要点：
      - `position` 是**机体系相对起点的航位推算**，会漂移；要精确得接 L2 SLAM；
      - `imu_state.rpy[2]` 是弧度，本文件统一转成度（跟 stub/dds 的 pose 一致）；
      - **SportModeState 里没有电量** —— 所以下面的 battery 留空，
        安全闸会按"电量未知"只放行 move_to（fail-closed，这是故意的）。
        真机到手要补 BMS 电量源，否则巡逻（navigate）会被一直拒。
    """
    from unitree_sdk2py.core.channel import ChannelSubscriber
    from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_
    latest = {"x": 0.0, "y": 0.0, "yaw": 0.0, "estop": False, "gripper": None}

    def _on(msg) -> None:
        latest["x"] = float(msg.position[0])
        latest["y"] = float(msg.position[1])
        latest["yaw"] = math.degrees(float(msg.imu_state.rpy[2]))
        if on_frame is not None:                   # 给看门狗打卡
            on_frame()

    sub = ChannelSubscriber("rt/sportmodestate", SportModeState_)
    sub.Init(_on, 10)
    return lambda: dict(latest)


# ── 执行器本体 ──────────────────────────────────────


class RealSportEntity:
    """高层执行器。依赖全部可注入，所以无真机也能测闭环逻辑。

        RealSportEntity()                        # 真机：自己去连
        RealSportEntity(sport=fake, pose=dog)    # 测试：喂假的
    """

    def __init__(self, sport=None, pose: Optional[Callable[[], Dict]] = None,
                 nic: Optional[str] = None, cfg: DriveCfg = DriveCfg(),
                 sleep: Callable[[float], None] = time.sleep,
                 watchdog=None, link_timeout: float = 1.0) -> None:
        self.cfg = cfg
        self._sleep = sleep
        self._estop = False
        self._gripper = None
        self._sport: Optional[object] = None

        # 自己去连真机 → 默认开链路看门狗（断线了狗不能一直走）。
        # 注入假执行器 = 测试场景，默认不开（测试想验就自己传 watchdog=）。
        self._standalone = sport is None or pose is None
        self._wd = watchdog
        if self._wd is None and self._standalone and link_timeout > 0:
            self._wd = LinkWatchdog(timeout=link_timeout, on_trip=self._halt)

        if self._standalone:
            pose = pose or sportmode_pose_source(
                on_frame=self._wd.beat if self._wd is not None else None)
        self._sport = sport if sport is not None else connect_sport(nic)
        self._pose_src = pose

    # ── 协议：状态 ──

    def pose(self) -> Dict:
        p = dict(self._pose_src())
        p.setdefault("estop", self._estop)
        p.setdefault("gripper", self._gripper)
        return p

    # ── 协议：运动 ──

    def move_to(self, x: float, y: float, yaw: float = 0.0) -> bool:
        """走到 (x, y, yaw)。到点 True；超时/卡住/急停/断链 → 停下并诚实 False。

        整个循环包在 try/finally：**任何异常都先把速度收掉再往外抛**。
        高层 Move 是持续生效的 —— 循环一崩（异常、Ctrl+C）而没停，
        狗就会带着最后一条速度一直走下去。
        """
        if self._estop:
            return False
        cfg, t0 = self.cfg, time.perf_counter()
        last_dist: Optional[float] = None
        stuck = 0
        try:
            while time.perf_counter() - t0 < cfg.timeout:
                if self._estop:
                    return False
                if self._wd is not None and not self._wd.check():
                    return False                   # 链路断了；check 里已收速
                cur = self.pose()
                cmd = plan_drive(cur, x, y, yaw, cfg)
                if cmd is None:
                    return True                    # 到位（finally 负责停）
                self._send(*cmd)
                dist = math.hypot(x - float(cur.get("x", 0.0)),
                                  y - float(cur.get("y", 0.0)))
                # 卡住判据只在**真的在往前走**时才算（cmd[0] > 0）。
                # 原地转向时位置本来就不变，那不是卡住；到点后调朝向同理。
                if cmd[0] > 0:
                    if last_dist is not None and last_dist - dist < cfg.stuck_eps:
                        stuck += 1                 # 推了但没靠近 → 撞墙 / 被卡
                        if stuck >= cfg.stuck_frames:
                            return False
                    else:
                        stuck = 0
                    last_dist = dist
                self._sleep(cfg.dt)
            return False                           # 超时
        finally:
            self._halt()

    def navigate(self, waypoints) -> bool:
        for wp in waypoints or []:
            if not self.move_to(float(wp.get("x", 0.0)), float(wp.get("y", 0.0)),
                                float(wp.get("yaw", 0.0))):
                return False
        return True

    def grab(self, target: str) -> bool:
        return False            # 没装 D1 机械臂就诚实失败，不假装有

    def release(self) -> bool:
        return False

    def estop(self) -> None:
        self._estop = True
        self._halt()

    def clear_estop(self) -> None:
        self._estop = False

    # ── 内部 ──

    def _send(self, vx: float, vy: float, vyaw: float) -> None:
        self._sport.Move(vx, vy, vyaw)

    def _halt(self) -> None:
        """停下：优先 StopMove（狗自己的急停），兜底发零速。"""
        if self._sport is None:                    # 还没连上，没什么可停的
            return
        stop = getattr(self._sport, "StopMove", None)
        if callable(stop):
            try:
                stop()
                return
            except Exception:
                pass
        try:
            self._sport.Move(0.0, 0.0, 0.0)
        except Exception:
            pass
