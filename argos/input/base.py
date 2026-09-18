"""输入层（Wave 3 / 指令 §20）—— 把"人说的话"变成 goal。

⚠️ 诚实边界：这里**不接 LLM、不接 ASR**（语音识别）。`SimulatedSpeechBackend` 是
**规则抽取**的口语模拟器：去语气词、找"去/到/前往"后面的地点短语、交给 resolver 校验。
认不出来就返回 `None`（**不猜**）—— 宁可说"没听懂"，也不要瞎执行。
"""
from __future__ import annotations

from typing import Callable, Optional, Protocol

__all__ = ["InputBackend", "Resolver"]


#: 把"地点短语"解析成地点名；认不出返回 None（通常就是 Planner.resolve_target）
Resolver = Callable[[str], Optional[str]]


class InputBackend(Protocol):
    name: str

    def goal_from(self, utterance: str) -> Optional[str]:
        """一句话 → goal（认不出返回 None，不许猜）。"""
        ...  # pragma: no cover - 协议
