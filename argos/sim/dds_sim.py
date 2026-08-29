"""无头 DDS 仿真：unitree_mujoco 官方桥 + MuJoCo 物理步进（不开 3D 窗口）。

和官方 simulate_python/unitree_mujoco.py 同一套桥（UnitreeSdk2Bridge）：
订阅 rt/lowcmd 做 PD 落关节，发布 rt/lowstate、rt/sportmodestate。
差异只有三处：不开 viewer 窗口（无头可测）；DDS 不指定网口（Windows 没有 "lo"，
自动探测）；导入桥前注入纯线程版 RecurrentThread（官方版依赖 Linux timerfd，
Windows 直接炸，见 _install_recurrent_thread_shim）。上游文件一字不动。

用法: python -m argos.sim.dds_sim    （Ctrl+C 停）
依赖: pip install pygame mujoco cyclonedds==11.0.1
      pip install -e sim/unitree_sdk2_python --no-deps   （跳过钉死的 cyclonedds==0.10.2）
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

_SIM_DIR = Path(__file__).resolve().parent / "unitree_mujoco" / "simulate_python"
_DOMAIN = 1            # 官方仿真约定 domain 1（真机/SDK 示例同款）
_DT = 0.005            # 物理步长，与官方 config.SIMULATE_DT 一致


def _install_recurrent_thread_shim() -> None:
    """unitree_sdk2py.utils.timerfd 用 Linux 专属 timerfd（ctypes.CDLL(None) 在
    Windows 上 TypeError）。在导入桥之前注入同名纯线程版 RecurrentThread，
    只影响本进程、语义与官方一致（单次失败不炸线程，Wait = 停止）；
    上游文件不动，Linux 上无需注入也自然不冲突。"""
    import types

    mod = types.ModuleType("unitree_sdk2py.utils.thread")

    class Thread:
        def __init__(self, target=None, name=None, args=(), kwargs=None):
            self._target, self._args, self._kwargs = target, args, (kwargs or {})
            self._thread = threading.Thread(target=self._run, name=name, daemon=True)

        def _run(self) -> None:
            self._target(*self._args, **self._kwargs)

        def Start(self) -> None:
            self._thread.start()

        def Wait(self, timeout: float | None = None) -> None:
            self._thread.join(timeout)

    class RecurrentThread(Thread):
        def __init__(self, interval: float = 1.0, target=None, name=None,
                     args=(), kwargs=None):
            super().__init__(target=self._loop, name=name)
            self._interval, self._loop_target = interval, target
            self._loop_args, self._loop_kwargs = args, (kwargs or {})
            self._quit = threading.Event()

        def _loop(self) -> None:
            while not self._quit.is_set():
                try:
                    self._loop_target(*self._loop_args, **self._loop_kwargs)
                except Exception as exc:          # 官方语义：单次失败打印不炸线程
                    print(f"[RecurrentThread] target func raise exception: {exc}")
                self._quit.wait(self._interval)

        def Wait(self, timeout: float | None = None) -> None:
            self._quit.set()
            super().Wait(timeout)

    mod.Thread, mod.RecurrentThread = Thread, RecurrentThread
    sys.modules.setdefault("unitree_sdk2py.utils.thread", mod)


class DdsSim:
    """一台仿真狗：加载 go2 mjcf，桥接 DDS，物理步进到 stop()。"""

    def __init__(self, robot: str = "go2", domain: int = _DOMAIN) -> None:
        if str(_SIM_DIR) not in sys.path:
            sys.path.insert(0, str(_SIM_DIR))   # 桥和它的 config.py 都在那边
        _install_recurrent_thread_shim()        # 必须先于桥的导入
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize
        ChannelFactoryInitialize(domain)        # 已初始化则内部自动跳过
        import mujoco
        xml = (Path(__file__).resolve().parent / "unitree_mujoco"
               / "unitree_robots" / robot / "scene.xml")
        self.model = mujoco.MjModel.from_xml_path(str(xml))
        self.data = mujoco.MjData(self.model)
        self.model.opt.timestep = _DT
        from unitree_sdk2py_bridge import UnitreeSdk2Bridge
        self.bridge = UnitreeSdk2Bridge(self.model, self.data)
        self._stop = threading.Event()

    def _loop(self) -> None:
        import mujoco
        while not self._stop.is_set():
            mujoco.mj_step(self.model, self.data)
            time.sleep(_DT)                     # 1x 实时（同官方主循环节奏）

    def start(self) -> threading.Thread:
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()


# 官方 stand_go2 同款关节角：FL/FR/RL/RR 四条腿 × hip/thigh/calf
STAND_UP = [0.00571868, 0.608813, -1.21763] * 4
STAND_DOWN = [0.0473455, 1.22187, -2.44375] * 4


def _selftest() -> None:
    """闭环自检：DDS 发站立序列 → 物理仿真起立 → lowstate 校验关节逼近目标。

    独立进程跑：cyclonedds 原生库在解释器退出时会段错误（线程清理老毛病），
    pytest 只认本函数打印的 DDS_STAND_OK，崩溃不污染测试结果。
    """
    import math

    from unitree_sdk2py.core.channel import (ChannelFactoryInitialize,
                                             ChannelPublisher, ChannelSubscriber)
    from unitree_sdk2py.idl.default import unitree_go_msg_dds__LowCmd_
    from unitree_sdk2py.idl.unitree_go.msg.dds_ import LowCmd_, LowState_

    ChannelFactoryInitialize(_DOMAIN)
    latest: dict = {}
    sub = ChannelSubscriber("rt/lowstate", LowState_)
    sub.Init(lambda m: latest.update(q=[m.motor_state[i].q for i in range(12)]), 0)
    pub = ChannelPublisher("rt/lowcmd", LowCmd_)
    pub.Init()
    time.sleep(0.5)                     # 等参与者互相发现

    sim = DdsSim()
    try:
        sim.start()
        time.sleep(1.0)                 # 等桥的 lowstate 发布线程转起来
        cmd = unitree_go_msg_dds__LowCmd_()
        cmd.head[0], cmd.head[1] = 0xFE, 0xEF
        cmd.level_flag = 0xFF
        for i in range(20):
            cmd.motor_cmd[i].mode = 0x01
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 4.0:
            # 官方节奏：tanh 插值趴下→站立，Kp 20→50，Kd 3.5，500Hz
            phase = math.tanh((time.perf_counter() - t0) / 1.2)
            for i in range(12):
                mc = cmd.motor_cmd[i]
                mc.q = phase * STAND_UP[i] + (1 - phase) * STAND_DOWN[i]
                mc.kp = phase * 50.0 + (1 - phase) * 20.0
                mc.dq, mc.kd, mc.tau = 0.0, 3.5, 0.0
            pub.Write(cmd)
            time.sleep(0.002)
        time.sleep(1.5)                 # 站稳
    finally:
        sim.stop()

    assert latest.get("q") is not None, "没收到 rt/lowstate（DDS 链路未通）"
    worst = max(abs(latest["q"][i] - STAND_UP[i]) for i in range(12))
    assert worst < 0.3, f"关节角未逼近站立目标：最大偏差 {worst:.3f} rad"
    print(f"DDS_STAND_OK 最大关节偏差 {worst:.3f} rad")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="无头 DDS 仿真（unitree_mujoco 桥）")
    ap.add_argument("--selftest", action="store_true",
                    help="闭环自检：rt/lowcmd 发站立序列，rt/lowstate 校验关节到位")
    args = ap.parse_args()
    if args.selftest:
        _selftest()
    else:
        print(f"无头 DDS 仿真运行中（domain {_DOMAIN}）：rt/lowcmd 受控，Ctrl+C 停")
        sim = DdsSim()
        try:
            sim.start().join()
        except KeyboardInterrupt:
            sim.stop()
