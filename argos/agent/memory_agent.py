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
