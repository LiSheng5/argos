"""LatencyProfile 测试（Phase 5）。

指令第十三节：模拟 50ms / 100ms / 300ms / 1s，甚至随机丢包，
然后验证 Watchdog / SafetyGate / Executor 是否还能正确工作。**别只测 happy path。**
"""
import random

import pytest

from argos.agent.interfaces import Action, ActionKind, FailReason
from argos.backends.simulator_backend import SimulatorBackend
from argos.sim.latency import PROFILES, LatencyProfile, get_profile


def _stop():
    return Action(ActionKind.STOP, {})


def test_required_profiles_exist():
    """指令点名的四档延迟都要在。"""
    for name in ("normal", "moderate", "slow", "very_slow"):
        assert name in PROFILES
    assert PROFILES["normal"].base_ms == 50.0
    assert PROFILES["moderate"].base_ms == 100.0
    assert PROFILES["slow"].base_ms == 300.0
    assert PROFILES["very_slow"].base_ms == 1000.0


def test_unknown_profile_raises():
    """不认识就明确报错，不静默退回 normal。"""
    with pytest.raises(KeyError):
        get_profile("光纤直连")


def test_sample_is_deterministic_without_jitter():
    p = LatencyProfile("fixed", 120.0)
    rng = random.Random(1)
    assert p.sample_ms(rng) == p.sample_ms(rng) == 120.0


def test_jitter_is_seed_reproducible():
    """注意：同一个 rng 连续采样才有意义 —— 每次新建 Random(42) 只会得到同一个数。"""
    p = get_profile("unstable")
    r1, r2 = random.Random(42), random.Random(42)
    a = [p.sample_ms(r1) for _ in range(5)]
    b = [p.sample_ms(r2) for _ in range(5)]
    assert a == b
    assert len(set(a)) > 1             # 抖动确实在抖


def test_packet_loss_is_seed_reproducible_and_happens():
    p = get_profile("packet_loss")
    r1, r2 = random.Random(7), random.Random(7)
    a = [p.drops(r1) for _ in range(50)]
    b = [p.drops(r2) for _ in range(50)]
    assert a == b
    assert any(a)                      # 30% 丢包率下 50 次一次不丢几乎不可能


def test_latency_advances_logical_clock():
    b = SimulatorBackend(seed=1, latency=get_profile("slow"))
    t0 = b.state.sim_time
    b.apply(_stop())
    assert b.state.sim_time - t0 >= 0.3      # 300ms 至少推进 0.3s


def test_packet_loss_produces_learnable_network_failure():
    """丢包 → NETWORK_DELAY，且**可被反思学习**（它是世界的真实状态）。"""
    b = SimulatorBackend(seed=3, latency=LatencyProfile("lossy", 100.0, loss=1.0))
    res = b.apply(_stop())
    assert res.ok is False
    assert res.reason is FailReason.NETWORK_DELAY
    assert res.learnable is True


def test_same_seed_same_trace_under_unstable_latency():
    """不稳定网络下，同 seed 仍要跑出完全一样的结果 —— benchmark 的前提。"""
    def run():
        b = SimulatorBackend(seed=11, latency=get_profile("packet_loss"))
        out = []
        for i in range(6):
            r = b.apply(Action(ActionKind.MOVE, {"x": 0.5 * (i + 1), "y": 0.0}))
            out.append((r.ok, r.reason.value, round(b.state.sim_time, 9)))
        return out
    assert run() == run()
