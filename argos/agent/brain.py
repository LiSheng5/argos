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
from argos.agent.memory_agent import (
    DEFAULT_MIN_CONFIDENCE,
    AgentMemory,
    EpisodeEvent,
    LessonStore,
)
from argos.agent.planner import Plan, Planner
from argos.agent.reflection import ROUTE_REASONS, Reflector
from argos.world.state import from_observation, view

__all__ = ["TraceStep", "RunResult", "AgentBrain"]


def _is_route_reason(reason) -> bool:
    """这个失败是不是"这条路的问题"？

    只有 `OBSTACLE_BLOCKED` / `PATH_INVALID` 算 —— 与 Procedural 层用**同一份**判据
    （`reflection.ROUTE_REASONS`），避免两层对"什么算路线失败"各有各的标准。
    接受 `FailReason` 或它的字符串值（trace 里存的是字符串）。
    """
    if reason is None:
        return False
    if isinstance(reason, FailReason):
        return reason in ROUTE_REASONS
    try:
        return FailReason(reason) in ROUTE_REASONS
    except ValueError:
        return False


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
        memory: Optional[AgentMemory] = None,
    ) -> None:
        self.backend = backend
        self.planner = planner
        self.reflector = reflector or Reflector()
        # 三层记忆（可选）。给了就用它的 procedural 层作为"硬避开"的来源，
        # 并用 semantic 层（滑窗失败率）做软降权 —— 这是指令 §9「Planner 按任务选不同记忆」的落点。
        self.memory = memory
        self.store = (memory.procedural if memory is not None
                      else (store or self.reflector.store))
        self.max_steps = int(max_steps)
        self.max_retry = int(max_retry)
        # 读 Lesson 的置信度门槛。必须与 Reflector 写入门槛**用同一个值**，
        # 否则会出现"写出来了但读不到"（0.5 的教训被 0.6 的读门槛滤掉，踩过）。
        self.lesson_threshold = float(lesson_threshold)

    # ---- 主循环 ----
    def run(self, goal: str) -> RunResult:
        caps = self.backend.capabilities()
        # 证据独立性 + 复核节奏都挂在 reflector 上（它是唯一跨 episode 的账本之一）
        self.reflector.begin_episode()

        if self.planner is None:
            return RunResult(ok=False, goal=goal, steps=0, failures=0, replans=0,
                             stop_reason="未配置 Planner")

        trace: List[TraceStep] = []

        def finish(ok: bool, stop_reason: str, plan=None,
                   steps: int = 0, failures: int = 0, replans: int = 0) -> RunResult:
            """统一出口：处理"复核成功 → 反证"与"记一条情节记忆"。"""
            if plan is not None and plan.is_probe and ok and failures == 0:
                # 试探的那条路线**一次都没失败** —— 说明它已经通了，撤销旧教训。
                self.reflector.record_success(f"route:{plan.route}")
                # 受控干预的结果**比日常观测更强**（干预式验证的要点）：
                # 清掉该路线的滑窗，让它从"这次确证的成功"重新起算。
                # 否则会出现两层打架：Procedural 已撤销，Semantic 还压着这条路不让走。
                if self.memory is not None:
                    self.memory.windows.pop(plan.route, None)

            # Episodic 层：**成败都记**（Semantic 层要分母才能算失败率）
            if self.memory is not None and plan is not None:
                first_bad = next((t for t in trace if not t.ok), None)
                # ⚠️ `route_ok` 只由**路线相关**的失败决定（OBSTACLE_BLOCKED / PATH_INVALID）。
                #    定位漂移、超时、执行器故障、缺传感器、电量低 —— 都不是"这条路的问题"，
                #    却曾经被算成"路线不顺" → 语义层于是把路降权、agent 因为定位漂移改走远路。
                #    （补覆盖缺口时实测抓到：非路线失败场景里学习臂比无记忆臂多花 2 个动作，
                #     失败数却完全一样 —— 那不是学得准，是**学错了对象**。）
                route_bad = any(
                    not t.ok and _is_route_reason(t.reason) for t in trace)
                self.memory.record_episode(EpisodeEvent(
                    episode=self.reflector.episode_index, goal=goal,
                    route=(trace[0].route if trace and trace[0].route else plan.route),
                    route_ok=not route_bad, episode_ok=ok, failures=failures,
                    reason=(first_bad.reason if first_bad else None),
                    detail=(first_bad.detail if first_bad else ""),
                    sim_time=self._view().sim_time,
                ))

            return RunResult(ok=ok, goal=goal, steps=steps, failures=failures,
                             replans=replans, lessons=self.store.all(), trace=trace,
                             final_pose=self._view().robot, stop_reason=stop_reason)

        # Semantic 层 → 软降权（只影响路线先后顺序，不淘汰候选）
        soft = self.memory.soft_penalty() if self.memory is not None else None

        v = self._view()
        plan = self.planner.plan(goal, v, self.store.active(self.lesson_threshold), caps,
                                 probe=self.reflector.should_revalidate(),
                                 soft_penalty=soft)
        if plan is None:
            return finish(False, "目标无法理解，或无可用路线")

        queue = list(plan.proposals)
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
                return finish(False, f"被安全闸拒绝（{res.reason.value}）：{res.detail}",
                              steps=steps, failures=failures, replans=replans)

            # 真实失败 → 记录 → 反思 → 换路线
            failures += 1
            self.reflector.record_failure(
                trigger=f"route:{plan.route}", reason=res.reason, detail=res.detail)
            self.reflector.consolidate()

            if retries < self.max_retry:
                retries += 1
                new_plan = self.planner.replan(
                    plan, self._view(), self.store.active(self.lesson_threshold), caps,
                    soft_penalty=(self.memory.soft_penalty() if self.memory else None))
                if new_plan is not None:
                    plan = new_plan
                    queue = list(new_plan.proposals)
                    replans += 1
                    continue

            return finish(False, f"重试 {retries} 次仍失败：{res.reason.value}",
                          steps=steps, failures=failures, replans=replans)

        ok = not queue
        return finish(ok, "完成" if ok else "步数预算耗尽", plan=plan,
                      steps=steps, failures=failures, replans=replans)

    # ---- 内部 ----
    def _view(self):
        """**只读**投影：Brain 永远拿不到可写的 WorldState。"""
        return view(from_observation(self.backend.observe()))


def _fmt(params) -> str:
    return ",".join(f"{k}={v}" for k, v in (params or {}).items())
