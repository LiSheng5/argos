"""口语输入（模拟，Wave 3 / 指令 §20）。

**这不是语音识别**，是"人说话通常带一堆客套和语气词"的**规则模拟**：

    "麻烦帮我去一下充电站吧"  →  "去充电站"

做法：去客套/语气词 → 找"去/到/前往/回"开头的动作短语 → 交给 resolver 校验。
认不出就返回 `None`（不猜、不硬凑）—— 上层会明确报"没听懂"。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from argos.input.base import Resolver

__all__ = ["SimulatedSpeechBackend", "POLITE_WORDS", "MOVE_VERBS"]

#: 客套 / 语气 / 填充词（口语里最常见的那批）
POLITE_WORDS = (
    "麻烦", "请", "帮我", "帮忙", "帮", "给我", "能不能", "可以", "麻烦你",
    "一下", "一趟", "去一下", "吧", "呢", "啊", "呀", "哦", "嗯", "谢谢", "谢谢啦",
    "那个", "就是", "然后", "现在", "立刻", "马上", "稍微",
)

#: 表示"要移动"的动词（找目标短语的锚点）
MOVE_VERBS = ("前往", "去往", "走到", "开到", "回到", "去", "到", "回", "来")

#: 结尾可能剩下的标点
_TRAILING = "。！？!?.，,、 \t\r\n"


@dataclass
class SimulatedSpeechBackend:
    """把口语化的一句 → goal。`resolver` 用来校验"这个地点名认不认"。"""
    resolver: Resolver
    name: str = "speech"
    stripped: List[str] = field(default_factory=list)

    def _clean(self, utterance: str) -> str:
        text = (utterance or "").strip()
        for w in POLITE_WORDS:
            text = text.replace(w, "")
        self.stripped.append(text)
        return text.strip(_TRAILING)

    def goal_from(self, utterance: str) -> Optional[str]:
        text = self._clean(utterance)
        if not text:
            return None

        # 1) 整句本身就能认出来 → 直接用（"去充电站"）
        if self.resolver(text) is not None:
            return text

        # 2) 从"动作动词"处截出目标短语（"从大厅去充电站" → "去充电站"）
        for verb in MOVE_VERBS:
            idx = text.find(verb)
            if idx < 0:
                continue
            cand = text[idx:].strip(_TRAILING)
            if cand and self.resolver(cand) is not None:
                return cand

        # 3) 认不出 → None。**不许猜**：宁可说没听懂，也不要瞎执行
        return None
