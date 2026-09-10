"""Console：Web 层中枢 —— 把现有 ArgOS 接到 Event Bus 上（Step 4/5 落地）。

## 怎么在不改 ArgOS 的前提下拿到事件

需求 §22 说"不要破坏现有架构"，但 Event Bus 总得有埋点。这里的做法是
**只在外面套一层，不进去改逻辑**：

| 想观测的东西 | 手段 | 侵入性 |
|---|---|---|
| 安全闸裁决 | 把 `brain.backend` 换成 `InstrumentedBackend`（转发 + emit） | 包装，不改动原对象 |
| tick 的状态转换 | server 的 tick 循环多带一个 sink 回调（默认 None） | server.py 加一个可选参数 |
| 用户指令 | Web 层自己包装 `try_command` 调用 | 无 |
| 记忆变化 | sink 里比对记忆条数 | 无 |

`InstrumentedBackend.apply()` 的返回值**原样透传**，所以大脑和安全闸的行为
一个字节都没变 —— 现有的 138 个测试就是这条的保险。
"""
from __future__ import annotations

import os
import threading
import time
from typing import Optional

from argos.brain import compile_command
from argos.web import telemetry as tel
from argos.web.events import (EV_BRAIN_STARTED, EV_COMMAND_ACCEPTED,
                              EV_COMMAND_RECEIVED, EV_COMMAND_REJECTED,
                              EV_ESTOP_OFF, EV_ESTOP_ON, EV_LLM_CALLED,
                              EV_MEMORY_UPDATED, EV_ROBOT_STATE,
                              EV_SAFETY_APPROVED, EV_SAFETY_REJECTED,
                              EV_TASK_COMPLETED, EV_TASK_FAILED,
                              EV_TASK_STARTED, EventBus)
from argos.web.models import (CAT_BRAIN, CAT_COMMAND, CAT_LLM, CAT_MEMORY,
                              CAT_ROBOT, CAT_SAFETY, CAT_SYSTEM, DONE, FAILED,
                              PENDING, RUNNING, SKIPPED, CameraConfig,
                              RobotProfile, Run, SafetyDecision,
                              STAGE_BRAIN, STAGE_EXECUTOR, STAGE_INPUT,
                              STAGE_LLM, STAGE_RESULT, STAGE_ROBOT,
                              STAGE_SAFETY, STAGE_TASK, now, to_dict)
from argos.web.store import Store, default_store


class InstrumentedBackend:
    """RobotBackend 的观测包装：调用前后 emit，返回值原样透传。

    用 __getattr__ 转发其余属性（尤其是 `gate`），所以大脑里
    `self.backend.gate.estop` 这类访问照旧可用。
    """

    def __init__(self, inner, console: "Console") -> None:
        self._inner = inner
        self._console = console

    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    def observe(self):
        return self._inner.observe()

    def apply(self, action, params):
        ok, reason = self._inner.apply(action, params)      # 先照原样执行
        console = self._console
        run = console.active_run_snapshot()                 # 带锁读，锁内不调 brain
        decision = SafetyDecision(action=str(action), approved=bool(ok),
                                  reason=str(reason or ("批准" if ok else "")),
                                  runId=run.id if run else None)
        console.last_decision = decision
        if ok:
            console.bus.emit(EV_SAFETY_APPROVED, CAT_SAFETY,
                             f"Safety check passed. {action} approved",
                             run.id if run else None,
                             {"action": action, "params": params})
            if run is not None:
                run.set_stage(STAGE_SAFETY, DONE, f"{action} 批准")
                run.set_stage(STAGE_EXECUTOR, RUNNING, f"执行 {action}")
                console.store.save_run(run)
        else:
            console.bus.emit(EV_SAFETY_REJECTED, CAT_SAFETY,
                             f"Safety rejected {action}. {reason}",
                             run.id if run else None,
                             {"action": action, "reason": reason})
            if run is not None:
                run.set_stage(STAGE_SAFETY, FAILED, f"{action} 被拒：{reason}")
                run.set_stage(STAGE_RESULT, FAILED, reason)
                run.status = "failed"
                run.error = str(reason)
                console.store.save_run(run)
        return ok, reason


