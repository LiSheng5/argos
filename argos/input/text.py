"""文本输入（Wave 3 / 指令 §20）—— 最朴素的一层：直接就是 goal。"""
from __future__ import annotations

from typing import Optional

__all__ = ["TextInputBackend"]


class TextInputBackend:
    """文本直通：去掉首尾空白即可，不做任何"理解"（不该在这一层加戏）。"""
    name = "text"

    def goal_from(self, utterance: str) -> Optional[str]:
        if not utterance:
            return None
        text = utterance.strip()
        return text or None
