"""Console 的 HTTP 路由（需求 §16）。

两条硬规矩：
  1. **优先兼容现有接口**：/api/command、/api/state、/api/memory、/api/estop
     是 server.py 原有的，这里一个都不动。Console 走 /api/runs 等新路径。
  2. **凡是要调 brain / LLM 的端点一律 to_thread**：try_command 里 LLM 措辞
     可能耗几秒到 20s，直接在事件循环里跑会把急停按钮一起卡死
     （评审 P0-2 的教训，别再踩一次）。
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional

from fastapi import Depends, File, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from argos.server import _verify_origin
from argos.web.camera import CameraService, CameraUnavailable
from argos.web.models import CameraConfig, LlmConfig, now, to_dict
from argos.web.upload import ImageStore

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_KEY_FILE = _REPO_ROOT / "api_key.txt"


def register(app, console, images: ImageStore, camera: CameraService, hub):
    """把 Console 的路由挂到现有 app 上。"""

    # ── System ──────────────────────────────────────────

    @app.get("/api/system", dependencies=[Depends(_verify_origin)])
    async def api_system():
        return {
            "online": True,
            "version": "0.1.0",
            "executor": console.executor_kind,
            "startedAt": console.started_at,
            "uptimeSec": round(time.time() - console.started_at, 1),
            "counts": {
                "runs": len(console.store.list_runs(limit=1000)),
                "events": len(console.store.list_events(limit=1000)),
                "memory": len(getattr(console.brain, "memory", []) or []),
            },
        }

    @app.get("/api/system/health", dependencies=[Depends(_verify_origin)])
    async def api_health():
        return {"status": "ok", "ts": now()}

    @app.get("/api/brain", dependencies=[Depends(_verify_origin)])
    async def api_brain():
        """大脑状态（tick / 当前活动 / LLM 是否启用）。"""
        return console.brain_state()

    # ── Robot ───────────────────────────────────────────

    @app.get("/api/robot", dependencies=[Depends(_verify_origin)])
    async def api_robot():
        return {"profile": to_dict(console.profile()),
                "state": console.robot_state()}

    @app.get("/api/robot/state", dependencies=[Depends(_verify_origin)])
    async def api_robot_state():
        return console.robot_state()

    @app.get("/api/robot/telemetry", dependencies=[Depends(_verify_origin)])
    async def api_robot_telemetry():
        return console.telemetry()

    @app.post("/api/robot/profile", dependencies=[Depends(_verify_origin)])
    async def api_robot_profile(req: Request):
        data = await _json(req)
        name = str(data.get("name", "")).strip()
        p = console.profile()
        if name:
            p.name = name
        if "id" in data and str(data["id"]).strip():
            p.id = str(data["id"]).strip()
        p.updatedAt = now()
        console.store.set_profile(p)
        return to_dict(p)

    @app.post("/api/robot/image", dependencies=[Depends(_verify_origin)])
    async def api_robot_image_upload(file: UploadFile = File(...)):
        data = await file.read()
        url, err = images.save(data, file.filename or "")
        if err:
            raise HTTPException(status_code=400, detail=err)
        p = console.profile()
        if p.imageUrl:                       # 换图：清掉上一张，不留孤儿文件
            images.clear(p.imageUrl)
        p.imageUrl = url
        p.updatedAt = now()
        console.store.set_profile(p)
        return to_dict(p)

    @app.delete("/api/robot/image", dependencies=[Depends(_verify_origin)])
    async def api_robot_image_delete():
        p = console.profile()
        if p.imageUrl:
            images.delete(p.imageUrl)
        p.imageUrl = None
        p.updatedAt = now()
        console.store.set_profile(p)
        return to_dict(p)

    @app.get("/api/robot/image/{name}")
    async def api_robot_image_file(name: str):
        p = images.resolve(f"/api/robot/image/{name}")
        if p is None:
            raise HTTPException(status_code=404, detail="图片不存在")
        return FileResponse(str(p))

    # ── Runs（核心数据模型）─────────────────────────────

    @app.get("/api/runs", dependencies=[Depends(_verify_origin)])
    async def api_runs(limit: int = 50, status: Optional[str] = None,
                       source: Optional[str] = None):
        return {"runs": [to_dict(r) for r in
                         console.store.list_runs(limit=limit, status=status,
                                                 source=source)]}

    @app.post("/api/runs", dependencies=[Depends(_verify_origin)])
    async def api_runs_create(req: Request):
        data = await _json(req)
        text = str(data.get("text", "")).strip()
        if not text:
            raise HTTPException(status_code=400, detail="text 不能为空")
        run = await asyncio.to_thread(console.submit, text)   # 可能调 LLM
        return to_dict(run)

    @app.get("/api/runs/{run_id}", dependencies=[Depends(_verify_origin)])
    async def api_run(run_id: str):
        run = console.store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run 不存在")
        events = console.store.list_events(limit=200, run_id=run_id)
        return {"run": to_dict(run),
                "events": [to_dict(e) for e in events]}

    # ── Events ──────────────────────────────────────────

    @app.get("/api/events", dependencies=[Depends(_verify_origin)])
    async def api_events(limit: int = 100, category: Optional[str] = None,
                         run_id: Optional[str] = None):
        return {"events": [to_dict(e) for e in
                           console.store.list_events(limit=limit,
                                                     category=category,
                                                     run_id=run_id)]}

    @app.get("/api/events/{event_id}", dependencies=[Depends(_verify_origin)])
    async def api_event(event_id: str):
        for e in console.store.list_events(limit=500):
            if e.id == event_id:
                return to_dict(e)
        raise HTTPException(status_code=404, detail="Event 不存在")

    # ── Tasks ───────────────────────────────────────────

    @app.get("/api/tasks", dependencies=[Depends(_verify_origin)])
    async def api_tasks():
        """诚实实现：ArgOS 现在没有独立 task store。

        task 在架构上是 run 的一节（brain 的 activity 就是它）。这里返回
        进行中的活动，并明确标注来源，不假装有张 tasks 表。
        """
        st = console.brain.status()
        act = getattr(console.brain, "activity", None)
        items = []
        if act is not None:
            items.append({
                "id": console.active_run.id if console.active_run else None,
                "desc": act.get("desc", ""),
                "stepsLeft": len(act.get("steps", []) or []),
                "fromUser": bool(act.get("from_user")),
                "state": st.get("state", ""),
            })
        return {"tasks": items,
                "note": "ArgOS 无独立 task store；task 是 run 的一节，"
                        "详情见 /api/runs/{id}"}

    @app.get("/api/tasks/{task_id}", dependencies=[Depends(_verify_origin)])
    async def api_task(task_id: str):
        run = console.store.get_run(task_id)       # task id 即 run id
        if run is None:
            raise HTTPException(status_code=404, detail="Task 不存在")
        stage = run.stage("task")
        return {"id": run.id, "run": to_dict(run),
                "stage": to_dict(stage) if stage else None}

    # ── Safety（全部走现有 SafetyGate）───────────────────

    @app.get("/api/safety", dependencies=[Depends(_verify_origin)])
    async def api_safety():
        return console.safety_state()

    @app.post("/api/safety/estop", dependencies=[Depends(_verify_origin)])
    async def api_safety_estop(req: Request):
        """急停：走 brain.estop() → 闸门 + 执行器一起置位，不绕 SafetyGate。"""
        on = True
        try:
            data = await _json(req)
            on = bool(data.get("on", True))
        except Exception:
            pass
        console.estop(on)
        return {"ok": True, "estop": on}

    # ── Memory ──────────────────────────────────────────

    @app.get("/api/memory/search", dependencies=[Depends(_verify_origin)])
    async def api_memory_search(q: str = "", top_k: int = 10):
        hits = console.brain.recall(q, top_k=top_k) if q else []
        return {"query": q, "entries": hits}

    @app.get("/api/memory/{mem_id}", dependencies=[Depends(_verify_origin)])
    async def api_memory_item(mem_id: str):
        for m in (getattr(console.brain, "memory", []) or []):
            if str(m.get("id")) == mem_id:
                return m
        raise HTTPException(status_code=404, detail="记忆不存在")

    # ── LLM Playground ──────────────────────────────────

    @app.get("/api/llm/models", dependencies=[Depends(_verify_origin)])
    async def api_llm_models():
        llm = getattr(console.brain, "llm", None)
        if llm is None or not llm.enabled():
            return {"models": [], "error": "未配置 API key"}
        try:
            import urllib.request
            req = urllib.request.Request(
                f"{llm.base_url}/models",
                headers={"Authorization": f"Bearer {llm.api_key}",
                         "User-Agent": "ArgOS-llm/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
            return {"models": ids, "current": llm.model}
        except Exception as exc:
            return {"models": [], "current": llm.model,
                    "error": f"拉取模型列表失败：{exc}"}

    @app.post("/api/llm/chat", dependencies=[Depends(_verify_origin)])
    async def api_llm_chat(req: Request):
        """两种模式（需求 §17）：
        direct = User → LLM（纯对话，不碰机器人）
        brain  = User → Brain → Safety → Executor（会真的落账执行）
        """
        data = await _json(req)
        message = str(data.get("message", "")).strip()
        mode = str(data.get("mode", "direct")).strip() or "direct"
        if not message:
            raise HTTPException(status_code=400, detail="message 不能为空")

        if mode == "brain":
            run = await asyncio.to_thread(console.submit, message)
            return {"mode": "brain", "reply": run.reply or "",
                    "runId": run.id, "run": to_dict(run)}

        llm = getattr(console.brain, "llm", None)
        if llm is None or not llm.enabled():
            raise HTTPException(status_code=400,
                                detail="未配置 API key（Settings 里填）")
        system = str(data.get("system") or "你是 ArgOS，一只诚实的机器狗。")
        max_tokens = int(data.get("maxTokens", 200) or 200)
        temperature = float(data.get("temperature", 0.7) or 0.7)
        t0 = time.time()

        def _call():
            return llm.chat(system, message, max_tokens=max_tokens,
                            temperature=temperature)

        try:
            text = await asyncio.to_thread(_call)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LLM 调用失败：{exc}")
        return {"mode": "direct", "reply": text, "model": llm.model,
                "elapsedMs": int((time.time() - t0) * 1000)}

    # ── Settings：API key 只存本地 ───────────────────────

    @app.get("/api/settings/llm", dependencies=[Depends(_verify_origin)])
    async def api_settings_llm():
        llm = getattr(console.brain, "llm", None)
        cfg = LlmConfig()
        if llm is not None:
            cfg.baseUrl = llm.base_url
            cfg.model = llm.model
            cfg.hasKey = bool(llm.api_key)
            cfg.timeout = llm.timeout
            cfg.maskedKey = _mask(llm.api_key)
        return to_dict(cfg)

    @app.post("/api/settings/llm", dependencies=[Depends(_verify_origin)])
    async def api_settings_llm_save(req: Request):
        data = await _json(req)
        llm = getattr(console.brain, "llm", None)
        if llm is None:
            raise HTTPException(status_code=400, detail="大脑未挂载 LLM 客户端")
        if "baseUrl" in data and str(data["baseUrl"]).strip():
            llm.base_url = str(data["baseUrl"]).strip().rstrip("/")
        if "model" in data and str(data["model"]).strip():
            llm.model = str(data["model"]).strip()
        if "timeout" in data:
            try:
                llm.timeout = float(data["timeout"])
            except (TypeError, ValueError):
                pass
        key = str(data.get("apiKey", "") or "").strip()
        if key:
            # 只落本地：仓库根 api_key.txt（已 gitignore），
            # 与现有 llm.load_api_key() 的读取路径一致，填完立刻生效。
            llm.api_key = key
            try:
                _KEY_FILE.write_text(key, encoding="utf-8")
            except OSError as exc:
                raise HTTPException(status_code=500,
                                    detail=f"写 api_key.txt 失败：{exc}")
        cfg = LlmConfig(baseUrl=llm.base_url, model=llm.model,
                        hasKey=bool(llm.api_key), timeout=llm.timeout,
                        maskedKey=_mask(llm.api_key))
        return to_dict(cfg)

    # ── Camera ──────────────────────────────────────────

    @app.get("/api/camera", dependencies=[Depends(_verify_origin)])
    async def api_camera():
        return camera.status()

    @app.post("/api/camera", dependencies=[Depends(_verify_origin)])
    async def api_camera_save(req: Request):
        data = await _json(req)
        cfg = CameraConfig(
            mode=str(data.get("mode", "none") or "none"),
            url=(str(data["url"]).strip() or None) if data.get("url") else None,
            usbIndex=int(data.get("usbIndex", 0) or 0))
        camera.set_config(cfg)
        return camera.status()

    @app.get("/api/camera/stream.mjpg")
    async def api_camera_stream():
        # 先判可用性再回流：CameraUnavailable 是在 async generator **迭代时**
        # 才抛的，等 StreamingResponse 开始产出就已经发不出 404 了。
        st = camera.status()
        if not st.get("available"):
            return JSONResponse(status_code=404,
                                content={"error": st.get("message", "无相机源"),
                                         "hint": "No camera signal"})
        return StreamingResponse(
            camera.stream(),
            media_type="multipart/x-mixed-replace; boundary=frame")

    @app.get("/api/camera/snapshot.jpg")
    async def api_camera_snapshot():
        jpeg = await camera.snapshot()
        if not jpeg:
            return Response(status_code=404)
        return Response(content=jpeg, media_type="image/jpeg")

    # ── WebSocket ───────────────────────────────────────

    @app.websocket("/api/ws")
    async def api_ws(ws: WebSocket):
        origin = ws.headers.get("origin", "")
        if origin and not (origin.startswith("http://127.0.0.1")
                           or origin.startswith("http://localhost")):
            await ws.close(code=1008)
            return
        await hub.connect(ws)
        try:
            while True:
                await ws.receive_text()      # 保持连接，客户端消息暂不使用
        except Exception:
            hub.disconnect(ws)

    return app


async def _json(req: Request) -> dict:
    raw = await req.body()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        try:                                  # Windows shell 发中文常变 GBK
            return json.loads(raw.decode("gbk"))
        except Exception:
            raise HTTPException(status_code=400, detail="请求体必须是 JSON")


def _mask(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:3]}***{key[-4:]}"
