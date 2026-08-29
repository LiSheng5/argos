"""链路看门狗 LinkWatchdog —— 防"断线了狗还一直走"。

## 为什么必须有这个

高层 `SportClient.Move(vx, vy, vyaw)` 是**持续生效**的速度指令：发一次，狗就一直按
这个速度走，直到你发下一条（或 StopMove）。

于是有个真实风险：

    下发 Move(0.4, 0, 0) → Wi-Fi / 以太网断了
    → 狗收不到"停"
    → 它沿着 0.4 m/s 一直走下去，直到撞墙或电池耗尽

软件急停救不了这个场景 —— **没人发得了急停**（链路断了），狗也收不到。
所以必须有个"多久没收到状态帧就自己停"的兜底，而且这个兜底在狗那侧
（或至少在一个还在跑的进程里）。

## 设计

- `beat()` —— 每收到一帧状态就打一次卡（由 pose 源的回调驱动）
- `check()` —— 超时没打卡 → **只触发一次** `on_trip`（通常是 StopMove），之后一直报"不在线"
- 时钟可注入 → 单测不用真的等超时

## 诚实说明

这只是**软件层的**兜底。真机上它挡不住"进程被杀 / 电脑蓝屏 / 狗端死机"。
物理急停（遥控器 / 急停按钮）和有人在场，仍然是第一道防线，见
`机器人/真机安全清单.md`。
"""
from __future__ import annotations

import time
from typing import Callable, Optional


class LinkWatchdog:
    """状态帧停了 = 链路断了 → 让狗停下。"""

    def __init__(self, timeout: float = 1.0,
                 on_trip: Optional[Callable[[], None]] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if timeout <= 0:
            raise ValueError("timeout 必须为正数")
        self.timeout = float(timeout)
        self.on_trip = on_trip
        self._clock = clock
        self._last = self._clock()
        self._tripped = False

    def beat(self) -> None:
        """收到一帧新状态就打一次卡。

        注意：**打卡不会解除已经触发的跳闸**。断过一次就停着等人来看，
        自动恢复行走太危险（链路可能只是闪断，狗却已经走到别处去了）。
        要继续必须显式 `reset()`，由上层（人）决定。
        """
        self._last = self._clock()

    def alive(self) -> bool:
        """链路是否还活着（只看时间，不触发 on_trip）。"""
        return self._clock() - self._last <= self.timeout

    def check(self) -> bool:
        """检查链路；断线则触发一次 on_trip，之后**一直**返回 False 直到 reset()。"""
        if self.alive() and not self._tripped:
            return True
        if not self._tripped:
            self._tripped = True
            if self.on_trip is not None:
                try:
                    self.on_trip()
                except Exception as exc:            # 兜底本身不能把调用方带崩
                    print(f"[LinkWatchdog] on_trip 回调失败：{exc}")
        return False

    def reset(self) -> None:
        """显式复位 —— 人确认安全、重新接管之后才该调。

        看门狗跳闸后不会自己恢复，这是故意的：断过一次就该停下来等人。
        """
        self._last = self._clock()
        self._tripped = False
