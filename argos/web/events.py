"""轻量 Event Bus（Step 4）。

为什么要有它：需求 §14 明确反对
    robot.send_to_web(...) / brain.send_to_web(...) / safety.send_to_web(...)
这种"每个模块都认识 WebSocket"的强耦合。正确的做法是各模块只管往总线里
丢事件，谁关心（日志 / Run Store / WS 网关）自己去订阅。

设计约束：
  - 零新依赖，标准库实现；
  - **订阅者异常必须隔离** —— 一个订阅者崩了不能带塌 emit 调用方
    （emit 是在 tick / 命令路径里调的，那里崩了等于狗失控）；
  - 线程安全：emit 可能来自 tick 线程（server 用 to_thread 跑 brain.tick），
    也可能来自请求线程；
  - 自带一个最近事件的环形缓冲：新连上的浏览器能立刻补一段历史，
    不用等下一次事件才有东西可显示。

埋点怎么加（关键：**不改 brain / safety / executor 内部逻辑**）：
  1. safety 裁决 → 包装 brain.backend（见 bridge.py 的 InstrumentedBackend）；
  2. tick 转换 → server 的 tick 循环多带一个可选 sink（默认 None，行为不变）；
  3. 命令 → web 层自己包装 try_command 调用。
这三个都是"在外面套一层"，不是"进去改逻辑"。
"""
from __future__ import annotations

import threading
from collections import deque
from typing import Callable, Deque, List, Optional

from argos.web.models import CAT_SYSTEM, Event, now, uid

Subscriber = Callable[[Event], None]


class EventBus:
    def __init__(self, buffer_size: int = 500) -> None:
        self._subs: List[Subscriber] = []
        self._lock = threading.Lock()
        self._recent: Deque[Event] = deque(maxlen=buffer_size)

    # ── 订阅 ──────────────────────────────────────────

    def subscribe(self, fn: Subscriber) -> Subscriber:
        with self._lock:
            self._subs.append(fn)
        return fn

    def unsubscribe(self, fn: Subscriber) -> None:
        with self._lock:
            self._subs = [f for f in self._subs if f is not fn]

    # ── 发布 ──────────────────────────────────────────

    def emit(self, event_type: str, category: str = CAT_SYSTEM,
             message: str = "", run_id: Optional[str] = None,
             data: Optional[dict] = None) -> Event:
        """发一个事件。返回值方便调用方接着用（比如塞进 Run）。"""
        ev = Event(id=uid("evt"), ts=now(), type=event_type,
                   category=category, message=message, runId=run_id,
                   data=data)
        with self._lock:
            self._recent.append(ev)
            subs = list(self._subs)
        for fn in subs:
            try:
                fn(ev)
            except Exception as exc:                 # 订阅者异常隔离
                print(f"[EventBus] 订阅者异常已隔离：{exc}")
        return ev

    def publish(self, ev: Event) -> Event:
        """已经构造好的 Event 直接发（内部转换用）。"""
        with self._lock:
            self._recent.append(ev)
            subs = list(self._subs)
        for fn in subs:
            try:
                fn(ev)
            except Exception as exc:
                print(f"[EventBus] 订阅者异常已隔离：{exc}")
        return ev

    # ── 读取 ──────────────────────────────────────────

    def recent(self, n: int = 50) -> List[Event]:
        with self._lock:
            items = list(self._recent)
        return items[-n:] if n > 0 else items


# 事件类型常量（一处定义，前后端共用口径）
EV_COMMAND_RECEIVED = "command.received"
EV_COMMAND_REJECTED = "command.rejected"
EV_COMMAND_ACCEPTED = "command.accepted"
EV_BRAIN_STARTED = "brain.started"
EV_LLM_CALLED = "llm.completed"
EV_SAFETY_APPROVED = "safety.approved"
EV_SAFETY_REJECTED = "safety.rejected"
EV_ROBOT_STATE = "robot.state"
EV_TASK_STARTED = "task.started"
EV_TASK_COMPLETED = "task.completed"
EV_TASK_FAILED = "task.failed"
EV_MEMORY_UPDATED = "memory.updated"
EV_ESTOP_ON = "safety.estop_on"
EV_ESTOP_OFF = "safety.estop_off"
EV_SYSTEM_ONLINE = "system.online"
