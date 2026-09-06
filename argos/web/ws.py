"""WebSocket Gateway（Step 5）：/api/ws 的唯一出口。

关键点：
  1. **总线 → WS 单向**。WS 网关是 Event Bus 的一个普通订阅者，跟 Run Store
     平级。brain / safety / executor 完全不知道 WebSocket 存在（需求 §14）。
  2. **跨线程安全**：事件多半由 tick 线程（server 用 to_thread 跑 brain.tick）
     发出，而 send 必须在事件循环线程里做。所以这里用
     `loop.call_soon_threadsafe` 把推送甩回循环，不在 tick 线程直接 await。
  3. **分频推送**（需求 §15）：pose 变化快 → 5Hz；电量/温度这类 → 1Hz；
     event 是事件驱动，来了就推。没有客户端时整个循环空转不采样，省 CPU。
  4. 客户端断线/异常一律摘掉，不让一个坏连接拖住所有推送。
"""
from __future__ import annotations

import asyncio
import time
from typing import Callable, Optional, Set

from fastapi import WebSocket

from argos.web.models import Event, to_dict

# 推送频率（秒）
STATE_HZ = 5.0        # robot.state：位姿 + 运行状态
TELEMETRY_HZ = 1.0    # robot.telemetry：电量 / 温度 / CPU
_IDLE_SLEEP = 0.05


class WebSocketHub:
    def __init__(self,
                 bus,
                 snapshot: Optional[Callable[[], dict]] = None,
                 robot_state: Optional[Callable[[], dict]] = None,
                 telemetry: Optional[Callable[[], dict]] = None) -> None:
        self.bus = bus
        self._snapshot = snapshot
        self._robot_state = robot_state
        self._telemetry = telemetry
        self._clients: Set[WebSocket] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._task = None
        bus.subscribe(self._on_event)          # 网关只是订阅者之一

    # ── 连接生命周期 ────────────────────────────────────

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        self._loop = asyncio.get_running_loop()
        # telemetry 循环懒启动：有人连才跑，且不用去动 server 的 lifespan
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.telemetry_loop())
        if self._snapshot is not None:        # 刚连上先给一份全量，避免空白页
            try:
                await ws.send_json({"type": "snapshot", "data": self._snapshot()})
            except Exception:
                pass

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    # ── 事件 → 推送（可能被任意线程调用）─────────────────

    def _on_event(self, ev: Event) -> None:
        loop = self._loop
        if loop is None or not self._clients:
            return
        try:
            loop.call_soon_threadsafe(self._spawn, ev)
        except RuntimeError:                  # 循环已关（服务在停）
            pass

    def _spawn(self, ev: Event) -> None:
        asyncio.create_task(self.broadcast("event.created", to_dict(ev)))

    async def broadcast(self, msg_type: str, data: dict) -> None:
        if not self._clients:
            return
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_json({"type": msg_type, "data": data})
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    # ── 分频 telemetry ─────────────────────────────────

    async def telemetry_loop(self) -> None:
        period_state = 1.0 / STATE_HZ
        period_tele = 1.0 / TELEMETRY_HZ
        last_state = last_tele = 0.0
        while True:
            if not self._clients:             # 没人看就不采样
                await asyncio.sleep(0.2)
                continue
            t = time.monotonic()
            if self._robot_state is not None and t - last_state >= period_state:
                last_state = t
                await self.broadcast("robot.state", self._robot_state())
            if self._telemetry is not None and t - last_tele >= period_tele:
                last_tele = t
                await self.broadcast("robot.telemetry", self._telemetry())
            await asyncio.sleep(_IDLE_SLEEP)
