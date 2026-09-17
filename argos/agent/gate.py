"""ActionGate —— 新 runtime 的动作闸门（Phase 1）。

为什么**不复用旧 `argos/safety.py`**：
  1. 旧闸白名单写死在 `primitives.ALLOWED_MOTION_ACTIONS = ("move_to","navigate","grab","release")`
     —— 迷你世界需要的 `turn / wait / inspect` 会被它拒掉；
  2. 旧闸缺指令要求的**速度上限 / 超时 / 参数范围 / 缺字段 fail-closed**；
  3. 用户已决定旧闸冻结不改（`文档/SIM_FIRST_AUDIT.md` §2）。

所以这里新写一个**能力驱动**的闸：白名单来自 `EmbodimentCapabilities`，
并复用旧闸里两个纯函数（`battery_of` / `_scan_forbidden`）—— **import 而不改写**。

fail-closed 原则：未知动作、非法参数、缺必要字段、参数越界 —— 一律拒绝，**不兜底默认值**。
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple

from argos.agent.interfaces import (
    Action,
    ActionKind,
    EmbodimentCapabilities,
    FailReason,
    WorldState,
)
from argos.safety import _scan_forbidden  # 复用旧闸的禁触字段扫描（不改旧文件）
from argos.world.state import WorldView, view

# 各动作必需的字段（缺一个就拒，绝不默认补 0）
_REQUIRED: Dict[ActionKind, Tuple[str, ...]] = {
    ActionKind.MOVE: ("x", "y"),
    ActionKind.TURN: ("yaw",),
    ActionKind.WAIT: (),
    ActionKind.STOP: (),
    ActionKind.INSPECT: (),
    ActionKind.GRAB: ("target",),
    ActionKind.RELEASE: (),
}

# 数值型字段（必须是有限实数）
_NUMERIC = ("x", "y", "yaw", "speed", "duration", "timeout")

DEFAULT_BOUNDARIES = {"x_min": -20.0, "x_max": 20.0, "y_min": -20.0, "y_max": 20.0}


def _is_num(v: Any) -> bool:
    """有限实数（**bool 不算数**，避免 True 当 1 用）。"""
    if isinstance(v, bool):
        return False
    if not isinstance(v, (int, float)):
        return False
    return math.isfinite(float(v))


class ActionGate:
    """所有动作出口之前的那道闸。`SimulatorBackend.apply()` 是唯一调用者。"""

    def __init__(
        self,
        capabilities: EmbodimentCapabilities,
        boundaries: Optional[Dict[str, float]] = None,
        max_speed: Optional[float] = None,
        max_duration: float = 30.0,
        battery_min: float = 10.0,
    ) -> None:
        self.caps = capabilities
        self.boundaries = dict(boundaries or DEFAULT_BOUNDARIES)
        self.max_speed = float(max_speed if max_speed is not None else capabilities.max_speed)
        self.max_duration = float(max_duration)
        self.battery_min = float(battery_min)
        self.estop = False

    def set_estop(self, on: bool = True) -> None:
        self.estop = bool(on)

    def check(self, action: Action, world) -> Tuple[bool, FailReason, str]:
        """返回 `(ok, reason, detail)`。`world` 可为 WorldState 或 WorldView。"""
        w = world if isinstance(world, WorldView) else view(world)

        # 1) 急停 —— 全拒
        if self.estop:
            return False, FailReason.SAFETY_REJECTED, "急停已触发，所有动作拒绝"

        # 2) 能力白名单（未知动作 / 这个身体做不了 —— 都不放行）
        if not isinstance(action.kind, ActionKind):
            return False, FailReason.SAFETY_REJECTED, f"未知动作类型：{action.kind!r}"
        if not self.caps.supports(action.kind):
            return False, FailReason.SAFETY_REJECTED, f"当前身体不支持该动作：{action.kind.value}"

        params = action.params or {}

        # 3) 禁触字段（纵深防御，递归扫参数树）
        if _scan_forbidden(params):
            return False, FailReason.SAFETY_REJECTED, "参数涉及不安全的字段"

        # 4) 缺字段 / 类型错 / 非有限数 —— fail-closed
        for key in _REQUIRED[action.kind]:
            if key not in params:
                return False, FailReason.INVALID_PARAMS, f"缺少必要参数：{key}"
        for key in _NUMERIC:
            if key in params and not _is_num(params[key]):
                return False, FailReason.INVALID_PARAMS, f"参数 {key} 不是有限数字：{params[key]!r}"

        # 5) 参数范围：目标必须在工作空间内
        if action.kind == ActionKind.MOVE:
            x, y = float(params["x"]), float(params["y"])
            b = self.boundaries
            if not (b["x_min"] <= x <= b["x_max"] and b["y_min"] <= y <= b["y_max"]):
                return False, FailReason.SAFETY_REJECTED, "目标坐标超出工作空间边界"

        # 6) 速度上限
        speed = params.get("speed")
        if speed is not None and float(speed) > self.max_speed:
            return False, FailReason.SAFETY_REJECTED, f"速度 {float(speed)} 超过上限 {self.max_speed}"

        # 7) 超时 / 时长上限
        for key in ("duration", "timeout"):
            if key in params and float(params[key]) > self.max_duration:
                return False, FailReason.SAFETY_REJECTED, f"{key} {float(params[key])} 超过上限 {self.max_duration}"

        # 8) 电量门控 —— 低电量是**世界的真实状态**，所以当可学习失败处理（不是闸的错）
        if action.kind != ActionKind.STOP and w.battery <= self.battery_min:
            return False, FailReason.BATTERY_LOW, f"电量过低({w.battery:.1f}%)，不允许动作"

        return True, FailReason.OK, ""


def build_world_state(**kw) -> WorldState:  # 便捷构造，测试与 demo 用
    return WorldState(**kw)