class Console:
    """Web 层的大脑侧门面：API 路由和 WS 都只跟它打交道。"""

    def __init__(self, brain, bus: Optional[EventBus] = None,
                 store: Optional[Store] = None,
                 executor_kind: Optional[str] = None) -> None:
        self.brain = brain
        self.bus = bus or EventBus()
        self.store = store or default_store()
        self.executor_kind = (executor_kind
                              or os.environ.get("ROBOT_EXECUTOR", "sim"))
        self.active_run: Optional[Run] = None
        self.last_decision: Optional[SafetyDecision] = None
        self.started_at = time.time()
        # 并发保护：submit 走 to_thread、tick_sink 走 tick 线程，两者都会读写
        # active_run。锁只包"读写 active_run 引用"的短临界区，**持锁时绝不调
        # brain** —— 否则与 brain._lock 形成 AB-BA 死锁（tick 持 brain 锁 → apply
        # 要 Console 锁；submit 持 Console 锁 → 又要 brain 锁）。
        self._lock = threading.RLock()
        self._mem_count = len(getattr(brain, "memory", []) or [])
        self.bus.subscribe(self.store.save_event)     # 事件落盘（订阅者之一）
        self._wrap_backend()

    # ── 装配 ────────────────────────────────────────────

    def _wrap_backend(self) -> None:
        inner = getattr(self.brain, "backend", None)
        if inner is None or isinstance(inner, InstrumentedBackend):
            return
        self.brain.backend = InstrumentedBackend(inner, self)

    # ── 指令 → Run ──────────────────────────────────────

    def submit(self, text: str) -> Run:
        """用户下一次指令 = 一条 Run（需求 §11）。

        只调**一次** try_command —— 调两次会重复记一条"接到任务"的记忆，
        那是污染记忆卡，不是可观测性。
        """
        text = (text or "").strip()
        run = Run(command=text, source="user")
        with self._lock:
            self.active_run = run
        self.store.save_run(run)
        run.set_stage(STAGE_INPUT, DONE, text)
        self.bus.emit(EV_COMMAND_RECEIVED, CAT_COMMAND,
                      f"You asked ArgOS: {text}", run.id, {"text": text})
        self.store.save_run(run)

        task = compile_command(text, self.brain.places)   # 纯函数，不改状态
        if task is None:
            run.set_stage(STAGE_BRAIN, FAILED,
                          "认不出这个指令（只懂：去某地 / 巡逻 / 拿某物 / 放下）")
            self._mark_llm(run)
            run.reply = self.brain.try_command(text)
            run.status = "rejected"
            run.error = "编译失败：不支持的指令"
            run.set_stage(STAGE_RESULT, FAILED, run.reply)
            self.store.save_run(run)
            self.bus.emit(EV_COMMAND_REJECTED, CAT_COMMAND, run.reply, run.id)
            return run

        run.set_stage(STAGE_BRAIN, DONE, f"编译 → {task.get('action')}",
                      {"task": task})
        # 安全闸预审（只读 check，不落账；真正那道在 backend.apply 里）
        params = {k: v for k, v in task.items() if k != "action"}
        ok, reason = self.brain.backend.gate.check(
            str(task.get("action", "")), params, self.brain.backend.observe())
        self.last_decision = SafetyDecision(
            action=str(task.get("action", "")), approved=bool(ok),
            reason=str(reason or "预审通过"), runId=run.id)
        run.set_stage(STAGE_SAFETY, DONE if ok else FAILED,
                      reason or "安全闸预审通过",
                      {"action": task.get("action")})

        before = self.brain.pending_task
        run.reply = self.brain.try_command(text)      # 唯一一次真实调用
        accepted = (self.brain.pending_task is not None
                    and self.brain.pending_task is not before)
        self._mark_llm(run)

        if accepted:
            run.set_stage(STAGE_TASK, RUNNING, "已落账，等下一帧 tick 执行",
                          {"task": task})
            self.bus.emit(EV_COMMAND_ACCEPTED, CAT_COMMAND, run.reply or "",
                          run.id)
        else:
            run.set_stage(STAGE_TASK, FAILED, run.reply or "落账被拒")
            run.set_stage(STAGE_RESULT, FAILED, run.reply)
            run.status = "rejected"
            run.error = run.reply
            self.bus.emit(EV_COMMAND_REJECTED, CAT_COMMAND,
                          run.reply or "落账被拒", run.id)
        self.store.save_run(run)
        return run

    def _mark_llm(self, run: Run) -> None:
        """LLM 这一节如实标注：它只做措辞，不参与规划与安全（铁律）。"""
        llm = getattr(self.brain, "llm", None)
        if llm is not None and llm.enabled():
            run.set_stage(STAGE_LLM, DONE,
                          "已用于回复措辞（不参与规划与安全判定）")
        else:
            run.set_stage(STAGE_LLM, SKIPPED, "未配置 API key，走规则话术")

    # ── tick → Run 推进 ─────────────────────────────────

    def tick_sink(self, ev) -> None:
        """挂在 server 的 tick 循环上：每帧的转换事件推进当前 Run。"""
        self._watch_memory()
        if not ev:
            return
        if "started" in ev:
            run = self._claim_run(str(ev["started"]))
            run.set_stage(STAGE_TASK, DONE, str(ev["started"]))
            run.set_stage(STAGE_EXECUTOR, RUNNING, "下发执行器")
            self.store.save_run(run)
            self.bus.emit(EV_TASK_STARTED, CAT_ROBOT,
                          f"Started: {ev['started']}", run.id)
        if "completed" in ev:
            run = self._current_run(str(ev["completed"]))
            run.set_stage(STAGE_EXECUTOR, DONE, "执行器返回成功")
            run.set_stage(STAGE_ROBOT, DONE, str(ev["completed"]))
            run.set_stage(STAGE_RESULT, DONE, str(ev["completed"]))
            run.status = "completed"
            self.store.save_run(run)
            self.bus.emit(EV_TASK_COMPLETED, CAT_ROBOT,
                          f"Completed: {ev['completed']}", run.id)
            self._close(run)
        if "failed" in ev:
            run = self._current_run(str(ev["failed"]))
            run.set_stage(STAGE_EXECUTOR, FAILED, str(ev["failed"]))
            run.set_stage(STAGE_ROBOT, FAILED, str(ev["failed"]))
            run.set_stage(STAGE_RESULT, FAILED, str(ev["failed"]))
            run.status = "failed"
            run.error = str(ev["failed"])
            self.store.save_run(run)
            self.bus.emit(EV_TASK_FAILED, CAT_ROBOT,
                          f"Failed: {ev['failed']}", run.id)
            self._close(run)
        if "reflected" in ev:
            self.bus.emit(EV_MEMORY_UPDATED, CAT_MEMORY,
                          "Memory updated. 反思归纳已入库")

    def _claim_run(self, desc: str) -> Run:
        """用户单优先复用当前 Run；否则这是大脑自选的日常，另开一条。"""
        with self._lock:
            r = self.active_run
            if (r is not None and r.status == RUNNING and r.source == "user"
                    and r.stage(STAGE_TASK) is not None
                    and r.stage(STAGE_TASK).status == RUNNING):
                return r
        run = Run(command=desc, source="autonomous")
        run.set_stage(STAGE_INPUT, DONE, "自主日常（非用户指令）")
        run.set_stage(STAGE_BRAIN, DONE, "大脑自选日常")
        run.set_stage(STAGE_LLM, SKIPPED, "自主日常不调 LLM")
        self.store.save_run(run)
        with self._lock:
            self.active_run = run
        self.bus.emit(EV_BRAIN_STARTED, CAT_BRAIN,
                      f"自主日常：{desc}", run.id)
        return run

    def _current_run(self, desc: str) -> Run:
        with self._lock:
            cur = self.active_run
            if cur is not None and cur.status == RUNNING:
                return cur
        run = Run(command=desc, source="autonomous")
        self.store.save_run(run)
        with self._lock:
            self.active_run = run
        return run

    def _close(self, run: Run) -> None:
        with self._lock:
            if self.active_run is run:
                self.active_run = None

    # ── 并发安全的读取口（锁内不调 brain）──────────────────

    def active_run_snapshot(self) -> Optional[Run]:
        """带锁读当前 Run 引用。"""
        with self._lock:
            return self.active_run

    def task_snapshot(self):
        """一次取"任务视图"三件套（/api/tasks 用）；brain 读取在锁外，
        避免与 brain._lock 形成 AB-BA（见 _lock 注释）。"""
        return (self.brain.status(),
                getattr(self.brain, "activity", None),
                self.active_run_snapshot())

    def _watch_memory(self) -> None:
        n = len(getattr(self.brain, "memory", []) or [])
        if n != self._mem_count:
            self._mem_count = n
            self.bus.emit(EV_MEMORY_UPDATED, CAT_MEMORY,
                          "Memory updated.")

    # ── 控制（全部走现有路径）────────────────────────────

    def estop(self, on: bool = True) -> None:
        """急停：走 brain.estop() → gate + executor 一起置位（评审 P0-1 的路径）。"""
        self.brain.estop(on)
        if on:
            self.bus.emit(EV_ESTOP_ON, CAT_SAFETY,
                          "Emergency stop engaged. 所有动作已拒绝")
        else:
            self.bus.emit(EV_ESTOP_OFF, CAT_SAFETY,
                          "Emergency stop released.")

    # ── 读取 ────────────────────────────────────────────

    def profile(self) -> RobotProfile:
        return self.store.get_profile()

    def camera_config(self) -> CameraConfig:
        return self.store.get_camera()

    def robot_state(self) -> dict:
        return tel.robot_state(self.brain, self.profile())

    def telemetry(self) -> dict:
        return tel.telemetry(self.brain)

    def brain_state(self) -> dict:
        return tel.brain_state(self.brain, self.executor_kind)

    def safety_state(self) -> dict:
        return tel.safety_state(self.brain, self.last_decision)

    def snapshot(self) -> dict:
        """WS 刚连上时给一份全量，避免空白页等第一次推送。"""
        return {
            "system": {
                "online": True,
                "version": "0.1.0",
                "executor": self.executor_kind,
                "startedAt": self.started_at,
            },
            "robot": self.robot_state(),
            "brain": self.brain_state(),
            "safety": self.safety_state(),
            "profile": to_dict(self.profile()),
            "camera": to_dict(self.camera_config()),
            "runs": [to_dict(r) for r in self.store.list_runs(limit=20)],
            "events": [to_dict(e) for e in self.store.list_events(limit=30)],
        }
