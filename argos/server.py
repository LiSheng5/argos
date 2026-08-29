"""机器人服务器：把 brain 挂成 HTTP（模式复用 1_Dagent/npc/server.py，只读参考）。

启动: python -m argos.server [--port 8766] [--executor sim|mujoco]
      （或双击 启动ArgOS服务器.bat）
安全: 仅绑定 127.0.0.1 + Origin 校验（本地单机工具，同 Dagent 规矩）。
端点:
  POST /api/command {"text": "..."} → brain.try_command → {reply, ...状态}
  GET  /api/state  → 状态快照（含最近 5 条记忆）
  GET  /api/memory → 全部记忆卡条目（可编辑文档：改文件即改记忆）
  POST /api/estop  {"on": true/false} → 急停置位/解除（真机解除应走物理复位）
自主循环随 FastAPI lifespan 启动：每 ROBOT_TICK_INTERVAL（默认 3s）推一帧 brain.tick()。
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request

from argos.brain import RobotBrain
from argos.executor import build_executor

TICK_INTERVAL = 3.0   # 帧间隔（秒），环境变量 ROBOT_TICK_INTERVAL 可覆盖
_DEFAULT_PORT = 8766  # 1_Dagent 大脑占 8765，机器人让一位

# 同 Dagent：本地页面来源放行，其余 Origin 拒绝；无 Origin（curl/脚本）放行
_ALLOWED_ORIGIN_PREFIXES = ("http://127.0.0.1", "http://localhost")


def _tick_interval() -> float:
    try:
        return float(os.environ.get("ROBOT_TICK_INTERVAL", "") or TICK_INTERVAL)
    except ValueError:
        return TICK_INTERVAL


def _verify_origin(request: Request) -> None:
    origin = request.headers.get("origin", "")
    if origin and not origin.startswith(_ALLOWED_ORIGIN_PREFIXES):
        raise HTTPException(status_code=403, detail="origin 不允许")


def default_brain() -> RobotBrain:
    """默认大脑：sim 执行器 + 记忆卡落盘 argos/store/robot_memory.json。"""
    kind = os.environ.get("ROBOT_EXECUTOR", "sim")
    store = Path(__file__).resolve().parent / "store" / "robot_memory.json"
    return RobotBrain(executor=build_executor(kind), memory_path=store)


async def _tick_loop(brain: RobotBrain) -> None:
    """自主循环：每帧恰一步（Dagent _tick_loop 同款，随 lifespan 启停）。

    **必须走 to_thread**（评审 P0-2）：brain.tick() 会一路同步调用到执行器，
    DdsEntity 一个 move_to 最长 15s、一次巡逻更久。直接在事件循环里调会把
    loop 卡死，期间 /api/command 与 /api/estop 全部无响应 —— 真机上等于
    "急停按不下去"。丢进线程后，急停端点始终能立刻返回。
    """
    try:
        while True:
            await asyncio.to_thread(brain.tick)
            await asyncio.sleep(_tick_interval())
    except asyncio.CancelledError:
        pass


def build_app(brain: RobotBrain | None = None) -> FastAPI:
    """装配 app。brain 可注入（测试用）；tick 循环只进 lifespan ——
    TestClient 不进 with 上下文则不启动（测试确定性，Dagent 同款取舍）。"""
    brain = brain or default_brain()

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        task = asyncio.create_task(_tick_loop(brain))
        yield
        task.cancel()

    app = FastAPI(title="ArgOS", lifespan=_lifespan)
    app.state.brain = brain

    @app.post("/api/command", dependencies=[Depends(_verify_origin)])
    async def api_command(req: Request):
        raw = await req.body()
        try:
            data = json.loads(raw)
        except Exception:
            try:    # Windows shell（cmd/PowerShell/Git Bash）发中文常变 GBK 字节，兜底解码
                data = json.loads(raw.decode("gbk"))
            except Exception:
                raise HTTPException(status_code=400, detail="请求体必须是 JSON")
        text = str((data or {}).get("text", "")).strip()
        if not text:
            raise HTTPException(status_code=400, detail="text 不能为空")
        reply = brain.try_command(text)
        return {"reply": reply, **brain.status()}

    @app.get("/api/state", dependencies=[Depends(_verify_origin)])
    async def api_state():
        return {**brain.status(), "memory": brain.recent(5)}

    @app.get("/api/memory", dependencies=[Depends(_verify_origin)])
    async def api_memory():
        return {"entries": brain.memory}

    @app.post("/api/estop", dependencies=[Depends(_verify_origin)])
    async def api_estop(req: Request):
        on = True
        try:
            data = await req.json()
            on = bool((data or {}).get("on", True))
        except Exception:
            pass                          # 空请求体 = 置位
        brain.estop(on)                   # 闸门 + 执行器一起置位（评审 P0-1）
        return {"ok": True, "estop": on}

    return app


def main() -> None:
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(description="机器人服务器（仅 127.0.0.1）")
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("ROBOT_PORT", str(_DEFAULT_PORT))))
    ap.add_argument("--executor", default=os.environ.get("ROBOT_EXECUTOR", "sim"),
                    choices=("sim", "mujoco", "dds"))
    args = ap.parse_args()
    os.environ["ROBOT_EXECUTOR"] = args.executor
    uvicorn.run(build_app(), host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
