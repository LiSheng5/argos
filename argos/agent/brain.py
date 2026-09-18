"""AgentBrain —— 只依赖抽象的大脑（Phase 4）。

与旧 `argos/brain.py` 的根本区别：

| 旧 RobotBrain | 新 AgentBrain |
|---|---|
| 编译与规划混在一个文件，查表展开步骤 | Planner 独立，会选路线、会重规划 |
| 失败即终止 + 冷却 5 tick，不换路 | 失败 → 反思 → Lesson → **换路线**重试 |
| recall 只用于措辞 | Lesson 被 Planner 消费 |
| 状态散在四处 | 只看 `Observation`（WorldState 的只读投影） |
| 绑死 RobotExecutor | 只认 `EmbodimentBackend` 协议 |

⚠️ 它不认识任何具体机器人 —— 给它 SimulatorBackend 就在仿真里跑，
给它未来的 Go2Backend 就在真机上跑，本文件一行不用改。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from argos.agent.interfaces import (
    ActionResult,
    EmbodimentBackend,
    FailReason,
    Lesson,
    Pose,
)
from argos.agent.memory_agent import DEFAULT_MIN_CONFIDENCE, LessonStore
from argos.agent.planner import Plan, Planner
from argos.agent.reflection import Reflector
from argos.world.state import from_observation, view

__all__ = ["TraceStep", "RunResult", "AgentBrain"]


@dataclass
class TraceStep:
    """一步的完整记录 —— Phase 8 的 trace / demo 就靠它（现在先落下来，不额外造轮子）。"""
    step: int
    goal: str
    route: Optional[str]
    action: str
    ok: bool
    reason: str
    detail: str
    sim_time: float
    note: str = ""


@dataclass
class RunResult:
    ok: bool
    goal: str
    steps: int
    failures: int
    replans: int
    lessons: List[Lesson] = field(default_factory=list)
    trace: List[TraceStep] = field(default_factory=list)
    final_pose: Pose = Pose()
    stop_reason: str = ""

    def as_rows(self) -> List[dict]:
        """给 trace / benchmark 用的原始行。"""
        return [t.__dict__ for t in self.trace]


class AgentBrain:
    def __init__(
        self,
        backend: EmbodimentBackend,
        planner: Optional[Planner] = None,
        reflector: Optional[Reflector] = None,
        store: Optional[LessonStore] = None,
        max_steps: int = 40,
        max_retry: int = 2,
        lesson_threshold: float = DEFAULT_MIN_CONFIDENCE,
    ) -> None:
        self.backend = backend
        self.planner = planner
        self.reflector = reflector or Reflector()
        self.store = store or self.reflector.store
        self.max_steps = int(max_steps)
        self.max_retry = int(max_retry)
        # 读 Lesson 的置信度门槛。必须与 Reflector 写入门槛**用同一个值**，
        # 否则会出现"写出来了但读不到"（0.5 的教训被 0.6 的读门槛滤掉，踩过）。
        self.lesson_threshold = float(lesson_threshold)

    # ---- 主循环 ----
    def run(self, goal: str) -> RunResult:
        caps = self.backend.capabilities()

        if self.planner is None:
            return RunResult(ok=False, goal=goal, steps=0, failures=0, replans=0,
                             stop_reason="未配置 Planner")

        v = self._view()
        plan = self.planner.plan(goal, v, self.store.active(self.lesson_threshold), caps)
        if plan is None:
            return RunResult(ok=False, goal=goal, steps=0, failures=0, replans=0,
                             final_pose=v.robot,
                             stop_reason="目标无法理解，或无可用路线")

        queue = list(plan.proposals)
        trace: List[TraceStep] = []
        steps = failures = replans = retries = 0

        while queue and steps < self.max_steps:
            proposal = queue.pop(0)
            res = self.backend.apply(proposal.to_action())
            steps += 1
            trace.append(TraceStep(
                step=steps, goal=goal, route=plan.route,
                action=f"{proposal.kind.value}({_fmt(proposal.params)})",
                ok=res.ok, reason=res.reason.value, detail=res.detail,
                sim_time=res.sim_time, note=proposal.rationale,
            ))

            if res.ok:
                continue

            # 被闸拒 / 参数不合法 —— 不是世界的经验，不反思、不重试，直接停
            if not res.learnable:
                return RunResult(
                    ok=False, goal=goal, steps=steps, failures=failures, replans=replans,
                    lessons=self.store.all(), trace=trace,
                    final_pose=self._view().robot,
                    stop_reason=f"被安全闸拒绝（{res.reason.value}）：{res.detail}",
                )

            # 真实失败 → 记录 → 反思 → 换路线
            failures += 1
            self.reflector.record_failure(
                trigger=f"route:{plan.route}", reason=res.reason, detail=res.detail)
            self.reflector.consolidate()

            if retries < self.max_retry:
                retries += 1
                new_plan = self.planner.replan(plan, self._view(),
                                               self.store.active(self.lesson_threshold), caps)
                if new_plan is not None:
                    plan = new_plan
                    queue = list(new_plan.proposals)
                    replans += 1
                    continue

            return RunResult(
                ok=False, goal=goal, steps=steps, failures=failures, replans=replans,
                lessons=self.store.all(), trace=trace,
                final_pose=self._view().robot,
                stop_reason=f"重试 {retries} 次仍失败：{res.reason.value}",
            )

        final = self._view()
        ok = not queue
        return RunResult(
            ok=ok, goal=goal, steps=steps, failures=failures, replans=replans,
            lessons=self.store.all(), trace=trace, final_pose=final.robot,
            stop_reason="完成" if ok else "步数预算耗尽",
        )

    # ---- 内部 ----
    def _view(self):
        """**只读**投影：Brain 永远拿不到可写的 WorldState。"""
        return view(from_observation(self.backend.observe()))


def _fmt(params) -> str:
    return ",".join(f"{k}={v}" for k, v in (params or {}).items())
