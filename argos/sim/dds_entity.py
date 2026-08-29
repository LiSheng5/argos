"""DDS 电机级执行器 DdsEntity（v1 = 直线巡逻员）。

指令走 DDS（rt/lowcmd，和真机同一条总线）；位姿读同进程 DdsSim 的
frame_pos / imu_quat 传感器（真机版 M3 换 SLAM 里程计，协议不变）。

实测结论（trot 调参实验室，物理仿真 6 秒/组）：
  - trot 步态 freq=2.0Hz、thigh 摆幅 0.25、calf 折叠 0.8、Kp80/Kd4：
    沿世界 -x 直线 ~0.7m/s 稳定行走，z 稳定不摔；
  - 整体相位 +π 不改变行进方向（接触动力学决定，非运动学对称）；
  - 左右差频转向只单向有效，左右反相差动会摔 → v1 不转弯。
所以 v1 只接"身体行走轴上的目标"：目标在行走轴上 → 分段 trot 走到即停；
不在轴上（要转弯/掉头）→ 诚实返回 False（大脑记"没做成"），不硬走。
"""
from __future__ import annotations

import math
import time
from typing import Dict, List, Optional

from argos.sim.dds_sim import STAND_DOWN, STAND_UP, DdsSim

# 实测步态参数（见模块 docstring）
FREQ, AT, AC, KP, KD = 2.0, 0.25, 0.8, 80.0, 4.0
WALK_DIR = -1.0          # 行走轴方向（世界系）：当前步态沿 -x
TROT_HZ = 200.0          # lowcmd 下发频率
STAND_SECONDS = 2.5      # 首次行动先起立（官方节奏）
BURST_SECONDS = 1.5      # 每段 trot 时长（段间核对位姿）
# 两个轴的能力完全不同，所以用两个容差：
ARRIVE_TOL_X = 0.25      # 纵向（行走轴）：分段自适应能控住，实测误差 ~0.2m
ARRIVE_TOL_Y = 0.8       # 横向：**v1 不会转向，这个轴根本控不了**
                         # 实测走 2m 侧向漂 0.20 / 0.57 / 0.69（随机），
                         # 所以 0.8 是**能力上限**，不是目标。
                         # ⚠ 能转向之后必须收严到 0.25，并加航向闭环与横向纠偏。
MAX_LATERAL = 1.0        # 横向超过这个就停下放弃（再走下去就是撞墙）
MAX_YAW_DRIFT = 30.0     # 航向漂移上限（度）：转过头就停 —— 见下
WALK_TIMEOUT = 15.0      # 单次 move_to 总时限


def heading_drifted(pose: Dict, yaw0: float,
                    budget: float = MAX_YAW_DRIFT) -> bool:
    """航向漂出预算？这是**比横向位移更早**的失控信号。

    实测（2026-08-29，4 次走 1m）：航向漂 1.4° / 19.9° / **163.2°** / **85.3°**。
    最后那两次狗已经不是"走偏"，是在打转 —— 而等到横向位移超预算才发现，
    它已经跑出去 3.6m 了。所以这里单独看航向，转过头立刻收。
    """
    d = abs(float(pose.get("yaw", 0.0)) - yaw0) % 360.0
    return min(d, 360.0 - d) > budget


def arrived(pose: Dict, x: float, y: float,
            tol_x: float = ARRIVE_TOL_X, tol_y: float = ARRIVE_TOL_Y) -> bool:
    """到点判据：**x 和 y 都要**在各自容差内。

    2026-08-29 改：原来只看 x 轴，于是侧向漂了 1.2m 也照样算"到了"
    （实测走 4m 漂 1.2m）。判据太松比没有判据更危险 —— 它会让上层以为一切正常。
    """
    return (abs(x - float(pose.get("x", 0.0))) <= tol_x
            and abs(y - float(pose.get("y", 0.0))) <= tol_y)


def drifted(pose: Dict, y: float, budget: float = MAX_LATERAL) -> bool:
    """横向漂移是否超出预算。超了就别再走了 —— v1 不会转弯，走下去只会更偏。"""
    return abs(float(pose.get("y", 0.0)) - y) > budget
# 腿序 0-2 FL, 3-5 FR, 6-8 RL, 9-11 RR；对角小跑 = FL+RR 对 FR+RL
PHASE = [0.0] * 3 + [math.pi] * 3 + [math.pi] * 3 + [0.0] * 3


