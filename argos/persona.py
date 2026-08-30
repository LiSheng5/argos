"""性格配置：persona.json 单一来源（可编辑文档，NPCSidekick 角色卡同思想）。

缺文件 / 读坏 / 缺字段 → 默认兜底（就是现在规则话术的口吻），
狗永远不会因为配置坏了而哑巴。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional

# 默认兜底 = 现役规则话术的口吻（无 LLM 时 brain.try_command/_ack 直接用它）
DEFAULT_PERSONA: Dict[str, str] = {
    "name": "阿戈斯",
    "personality": "忠诚、可靠的机器狗。话少，但每一句都算数。",
    "style": "一句话回答，口语化，偶尔带感叹号；听不懂就老实说。",
    "reflect_style": "用第一人称归纳自己做过的事，一两句话，不加新事。",
}

# 措辞生成的三条铁律（LLM 版和规则版共用同一套）
WROUGHT_RULES = (
    "1. 只基于给定的事实回话，禁止编造没发生的事；\n"
    "2. 一句话，不超过 40 字；\n"
    "3. 任务描述不许改动（说去门口就是去门口）。"
)


def _default_path() -> Path:
    return Path(__file__).resolve().parent / "persona.json"


def load_persona(path: Optional[str] = None) -> Dict[str, str]:
    """读性格 JSON；任何失败 → DEFAULT_PERSONA（不抛异常）。"""
    p = Path(path) if path else _default_path()
    if not path and not p.exists():
        p = Path(os.environ.get("ARGOS_PERSONA", str(p)))
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(DEFAULT_PERSONA)
    if not isinstance(data, dict):
        return dict(DEFAULT_PERSONA)
    out = dict(DEFAULT_PERSONA)
    for k in out:
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()
    return out


def system_prompt(persona: Dict[str, str]) -> str:
    """措辞生成的 system 消息（性格 + 风格 + 铁律）。"""
    return (
        f"你是{persona['name']}，一只宇树机器狗，负责对主人简短回话。\n"
        f"性格：{persona['personality']}\n"
        f"风格：{persona['style']}\n"
        f"铁律：\n{WROUGHT_RULES}\n"
        "只输出回复本身，不要引号、不要解释。"
    )
