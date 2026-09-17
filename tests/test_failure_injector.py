"""FailureInjector 测试（Phase 4）—— 九类失败，每类都要能主动造出来。

没有真机反而更该测这个：真机上你只能等它偶然出错，仿真里你必须能**指定**它出错。
"""
import random

import pytest

from argos.agent.interfaces import Action, ActionKind, FailReason
from argos.backends.simulator_backend import SimulatorBackend
from argos.sim.failure_injector import INJECTABLE, FailureInjector


@pytest.mark.parametrize("reason", sorted(INJECTABLE, key=lambda r: r.value))
def test_every_reason_can_be_injected(reason):
    """指令第六节列的九类失败，一个都不能少。"""
    b = SimulatorBackend(seed=1)
    b.injector.arm(reason, once=True)
    res = b.apply(Action(ActionKind.MOVE, {"x": 1.0, "y": 0.0}))
    assert res.ok is False
    assert res.reason is reason
    assert res.learnable is True          # 这些都能被反思学习


def test_all_nine_reasons_are_covered():
    assert len(INJECTABLE) == 9


def test_once_fires_only_once():
    b = SimulatorBackend(seed=1)
    b.injector.arm(FailReason.ACTION_TIMEOUT, once=True)
    move = Action(ActionKind.MOVE, {"x": 1.0, "y": 0.0})
    assert b.apply(move).reason is FailReason.ACTION_TIMEOUT
    assert b.apply(Action(ActionKind.MOVE, {"x": 2.0, "y": 0.0})).ok is True


def test_at_step_targets_a_specific_step():
    b = SimulatorBackend(seed=1)
    b.injector.arm(FailReason.NETWORK_DELAY, at_step=2)
    assert b.apply(Action(ActionKind.MOVE, {"x": 1.0, "y": 0.0})).ok is True
    assert b.apply(Action(ActionKind.MOVE, {"x": 2.0, "y": 0.0})).reason is FailReason.NETWORK_DELAY


def test_on_restricts_to_one_action_kind():
    b = SimulatorBackend(seed=1)
    b.injector.arm(FailReason.SENSOR_MISSING, on=ActionKind.INSPECT)
    assert b.apply(Action(ActionKind.MOVE, {"x": 1.0, "y": 0.0})).ok is True
    assert b.apply(Action(ActionKind.INSPECT, {})).reason is FailReason.SENSOR_MISSING


def test_safety_reasons_cannot_be_forged():
    """闸的失败不能被伪造 —— 否则反思会学到错误的因果。"""
    inj = FailureInjector(rng=random.Random(0))
    for bad in (FailReason.SAFETY_REJECTED, FailReason.INVALID_PARAMS, FailReason.OK):
        with pytest.raises(ValueError):
            inj.arm(bad)


def test_probability_is_seed_deterministic():
    """给概率时也要能复现（同 seed 同结果）—— benchmark 的前提。"""
    def run(seed, n=20):
        inj = FailureInjector(rng=random.Random(seed))
        inj.arm(FailReason.SIMULATOR_DELAY, probability=0.5)
        return [inj.maybe_inject(Action(ActionKind.STOP, {}), None) is not None for _ in range(n)]
    assert run(42) == run(42)
    assert run(42) != run(43)
