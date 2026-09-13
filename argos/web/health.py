"""Tick 健康追踪（健康门，借鉴 Microduck 的"看循环有没有跟上频率"）。

## 为什么需要

原来 `/api/system/health` 恒返回 `{"status": "ok"}` —— 它回答的是"进程还在不在"，
不是"大脑还在不在转"。真机上如果某个 executor 卡死、或 tick 越来越慢，
界面上没有任何信号。（Microduck 的板端就是靠"健康门"挡这类问题的：
它看的是循环有没有跟上频率，而不是进程还活着。）

## 设计

- `record(ms, interval_ms)` —— server 的 tick 循环每帧调一次（本帧耗时 + 期望帧间隔）
- `snapshot()` / `status()` —— 给 `/api/system/health` 读出去
- 时钟可注入 → 单测不用真的等超时（与 LinkWatchdog 同一套做法）
- **纯观测**：不碰 brain / executor。server 侧只按鸭子类型调 `record()`，
  所以 server.py 不需要 import 本模块（保持"原始层不依赖 web 层"）。
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Dict, Optional

WINDOW = 60          # 保留最近多少帧的耗时
STALE_MULT = 3.0     # 超过 N 倍帧间隔没出帧 → stalled

STATUS_IDLE = "idle"          # 还没跑过一帧（tick 未启动）——诚实，不谎报 ok
STATUS_OK = "ok"              # 帧都按时完成
STATUS_DEGRADED = "degraded"  # 出过慢帧（耗时 > 帧间隔）
STATUS_STALLED = "stalled"    # 太久没出帧 = 大脑可能卡住


class TickTracker:
    """tick 循环的健康记录仪。线程安全（tick 线程写、HTTP 线程读）。"""

    def __init__(self, window: int = WINDOW,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._window = max(1, int(window))
        self._clock = clock
        self._lock = threading.Lock()
        self._frames: deque = deque(maxlen=self._window)   # 每帧耗时 ms
        self._last_at: Optional[float] = None              # 最近一帧完成时刻
        self._interval_ms: float = 0.0
        self._slow: int = 0                                # 累计慢帧数

    # ── 写：由 tick 循环调用 ─────────────────────────────

    def record(self, ms: float, interval_ms: float) -> None:
        """一帧跑完时调用。ms = 本帧耗时，interval_ms = 期望帧间隔。"""
        try:
            ms = float(ms)
            interval_ms = float(interval_ms)
        except (TypeError, ValueError):
            return
        with self._lock:
            self._frames.append(ms)
            self._last_at = self._clock()
            self._interval_ms = interval_ms
            if interval_ms > 0 and ms > interval_ms:
                self._slow += 1

    # ── 读：健康快照 ─────────────────────────────────────

    def snapshot(self) -> Dict:
        """给 /api/system/health 的原始数据（拿不到的一律 None，不编）。"""
        with self._lock:
            n = len(self._frames)
            last_ms = self._frames[-1] if n else None
            avg_ms = (sum(self._frames) / n) if n else None
            last_at = self._last_at
            interval_ms = self._interval_ms
            slow = self._slow
        age_ms = None if last_at is None else (self._clock() - last_at) * 1000.0
        return {
            "lastTickAgeMs": _round(age_ms),
            "lastFrameMs": _round(last_ms),
            "avgFrameMs": _round(avg_ms),
            "intervalMs": _round(interval_ms) if interval_ms else None,
            "slowFrames": slow,
            "window": n,
        }

    def status(self) -> str:
        """ok | idle | degraded | stalled。"""
        with self._lock:
            last_at = self._last_at
            interval_ms = self._interval_ms
            slow = self._slow
        if last_at is None:
            return STATUS_IDLE                     # 没跑过帧 → 不能说 ok
        age_ms = (self._clock() - last_at) * 1000.0
        if interval_ms > 0 and age_ms > interval_ms * STALE_MULT:
            return STATUS_STALLED
        if slow > 0:
            return STATUS_DEGRADED
        return STATUS_OK


def _round(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(float(v), 1)