class DdsEntity:
    """实现 RobotExecutor 协议。用法：DdsEntity()（自建无头仿真并起立待命）。"""

    def __init__(self, sim: Optional[DdsSim] = None) -> None:
        from unitree_sdk2py.core.channel import (ChannelFactoryInitialize,
                                                 ChannelPublisher)
        from unitree_sdk2py.idl.unitree_go.msg.dds_ import LowCmd_
        self._sim = sim if sim is not None else DdsSim()
        ChannelFactoryInitialize(1)
        self._pub = ChannelPublisher("rt/lowcmd", LowCmd_)
        self._pub.Init()
        self._sim.start()
        self._estop = False
        self._stood = False
        self._gripper = None

    # ── 协议：位姿 ────────────────────────────────────

    def pose(self) -> Dict:
        import mujoco
        m, d = self._sim.model, self._sim.data
        pa = m.sensor_adr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SENSOR, "frame_pos")]
        qa = m.sensor_adr[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SENSOR, "imu_quat")]
        q = d.sensordata[qa:qa + 4]
        yaw = math.degrees(math.atan2(2 * (q[0] * q[3] + q[1] * q[2]),
                                      1 - 2 * (q[2] * q[2] + q[3] * q[3])))
        # battery_pct：仿真恒满电。真机版换 SLAM 里程计时必须接真实电量 ——
        # 缺这个字段安全闸会按"电量未知"降级（只放行安全原语），不会再默认满电。
        return {"x": float(d.sensordata[pa]), "y": float(d.sensordata[pa + 1]),
                "yaw": yaw, "battery_pct": 100.0,
                "estop": self._estop, "gripper": self._gripper}

    # ── 协议：运动 ────────────────────────────────────

    def move_to(self, x: float, y: float, yaw: float = 0.0,
                max_lateral: float = MAX_LATERAL) -> bool:
        """直线走到 (x, y)：目标须在行走轴上（横向差 ≤ 预算且方向沿 WALK_DIR），
        否则 False（v1 还不会转弯）。

        走到 x/y 都进容差 → True。中途横向漂出预算 → **立刻停下**并返回 False
        （v1 纠不回来，硬走只会更偏，别浪费剩下的 WALK_TIMEOUT）。超时同理。
        """
        if self._estop:
            return False
        p = self.pose()
        # 已经站在目标上 → 直接算到了
        # （2026-08-29 修：原来没有这一档，"回充电桩"而狗已在桩边会被判成
        #   方向不对 → 返回 False → 记一条"没做成"，纯属冤枉。）
        if arrived(p, x, y):
            return True
        if drifted(p, y, max_lateral) or (x - p["x"]) * WALK_DIR <= 0:
            return False                      # 要转弯/掉头，或起始横向偏差已超预算
        if not self._stood:
            self._stand()
        yaw0 = self.pose()["yaw"]      # 航向基准：走的过程中转过头就收
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < WALK_TIMEOUT:
            cur = self.pose()
            if arrived(cur, x, y):
                return True
            if heading_drifted(cur, yaw0):     # 打转了，比等位移偏更早发现
                return False
            if drifted(cur, y, max_lateral):   # 横向漂出预算：停下，诚实放弃
                return False
            if self._estop:
                return False
            # 分段长度按剩余距离自适应（远大步近小步，防过冲——不能倒着走回来）
            dist = abs(x - cur["x"])
            self._trot(min(1.5, max(0.4, dist / 0.7 * 0.8)))
        return arrived(self.pose(), x, y)

    def navigate(self, waypoints: List[Dict],
                 max_lateral: float = MAX_LATERAL) -> bool:
        for wp in waypoints:
            if not self.move_to(float(wp["x"]), float(wp.get("y", 0.0)),
                                float(wp.get("yaw", 0.0)), max_lateral):
                return False
        return True

    def grab(self, target: str) -> bool:
        return False                          # v1 没装手臂，诚实失败

    def release(self) -> bool:
        return False

    def estop(self) -> None:
        self._estop = True                    # 停发指令 → 关节保持，物理上站定

    def clear_estop(self) -> None:
        self._estop = False

    # ── 内部：起立 / trot 一段 ─────────────────────────

    def _stand(self) -> None:
        cmd = self._new_cmd()
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < STAND_SECONDS:
            if self._estop:                   # 起立途中也能停
                self._stood = False
                return
            ph = math.tanh((time.perf_counter() - t0) / 1.2)
            for i in range(12):
                cmd.motor_cmd[i].q = ph * STAND_UP[i] + (1 - ph) * STAND_DOWN[i]
            self._pub.Write(cmd)
            time.sleep(1.0 / TROT_HZ)
        self._stood = True

    def _trot(self, seconds: float) -> None:
        cmd = self._new_cmd()
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < seconds:
            if self._estop:                   # 段内中断：急停不该等这一整段跑完
                return
            t = time.perf_counter() - t0
            for leg in range(4):
                w = 2 * math.pi * FREQ
                s = math.tanh(2.5 * math.sin(w * t + PHASE[leg * 3]))
                hip, thigh, calf = STAND_UP[leg * 3: leg * 3 + 3]
                cmd.motor_cmd[leg * 3].q = hip + 0.05 * math.sin(w * t + PHASE[leg * 3])
                cmd.motor_cmd[leg * 3 + 1].q = thigh + AT * s
                cmd.motor_cmd[leg * 3 + 2].q = calf - AC * max(0.0, s)
            self._pub.Write(cmd)
            time.sleep(1.0 / TROT_HZ)

    def _new_cmd(self):
        from unitree_sdk2py.idl.default import unitree_go_msg_dds__LowCmd_
        cmd = unitree_go_msg_dds__LowCmd_()
        cmd.head[0], cmd.head[1], cmd.level_flag = 0xFE, 0xEF, 0xFF
        for i in range(20):
            cmd.motor_cmd[i].mode = 0x01
            cmd.motor_cmd[i].kp, cmd.motor_cmd[i].kd = KP, KD
        return cmd
