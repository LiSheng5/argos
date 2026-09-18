"""输入层（Wave 3 / 指令 §20）：`人说的话 → goal`。

两个后端：`text`（直通）/ `speech`（口语规则抽取）。
⚠️ `speech` **不是语音识别**，只是把口语里的客套与语气词去掉、再抽目标短语。
"""
from typing import Callable, Dict

from argos.input.base import InputBackend, Resolver
from argos.input.speech import MOVE_VERBS, POLITE_WORDS, SimulatedSpeechBackend
from argos.input.text import TextInputBackend

__all__ = [
    "InputBackend", "Resolver", "INPUTS", "build_input",
    "TextInputBackend", "SimulatedSpeechBackend", "POLITE_WORDS", "MOVE_VERBS",
]


def build_input(name: str, resolver: Resolver) -> InputBackend:
    """按名字装配输入后端。不认识就明确报错（不静默退回 text）。"""
    if name == "text":
        return TextInputBackend()
    if name == "speech":
        return SimulatedSpeechBackend(resolver=resolver)
    raise KeyError(f"没有名为 {name!r} 的输入后端。当前可用：text、speech")


#: 可用名字（CLI 与测试共用，避免两处各写一份）
INPUTS: Dict[str, str] = {"text": "文本直通", "speech": "口语规则抽取（非语音识别）"}
