"""FailureInjector —— 主动制造失败（Phase 4，本轮最关键的研究工具之一）。

**没有真机，反而更该研究失败**：真机上你只能等它偶然出错，仿真里你可以**指定它出错**。

支持的九类（对齐指令第六节）：
    obstacle_blocked / action_timeout / path_invalid / localization_error /
    battery_low / sensor_missing / simulator_delay / network_delay / executor_failure

设计要点：
  * **确定性优先**：注入是显式 `arm()` 出来的，不是随机抽风；只有显式给了 `probability`
    才动用 rng（且 rng 由外部注入 + seed，保证同 seed 复现）。
  * 只能注入"世界真的会发生的失败"，**不能注入 `safety_rejected` / `invalid_params`**
    —— 那是闸的事，混进来会让反思学到错误的因果。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Optional

from argos.agent.interfaces import Action, ActionKind, FailReason, WorldState

#: 可被主动注入的失败类型（注意：不含 SAFETY_REJECTED / INVALID_PARAMS）
INJECTABLE = frozenset({
    FailReason.OBSTACLE_BLOCKED,
    FailReason.ACTION_TIMEOUT,
    FailReason.PATH_INVALID,
    FailReason.LOCALIZATION_ERROR,
    FailReason.BATTERY_LOW,
    FailReason.SENSOR_MISSING,
    FailReason.SIMULATOR_DELAY,
    FailReason.NETWORK_DELAY,
    FailReason.EXECUTOR_FAILURE,
})


@dataclass
class _Armed:
    reason: FailReason
    once: bool = False
    at_step: Optional[int] = None      # None = 下一步就生效
    on: Optional[ActionKind] = None    # None = 任何动作都生效
    probability: float = 1.0
    fired: int = 0


@dataclass
class FailureInjector:
    """调用时机：`backend.apply()` 里，**在闸门之后、执行器之前**。"""
    rng: random.Random = field(default_factory=random.Random)
    armed: List[_Armed] = field(default_factory=list)
    step: int = 0

    def arm(self, reason: FailReason, *, once: bool = False,
            at_step: Optional[int] = None, on: Optional[ActionKind] = None,
            probability: float = 1.0) -> "FailureInjector":
        """登记一次（或持续）失败注入。返回 self 便于链式调用。"""
        if isinstance(reason, str):
            reason = FailReason(reason)
        if reason not in INJECTABLE:
            raise ValueError(f"{reason} 不可注入（闸门类的失败不能被伪造）：可注入的是 {sorted(r.value for r in INJECTABLE)}")
        self.armed.append(_Armed(reason=reason, once=once, at_step=at_step,
                                 on=on, probability=probability))
        return self

    def clear(self) -> None:
        self.armed.clear()

    def maybe_inject(self, action: Action, world: WorldState) -> Optional[FailReason]:
        """返回要注入的失败原因；None = 这次不注入。"""
        self.step += 1
        for item in list(self.armed):
            if item.at_step is not None and item.at_step != self.step:
                continue
            if item.on is not None and action.kind != item.on:
                continue
            if item.probability < 1.0 and self.rng.random() >= item.probability:
                continue
            item.fired += 1
            if item.once or item.at_step is not None:
                self.armed.remove(item)
            return item.reason
        return None
