"""Console 装配入口：把 Web 层挂到现有 ArgOS server 上。

用法：
    python -m argos.web.gateway --executor sim        # 默认 127.0.0.1:8766
    python -m argos.web.gateway --executor dds --port 8766

设计原则：**不复制 ArgOS，只包一层**。
  - app 本体还是 server.build_app()（四个原有端点一个没动）；
  - tick 循环多带一个 sink，把每帧事件喂给 Console；
  - 只在这里加 CORS —— 浏览器从 Vite dev server（localhost:5173）访问
    127.0.0.1:8766 属于跨源，没有 CORS 头浏览器会直接吞掉响应。
    放开范围仍是本机（127.0.0.1 / localhost），跟现有 Origin 白名单一致。
"""
from __future__ import annotations

import argparse
import os

from fastapi.middleware.cors import CORSMiddleware

from argos.server import _DEFAULT_PORT, build_app, default_brain
from argos.web.api import register
from argos.web.bridge import Console
from argos.web.camera import CameraService
from argos.web.events import EventBus
from argos.web.store import Store, default_store
from argos.web.upload import ImageStore
from argos.web.ws import WebSocketHub


def build_console_app(brain=None, store=None, db_path: str | None = None,
                      executor_kind: str | None = None):
    brain = brain or default_brain()
    store = store or (Store(db_path) if db_path else default_store())

    bus = EventBus()
    console = Console(brain, bus=bus, store=store, executor_kind=executor_kind)
    hub = WebSocketHub(bus,
                       snapshot=console.snapshot,
                       robot_state=console.robot_state,
                       telemetry=console.telemetry)

    app = build_app(brain=brain, tick_sink=console.tick_sink)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(127\.0\.0\.1|localhost)(:\d+)?",
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
    register(app, console, ImageStore(), CameraService(store), hub)
    app.state.console = console
    app.state.hub = hub
    return app


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser(description="ArgOS Console（仅本机）")
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("ROBOT_PORT",
                                               str(_DEFAULT_PORT))))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--executor", default=os.environ.get("ROBOT_EXECUTOR", "sim"),
                    choices=("sim", "mujoco", "dds"))
    ap.add_argument("--db", default=os.environ.get("ARGOS_DB", ""))
    args = ap.parse_args()

    os.environ["ROBOT_EXECUTOR"] = args.executor
    uvicorn.run(build_console_app(db_path=args.db or None),
                host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
