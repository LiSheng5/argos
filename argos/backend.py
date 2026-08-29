"""RobotBackend：把"大脑决定做什么"桥接到 RobotExecutor，且不可绕过 SafetyGate。
对应 架构.md 第 3/5 节：落账后的单步 action 先过安全闸，再经由执行器下发。

2026-08-29 评审后修订（P0-1）：急停必须到达执行器。
原来 /api/estop 只置 gate.estop，等于"不再接新单"，但正在跑的那一段动作
（DdsEntity 单段最长 15s）并不会停 —— 真机上就是"按了急停狗还往前冲"。
RobotExecutor.estop() 协议里有，却从没人调用过。现在由 RobotBackend.estop()
把闸门和执行器一起置位，调用方只需要打这一个口子。
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from argos.safety import SafetyGate


class ActionBackend:
    """复用接缝。游戏侧 = GameBackend(世界字典 apply_action)，机器人侧 = RobotBackend。"""
    def observe(self) -> Dict:
        raise NotImplementedError

    def apply(self, action: str, params: Dict) -> Tuple[bool, str]:
        raise NotImplementedError

    def estop(self, on: bool = True) -> None:
        raise NotImplementedError


class RobotBackend(ActionBackend):
    def __init__(self, executor, gate: Optional[SafetyGate] = None) -> None:
        self.executor = executor
        self.gate = gate or SafetyGate()

    def observe(self) -> Dict:
        return self.executor.pose()

    def apply(self, action: str, params: Dict) -> Tuple[bool, str]:
        state = self.executor.pose()
        ok, reason = self.gate.check(action, params, state)
        if not ok:
            return False, reason
        try:
            if action == "move_to":
                ok_flag = self.executor.move_to(
                    params["x"], params["y"], params.get("yaw", 0.0))
            elif action == "navigate":
                ok_flag = self.executor.navigate(params["waypoints"])
            elif action == "grab":
                ok_flag = self.executor.grab(params["target"])
            elif action == "release":
                ok_flag = self.executor.release()
            else:
                return False, f"未知动作：{action}"
        except (KeyError, TypeError) as exc:
            return False, f"参数错误：{exc}"
        return bool(ok_flag), ("ok" if ok_flag else "执行失败")

    def estop(self, on: bool = True) -> None:
        """急停/解除：置闸门 + 通知执行器（两处都做，缺一不可）。

        置位时调 executor.estop()，让正在跑的长动作能从内部退出；
        解除时调 executor.clear_estop()（没有就跳过，真机解除按 SKILL.md
        的规矩应走物理复位）。执行器回调抛异常不影响闸门本身生效。
        """
        self.gate.set_estop(bool(on))
        fn = getattr(self.executor, "estop" if on else "clear_estop", None)
        if callable(fn):
            try:
                fn()
            except Exception as exc:                      # 闸门已生效，不让回调带崩
                print(f"[RobotBackend] 执行器急停回调失败（闸门已置位）：{exc}")
