"""Reflector —— 把失败变成 Planner 能用的 Lesson（Phase 4）。

旧系统在这里的病：`reflection_text` 写完就没人读了（`brain.py:674` 甚至把反思条目
排除在候选之外）。这一版的三条硬约束：

  1. **产物必须是结构化的 Lesson**（trigger / avoid / prefer / evidence / confidence），
     不是一段话；
  2. **必须有证据**（evidence 来自真实 ActionResult 的 detail），不许编造；
  3. **必须达到阈值才生效**（min_hits + min_confidence），
     防"一次偶发就永久绕行" —— 这会让 agent 变得胆小且不可信。

被闸拒（SAFETY_REJECTED / INVALID_PARAMS）**不算世界给的经验**，不产生 Lesson。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from argos.agent.interfaces import FailReason, Lesson
from argos.agent.memory_agent import DEFAULT_MIN_CONFIDENCE, LessonStore

__all__ = ["Reflector"]


@dataclass
class Reflector:
    """累计同类失败 → 够了就产出 Lesson。

    `alternatives` 告诉它"避开 A 之后该走哪条"，例如 `{"north": "south", "south": "north"}`。
    """
    store: LessonStore = field(default_factory=LessonStore)
    alternatives: Dict[str, str] = field(default_factory=dict)
    min_hits: int = 2
    min_confidence: float = DEFAULT_MIN_CONFIDENCE
    _counts: Dict[Tuple[str, str], int] = field(default_factory=dict)
    _evidence: Dict[Tuple[str, str], List[str]] = field(default_factory=dict)

    def record_failure(self, *, trigger: str, reason: FailReason,
                       detail: str = "") -> int:
        """记一次失败，返回该 (trigger, reason) 的累计次数。

        只有 LEARNING_REASONS 里的原因才记 —— 闸的拒绝不进这里。
        """
        if not isinstance(reason, FailReason) or reason not in _learnable():
            return 0
        key = (trigger, reason.value)
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
            )
            out.append(self.store.add(lesson))
        return out

    def counts(self) -> Dict[Tuple[str, str], int]:
        return dict(self._counts)


def _learnable():
    from argos.agent.interfaces import LEARNING_REASONS
    return LEARNING_REASONS
