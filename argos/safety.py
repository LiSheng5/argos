"""真机安全闸门 SafetyGate（对应 npc/reviewer.py 的 A 审查升级版）。
不可绕过：所有 RobotExecutor 调用先过 check()；参照 Claudia 三级电量门控。

2026-08-29 评审后修订（见 文档/代码评审_20260829.md）：
  - P1-4：禁触字段扫描改为递归 —— 原来只扫 params.values() 顶层，
    navigate 的 waypoints 里嵌的 dict 是漏的；
  - P1-6：电量未知（执行器没上报 battery_pct）不再默认满电放行，
    改按 SAFE_BATT 档处理（fail-closed）。仿真里看不出来，真机上
    "传感器没接 = 满电" 是最危险的默认值。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from argos.primitives import ALLOWED_MOTION_ACTIONS, FORBIDDEN_MOTION_TOKENS

# 工作空间可达边界（米）—— 示例值，真机按场地配置
BOUNDARIES = {"x_min": -10.0, "x_max": 10.0, "y_min": -10.0, "y_max": 10.0}
SAFE_BATT = 10.0      # 电量 <= 10%：仅安全原语
NORMAL_BATT = 20.0    # 电量 <= 20%：禁止长途移动(navigate)
SAFE_ONLY = ("move_to",)


def battery_of(state: Dict) -> Optional[float]:
    """读电量；没上报/读不出来 → None（未知）。

    调用方必须按"未知 = 保守"处理，不要再兜底成 100。
    """
    if not state:
        return None
    v = state.get("battery_pct")
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _scan_forbidden(obj: Any) -> bool:
    """递归扫参数树：任意一层的字段名或字符串值命中禁触词 → True。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in FORBIDDEN_MOTION_TOKENS or _scan_forbidden(v):
                return True
        return False
    if isinstance(obj, (list, tuple)):
        return any(_scan_forbidden(x) for x in obj)
    if isinstance(obj, str):
        low = obj.lower()
        return any(tok in low for tok in FORBIDDEN_MOTION_TOKENS)
    return False


class SafetyGate:
    def __init__(self, boundaries: Dict[str, float] | None = None) -> None:
        self.estop = False
        self.boundaries = dict(boundaries or BOUNDARIES)

    def set_estop(self, on: bool) -> None:
        self.estop = on

    def check(self, action: str, params: Dict, state: Dict) -> Tuple[bool, str]:
        # 1) 白名单
        if action not in ALLOWED_MOTION_ACTIONS:
            return False, f"不允许的动作：{action}"
        # 2) 禁触字段（纵深防御，递归到 waypoints 内部）
        if _scan_forbidden(params or {}):
            return False, "参数涉及不安全的字段"
        # 3) 急停 -> 全拒
        if self.estop:
            return False, "急停已触发，所有动作拒绝"
        # 4) 电量门控（未知 = 按最低档，fail-closed）
        batt = battery_of(state)
        if batt is None:
            if action not in SAFE_ONLY:
                return False, "电量未知，仅允许安全原语"
        else:
            if batt <= SAFE_BATT and action not in SAFE_ONLY:
                return False, f"电量过低({batt:.0f}%)，仅允许安全原语"
            if batt <= NORMAL_BATT and action == "navigate":
                return False, f"电量({batt:.0f}%)不足以长途移动"
        # 5) 可达边界（move_to 单点 / navigate 途经点）
        coords = [params] if action == "move_to" else (params or {}).get("waypoints", [])
        if isinstance(coords, dict):
            coords = [coords]
        for pt in coords or []:
            x = float(pt.get("x", 0.0)); y = float(pt.get("y", 0.0))
            if not (self.boundaries["x_min"] <= x <= self.boundaries["x_max"]
                    and self.boundaries["y_min"] <= y <= self.boundaries["y_max"]):
                return False, "目标坐标超出工作空间边界"
        return True, ""
