"""LatencyProfile —— 在没有真机的时候，把"网络/时序"也变成可实验的变量（Phase 5）。

指令第十三节：模拟 50ms / 100ms / 300ms / 1s，甚至随机丢包，
然后验证 **Watchdog / SafetyGate / Executor 是否还能正确工作**。
不要只测 happy path —— 这一层就是为"非 happy path"准备的。

延迟是**加在逻辑时钟上**的（`sim_time`），不是真的 sleep：
既能让 watchdog 判超时，又不破坏 benchmark 的可复现性。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

__all__ = ["LatencyProfile", "PROFILES", "get_profile"]


@dataclass(frozen=True)
class LatencyProfile:
    name: str
    base_ms: float
    jitter_ms: float = 0.0
    loss: float = 0.0        # 丢包率（0~1）

    def sample_ms(self, rng) -> float:
        """本次往返延迟（毫秒）。给了 jitter 才动用 rng。"""
        if self.jitter_ms > 0:
            return self.base_ms + rng.uniform(0.0, self.jitter_ms)
        return self.base_ms

    def drops(self, rng) -> bool:
        """这次是否丢包（丢包 = 动作没送达 / 回包丢了）。"""
        return self.loss > 0 and rng.random() < self.loss


PROFILES: Dict[str, LatencyProfile] = {
    "normal":     LatencyProfile("normal", 50.0),
    "moderate":   LatencyProfile("moderate", 100.0),
    "slow":       LatencyProfile("slow", 300.0),
    "very_slow":  LatencyProfile("very_slow", 1000.0),
    "unstable":   LatencyProfile("unstable", 150.0, jitter_ms=250.0),
    "packet_loss": LatencyProfile("packet_loss", 100.0, jitter_ms=60.0, loss=0.3),
}


def get_profile(name: str) -> LatencyProfile:
    """按名字取剖面；不认识就明确报错（不静默退回 normal）。"""
    if name not in PROFILES:
        raise KeyError(f"未知延迟剖面：{name}；可选 {sorted(PROFILES)}")
    return PROFILES[name]
