"""感知：把执行器状态拼成"观察文本"，喂给大脑上下文（对应 npc/world.observe）。
接地约束（同 npc）：大脑只讲观察/记忆里真实存在的事，禁止编造。
"""
from __future__ import annotations

from typing import Dict


def observe_text(state: Dict) -> str:
    lines = [
        f"当前位置: x={state.get('x', 0):.1f} y={state.get('y', 0):.1f} 朝向={state.get('yaw', 0):.0f}°",
        f"电量: {state.get('battery_pct', 100):.0f}%",
        f"夹爪目标: {state.get('gripper') or '空'}",
    ]
    if state.get("estop"):
        lines.append("急停已触发（禁止移动）")
    return "\n".join(lines)