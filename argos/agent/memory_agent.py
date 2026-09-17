"""Lesson 存取（Phase 4）。

为什么单独一个 store，而不是直接塞进旧 `argos/memory.py`：
  * 旧记忆是"事件卡 + 语义检索"，面向"狗说了什么/做了什么"；
  * Lesson 是**给 Planner 用的结构化经验**（trigger / avoid / prefer / evidence），
    要能被**按字段命中**，不能被语义相似度糊掉 —— 换路线的判断必须是确定的。
  * 将来（Phase 7）可以把 Lesson 同步回旧记忆卡做长期留存；本轮先保证闭环成立。

本 store 是纯内存的（进程内），无 I/O、无随机 —— 同 seed 可复现。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from argos.agent.interfaces import Lesson

#: 低于这个置信度的 Lesson 不参与规划（防"一次偶发就永久绕行"）
DEFAULT_MIN_CONFIDENCE = 0.6


@dataclass
class LessonStore:
    lessons: Dict[str, Lesson] = field(default_factory=dict)

    def add(self, lesson: Lesson) -> Lesson:
        """同一条经验重复出现 → hits 累加、confidence 提高（不重复建条目）。"""
        old = self.lessons.get(lesson.id)
        if old is None:
            self.lessons[lesson.id] = lesson
            return lesson
        merged = Lesson(
            id=old.id, trigger=old.trigger, avoid=old.avoid, prefer=old.prefer,
            evidence=(old.evidence + " | " + lesson.evidence)[:400],
            confidence=lesson.confidence, hits=old.hits + 1,
        )
        self.lessons[old.id] = merged
        return merged

    def active(self, min_confidence: float = DEFAULT_MIN_CONFIDENCE) -> List[Lesson]:
        """参与规划的经验（按置信度过滤）。"""
        return [l for l in self.lessons.values() if l.confidence >= min_confidence]

    def avoided(self, min_confidence: float = DEFAULT_MIN_CONFIDENCE) -> Tuple[str, ...]:
        """当前应该避开的东西（路线名 / 区域名）。"""
        return tuple(l.avoid for l in self.active(min_confidence))

    def all(self) -> List[Lesson]:
        return list(self.lessons.values())

    def get(self, lesson_id: str) -> Optional[Lesson]:
        return self.lessons.get(lesson_id)

    def clear(self) -> None:
        self.lessons.clear()
