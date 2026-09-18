"""Agent 记忆：三层（Episodic / Semantic / Procedural）+ 滑窗统计（Phase 4 / Wave 2）。

对应指令 §9 的三类记忆：

| 层 | 存什么 | 例子 | 谁消费 |
|---|---|---|---|
| **Episodic（情节）** | 每次尝试的**原始事件**（成败都记） | "ep1 走 north 失败，被 north_block 挡住" | 人审阅 / 统计原料 |
| **Semantic（语义）** | 从事件里归纳的**规律**（滑窗统计） | "north 最近 3 次里失败 2 次（失败率 0.67）" | Planner **软降权** |
| **Procedural（程序性）** | 可直接执行的**策略** | "避开 north，改走 south" | Planner **硬避开** |

两条设计要点：

1. **成败成对记录**（B4）：只记失败会得出"这条路失败过"，但没有**分母** ——
   也就无法区分"走 1 次失败 1 次"和"走 5 次失败 1 次"。所以每次尝试都记，成功也算。
2. **Semantic 用滑窗而不是累计**（B3）：累计统计会让旧证据永久压着，
   滑窗（只保留最近 `window` 次尝试）天然实现"遗忘"，对齐非平稳老虎机里的 SW-TS 思路。
   ⚠️ 但滑窗**不能替代复核**：不去尝试就不会产生新观测，窗口永远停在旧数据上 ——
   所以 `revalidate_every`（主动试探）与滑窗是互补的，不是二选一。

本层是纯内存的（进程内），无 I/O、无随机 —— 同 seed 可复现。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from argos.agent.interfaces import FailReason, Lesson

#: 低于这个置信度的 Lesson 不参与规划（防"一次偶发就永久绕行"）
DEFAULT_MIN_CONFIDENCE = 0.6

#: Semantic 层默认只看最近几次尝试（滑窗）
DEFAULT_WINDOW = 3
#: 软降权的最小观测数：少于这个数**不允许**影响路线选择（防一次偶发就改道）
DEFAULT_MIN_OBSERVATIONS = 2
#: 软降权的最小**失败次数**：与 Procedural 的 `min_hits=2` 同一纪律 ——
#: "失败两次才算规律"。少了这条，`[失败, 成功]`（失败率 0.5）就会把路线降权，
#: 等于一次偶发就改道（这正是我们要避免的病；实测踩到过）。
DEFAULT_MIN_FAILURES = 2
#: 失败率达到这个数才算"这条路线不太行"
DEFAULT_SOFT_THRESHOLD = 0.5


class MemoryKind(str, Enum):
    """指令 §9 的三类记忆。"""
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


@dataclass(frozen=True)
class EpisodeEvent:
    """**Episodic**：一次尝试的原始记录（成功也记，失败也记）。

    刻意区分两个"成功"：

    * `route_ok` —— **这条路线本身走顺了没有**（Semantic 层统计用的就是它）。
      例：走 north 被挡 → 换 south 到达，`route_ok=False`（north 确实有问题），
      但 `episode_ok=True`（任务完成了）。把两者混为一谈会让统计失真。
    * `episode_ok` —— 整个 episode 的任务是否完成。
    """
    episode: int
    goal: str
    route: Optional[str]
    route_ok: bool
    episode_ok: bool
    failures: int = 0
    reason: Optional[str] = None      # 第一次失败的原因（有的话）
    detail: str = ""
    sim_time: float = 0.0

    @property
    def kind(self) -> MemoryKind:
        return MemoryKind.EPISODIC


@dataclass(frozen=True)
class RouteStats:
    """**Semantic**：某条路线在**最近 window 次尝试**里的表现。"""
    route: str
    attempts: int
    failures: int
    window: int

    @property
    def failure_rate(self) -> float:
        return self.failures / self.attempts if self.attempts else 0.0

    @property
    def kind(self) -> MemoryKind:
        return MemoryKind.SEMANTIC

    def describe(self) -> str:
        return (f"{self.route}：最近 {self.attempts} 次尝试里失败 {self.failures} 次"
                f"（失败率 {self.failure_rate:.2f}）")


@dataclass
class LessonStore:
    lessons: Dict[str, Lesson] = field(default_factory=dict)

    def add(self, lesson: Lesson, episode: int = 0) -> Lesson:
        """同一条经验重复出现 → hits 累加、confidence 提高（不重复建条目）。

        若该条目此前已被反证失效，则**复活**它 —— 环境可能又变回去了，
        「失效」不等于「永久作废」。
        """
        old = self.lessons.get(lesson.id)
        if old is None:
            self.lessons[lesson.id] = Lesson(
                id=lesson.id, trigger=lesson.trigger, avoid=lesson.avoid,
                prefer=lesson.prefer, evidence=lesson.evidence,
                confidence=lesson.confidence, hits=lesson.hits, scope=lesson.scope,
                status="active",
                history=lesson.history or (f"support@ep{episode}",),
                created_episode=episode, updated_episode=episode,
            )
            return self.lessons[lesson.id]

        reinstate = old.status != "active"
        merged = Lesson(
            id=old.id, trigger=old.trigger, avoid=old.avoid, prefer=old.prefer,
            evidence=(old.evidence + " | " + lesson.evidence)[:400],
            confidence=lesson.confidence, hits=old.hits + 1, scope=old.scope,
            status="active",
            history=old.history + ((f"reinstate@ep{episode}",) if reinstate
                                   else (f"support@ep{episode}",)),
            created_episode=old.created_episode, updated_episode=episode,
        )
        self.lessons[old.id] = merged
        return merged

    def active(self, min_confidence: float = DEFAULT_MIN_CONFIDENCE) -> List[Lesson]:
        """参与规划的经验（**只算生效中的**，按置信度过滤）。"""
        return [l for l in self.lessons.values()
                if l.status == "active" and l.confidence >= min_confidence]

    def invalidated(self) -> List[Lesson]:
        """已被反证推翻的教训 —— **保留下来供审计**，不参与规划。"""
        return [l for l in self.lessons.values() if l.status != "active"]

    def avoided(self, min_confidence: float = DEFAULT_MIN_CONFIDENCE) -> Tuple[str, ...]:
        """当前应该避开的东西（路线名 / 区域名）。"""
        return tuple(l.avoid for l in self.active(min_confidence))

    def weaken(self, avoid: str, episode: int = 0) -> Optional[Lesson]:
        """**反证**：有人走通了这条被避开的路线 → 教训降一级。

        这是治"一次偶发被当成永久教训"的关键一步 —— 教训必须能被撤销，
        否则环境恢复了、agent 还在绕远路。

        规则：`hits -= 1` 并重算置信度（`hits/(hits+1)`）；降到 0 → **标记失效**。
        ⚠️ **不删除**：删掉就再也查不到"当初学到过什么、又是被什么推翻的"。
        失效的条目留在库里（`invalidated()` 可查），若日后又积累到证据会**复活**。
        """
        for l in self.lessons.values():
            if l.avoid != avoid or l.status != "active":
                continue
            hits = l.hits - 1
            history = l.history + (f"counter_evidence@ep{episode}",)
            if hits <= 0:
                out = Lesson(
                    id=l.id, trigger=l.trigger, avoid=l.avoid, prefer=l.prefer,
                    evidence=(l.evidence + f" | 反证：{avoid} 后来走通了")[:400],
                    confidence=0.0, hits=0, scope=l.scope,
                    status="invalidated", history=history,
                    created_episode=l.created_episode, updated_episode=episode,
                )
            else:
                out = Lesson(
                    id=l.id, trigger=l.trigger, avoid=l.avoid, prefer=l.prefer,
                    evidence=(l.evidence + f" | 反证：{avoid} 后来走通了")[:400],
                    confidence=min(0.95, hits / (hits + 1.0)), hits=hits,
                    scope=l.scope, status="active", history=history,
                    created_episode=l.created_episode, updated_episode=episode,
                )
            self.lessons[l.id] = out
            return out
        return None

    def all(self) -> List[Lesson]:
        return list(self.lessons.values())

    def get(self, lesson_id: str) -> Optional[Lesson]:
        return self.lessons.get(lesson_id)

    def clear(self) -> None:
        self.lessons.clear()


@dataclass
class AgentMemory:
    """三层记忆的统一入口（指令 §9）。

    Planner 只读它给出的**两类结论**：
      * `procedural_lessons()` → 硬避开（够证据才升级上来的策略）
      * `soft_penalty()`       → 软降权（Semantic 层的滑窗失败率）
    """

    procedural: LessonStore = field(default_factory=LessonStore)
    window: int = DEFAULT_WINDOW
    min_observations: int = DEFAULT_MIN_OBSERVATIONS
    min_failures: int = DEFAULT_MIN_FAILURES
    soft_threshold: float = DEFAULT_SOFT_THRESHOLD
    episodic: List[EpisodeEvent] = field(default_factory=list)
    #: route → 最近 window 次尝试是否成功（True=成功）
    windows: Dict[str, List[bool]] = field(default_factory=dict)

    # ---- 写 ----
    def record_episode(self, event: EpisodeEvent) -> None:
        """记一次尝试（**成败都记** —— 没有分母就算不出失败率）。"""
        self.episodic.append(event)
        if not event.route:
            return
        hist = self.windows.setdefault(event.route, [])
        hist.append(bool(event.route_ok))    # 统计的是"路线本身顺不顺"，不是任务有没有完成
        if len(hist) > self.window:          # 滑窗：超出就丢最旧的
            del hist[: len(hist) - self.window]

    # ---- 读 ----
    def semantic(self) -> List[RouteStats]:
        """把滑窗摊成可读的规律（按路线名排序，确定性）。"""
        return [RouteStats(route=r, attempts=len(h), failures=sum(1 for ok in h if not ok),
                           window=self.window)
                for r, h in sorted(self.windows.items())]

    def soft_penalty(self) -> Dict[str, float]:
        """Semantic → 软降权字典 `{路线: 惩罚值}`（值越大越不优先）。

        三道门槛**都不能省**（它们的共同目的是"别把偶发当规律"）：

        1. 观测数 ≥ `min_observations`；
        2. **失败次数 ≥ `min_failures`** —— 与 Procedural 的 `min_hits=2` 同一纪律。
           少了这条，`[失败, 成功]`（失败率 0.5）就会降权，等于一次偶发就改道；
        3. 失败率 ≥ `soft_threshold`。
        """
        out: Dict[str, float] = {}
        for st in self.semantic():
            if (st.attempts >= self.min_observations
                    and st.failures >= self.min_failures
                    and st.failure_rate >= self.soft_threshold):
                out[st.route] = st.failure_rate
        return out

    def procedural_lessons(self, min_confidence: float = DEFAULT_MIN_CONFIDENCE) -> List[Lesson]:
        return self.procedural.active(min_confidence)

    def describe(self) -> Dict[str, list]:
        """给 CLI / trace 用的人类可读快照。"""
        return {
            "episodic": [f"ep{e.episode} {e.route or '-'} "
                         f"路线{'顺' if e.route_ok else '不顺'}/"
                         f"任务{'完成' if e.episode_ok else '未完成'}"
                         f"{('（' + e.reason + '）') if e.reason else ''}"
                         for e in self.episodic],
            "semantic": [st.describe() for st in self.semantic()],
            "procedural": [f"避开 {l.avoid} → 改用 {l.prefer}"
                           f"（{l.status}，置信度 {l.confidence:.2f}）"
                           for l in self.procedural.all()],
        }

    def clear(self) -> None:
        self.episodic.clear()
        self.windows.clear()
        self.procedural.clear()
