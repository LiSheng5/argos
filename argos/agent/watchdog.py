"""AgentWatchdog —— 让"大脑还在跟上吗"变成可观测、会动作的东西（Phase 5）。

旧的 `argos/watchdog.py::LinkWatchdog` 只活在 `RealSportEntity` 内部、只看状态帧心跳，
**和 SafetyGate 没有任何联动**（跳闸不会拦动作）。这里补上三件事：

  1. 同时盯 **心跳 / 单次动作耗时 / 后端响应** 三类超时；
  2. 一旦跳闸 → **强制安全停止**（清速度）并让闸门拒绝后续动作（fail-closed，须显式 reset）；
  3. 留下 `WATCHDOG_TRIGGERED` 事件 —— 指令第十二节要求的那条记录。

时间一律用**逻辑时钟**（`sim_time`），不用 `time.time()`：否则同 seed 不可复现。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

__all__ = ["AgentWatchdog"]

TRIGGER_TAG = "WATCHDOG_TRIGGERED"


@dataclass
class AgentWatchdog:
    heartbeat_timeout_s: float = 5.0     # 多久没有心跳算失联
    action_timeout_s: float = 10.0       # 单次动作最长允许耗时
    backend_timeout_s: float = 20.0      # 后端整体最长允许耗时
    tripped: bool = False
    events: List[str] = field(default_factory=list)
    _last_beat: Optional[float] = None
    _action_start: Optional[float] = None
    _backend_start: Optional[float] = None

    # ---- 打点 ----
    def beat(self, t: float) -> None:
        self._last_beat = t

    def begin_action(self, t: float) -> None:
        self._action_start = t
        if self._backend_start is None:
            self._backend_start = t

    # ---- 判据 ----
    def check_heartbeat(self, t: float) -> Optional[str]:
        if self._last_beat is None:
            return None
        if (t - self._last_beat) > self.heartbeat_timeout_s:
            return f"心跳超时（{(t - self._last_beat):.1f}s > {self.heartbeat_timeout_s}s）"
        return None

    def check_action(self, t: float) -> Optional[str]:
        if self._action_start is None:
            return None
        if (t - self._action_start) > self.action_timeout_s:
            return f"动作超时（{(t - self._action_start):.1f}s > {self.action_timeout_s}s）"
        return None

    def check_backend(self, t: float) -> Optional[str]:
        if self._backend_start is None:
            return None
        if (t - self._backend_start) > self.backend_timeout_s:
            return f"后端超时（{(t - self._backend_start):.1f}s > {self.backend_timeout_s}s）"
        return None

    def check(self, t: float) -> Optional[str]:
        """顺序：心跳 → 动作 → 后端。返回第一个超时原因。"""
        return (self.check_heartbeat(t) or self.check_action(t) or self.check_backend(t))

    def end_action(self, t: float) -> None:
        self._action_start = None

    def end_backend(self, t: float) -> None:
        self._backend_start = None

    # ---- 跳闸 ----
    def trip(self, why: str) -> None:
        self.tripped = True
        self.events.append(f"{TRIGGER_TAG}: {why}")

    def reset(self) -> None:
        """**不会自动恢复** —— 断过一次就该停下来被人看一眼。"""
        self.tripped = False
        self._last_beat = None
        self._action_start = None
        self._backend_start = None
