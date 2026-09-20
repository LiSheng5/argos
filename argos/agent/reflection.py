"""Reflector —— 把失败变成 Planner 能用的 Lesson（Phase 4）。

旧系统在这里的病：`reflection_text` 写完就没人读了（`brain.py:674` 甚至把反思条目
排除在候选之外）。这一版的三条硬约束：

  1. **产物必须是结构化的 Lesson**（trigger / avoid / prefer / evidence / confidence），
     不是一段话；
  2. **必须有证据**（evidence 来自真实 ActionResult 的 detail），不许编造；
  3. **必须达到阈值才生效**（min_hits + min_confidence），
     防"一次偶发就永久绕行" —— 这会让 agent 变得胆小且不可信；
  4. **教训必须能被证伪，但也要防"被一次偶然证伪"**：走通了被避开的路线会削弱教训，
     但要求**连续两次**成功复核（`record_success`，D-02）—— 与第 3 条是同一条纪律的两端：
     门槛进、门槛出，都别被单次观测牵着走。

被闸拒（SAFETY_REJECTED / INVALID_PARAMS）**不算世界给的经验**，不产生 Lesson。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from argos.agent.interfaces import FailReason, Lesson
from argos.agent.memory_agent import DEFAULT_MIN_CONFIDENCE, LessonStore

__all__ = ["Reflector", "ROUTE_REASONS"]

#: 只有这些失败原因意味着"**换条路能解决**"，才允许生成"避开某条路线"的 Lesson。
#: 反例：低电量（BATTERY_LOW）时路线没问题，学成"北线不能走"就是**错误因果**
#: —— 这是本轮 benchmark 实测暴露出来的限制，见 `文档/BENCHMARK.md`。
ROUTE_REASONS = frozenset({FailReason.OBSTACLE_BLOCKED, FailReason.PATH_INVALID})

#: 反证一条教训需要**连续**成功复核几次（D-02）。
#: 取 2：一次成功可能是偶然（噪声/瞬时抖动），能**复现**的成功才配推翻已积累的教训。
_REQUIRED_PROBE_SUCCESSES = 2


@dataclass
class Reflector:
    """累计同类失败 → 够了就产出 Lesson。

    `alternatives` 告诉它"避开 A 之后该走哪条"，例如 `{"north": "south", "south": "north"}`。
    """
    store: LessonStore = field(default_factory=LessonStore)
    alternatives: Dict[str, str] = field(default_factory=dict)
    min_hits: int = 2
    min_confidence: float = DEFAULT_MIN_CONFIDENCE
    #: 每隔 N 个 episode 主动复核一次被避开的路线（0 = 不复核）。
    #: 没有复核的教训会**永久化** —— 环境恢复了 agent 还在绕远路。
    revalidate_every: int = 0
    _counts: Dict[Tuple[str, str], int] = field(default_factory=dict)
    _evidence: Dict[Tuple[str, str], List[str]] = field(default_factory=dict)
    _episodes: int = 0
    _seen_this_episode: Dict[str, bool] = field(default_factory=dict)
    #: route → **连续**成功复核的次数。一次成功不再立刻推翻教训（D-02）：
    #: "偶然走通一次"和"环境真的恢复了"要区分开 —— 后者应当能稳定复现。
    _probe_successes: Dict[str, int] = field(default_factory=dict)

    # ---- episode 边界（证据独立性的关键）----
    def begin_episode(self) -> None:
        """每个 episode 开始时调用：清掉"本回合已计过"的标记。

        没有这一步，一次 episode 里连撞两次就会被当成 **2 条独立证据**，
        `min_hits=2` 也就形同虚设 —— "两次独立尝试才学"这个意图会落空。
        """
        self._episodes += 1
        self._seen_this_episode.clear()

    @property
    def episode_index(self) -> int:
        """已经历的 episode 数（public 出口，别在外面读 `_episodes`）。"""
        return self._episodes

    def should_revalidate(self) -> bool:
        # `_episodes > 0` 不能省：计数从 0 起，`0 % N == 0` 会让"一次都没跑过"也判成该复核。
        return (self.revalidate_every > 0 and self._episodes > 0
                and self._episodes % self.revalidate_every == 0)

    def probe_streak(self, route: str) -> int:
        """该路线当前已累计的**连续成功复核**次数（public 出口，别在外面读 `_probe_successes`）。"""
        return self._probe_successes.get(route, 0)

    def record_success(self, trigger: str, detail: str = "") -> Optional[Lesson]:
        """走通了某条**曾被避开**的路线 → 反证 → 削弱对应教训。

        **连续两次**成功复核才算反证成立（D-02）。只成功一次不算：
        一次成功既可能是"环境真恢复了"，也可能只是**偶然走通**（噪声、瞬时抖动）。
        要求可复现，才配得上"推翻一条已经积累到 min_hits 的教训"。

        反证成立之后才**清空该路线的失败证据计数**：教训重新激活
        必须重新积累 `min_hits` 次独立失败 —— 否则"刚被推翻的教训被一次偶发立刻复活"，
        等于没治。

        返回：真正削弱了教训时返回新的 Lesson；只是累计到第 1 次成功时返回 None
        （调用方据此判断"还没到能清 Semantic 滑窗的时候"，见 `brain.AgentBrain.finish`）。
        """
        route = trigger.split(":", 1)[-1]
        self._probe_successes[route] = self._probe_successes.get(route, 0) + 1
        if self._probe_successes[route] < _REQUIRED_PROBE_SUCCESSES:
            return None

        self._probe_successes.pop(route, None)
        out = self.store.weaken(route, episode=self._episodes)
        for key in [k for k in self._counts if k[0] == trigger]:
            self._counts.pop(key, None)
            self._evidence.pop(key, None)
        return out

    def record_failure(self, *, trigger: str, reason: FailReason,
                       detail: str = "") -> int:
        """记一次失败，返回该 (trigger, reason) 的累计次数。

        只有 LEARNING_REASONS 里的原因才记 —— 闸的拒绝不进这里。
        """
        if not isinstance(reason, FailReason) or reason not in _learnable():
            return 0
        if reason not in ROUTE_REASONS:
            # 记数是记数，但**不生成"避开这条路"的经验** —— 原因不在这里。
            return 0
        # 同一 episode 内同类失败只算 **1 条独立证据**（去重）
        dedup = f"{trigger}|{reason.value}"
        if self._seen_this_episode.get(dedup):
            return self._counts.get((trigger, reason.value), 0)
        self._seen_this_episode[dedup] = True

        key = (trigger, reason.value)
        # 路线再次失败 → 先前的"连续成功"断链，必须重新数两次（D-02）。
        # 注意这里只对**路线相关**失败生效：上面已提前 return，低电量/定位漂移不会误清。
        route = trigger.split(":", 1)[-1]
        self._probe_successes.pop(route, None)
        self._counts[key] = self._counts.get(key, 0) + 1
        self._evidence.setdefault(key, []).append(detail or reason.value)
        return self._counts[key]

    def consolidate(self) -> List[Lesson]:
        """把够了次数的失败固化成 Lesson（并写进 store）。"""
        out: List[Lesson] = []
        for (trigger, reason), hits in sorted(self._counts.items()):
            if hits < self.min_hits:
                continue
            # 置信度随证据增长，但封顶 0.95 —— 不假装"绝对确定"
            confidence = min(0.95, hits / (hits + 1.0))
            if confidence < self.min_confidence:
                continue
            route = trigger.split(":", 1)[-1]
            prefer = self.alternatives.get(route, "")
            if not prefer:
                continue          # 不知道该改走哪条 → 不产生没用的 Lesson
            lesson = Lesson(
                id=f"lesson:{trigger}:{reason}",
                trigger=trigger,
                avoid=route,
                prefer=prefer,
                evidence=" | ".join(self._evidence.get((trigger, reason), []))[:300],
                confidence=confidence,
                hits=hits,
                scope=f"route:{route}",
            )
            out.append(self.store.add(lesson, episode=self._episodes))
        return out

    def counts(self) -> Dict[Tuple[str, str], int]:
        return dict(self._counts)


def _learnable():
    from argos.agent.interfaces import LEARNING_REASONS
    return LEARNING_REASONS
