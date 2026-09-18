"""输入层测试（Wave 3 / 指令 §20）。

两个后端：`text`（直通）/ `speech`（口语规则抽取）。
**最重要的一条：听不懂就返回 None，绝不猜一个目标去执行。**
"""
import pytest

from argos.agent.planner import Planner
from argos.input import (
    INPUTS,
    SimulatedSpeechBackend,
    TextInputBackend,
    build_input,
)
from argos.run import main, resolve_goal
from argos.world.mini_world import build_default_world


@pytest.fixture
def resolver():
    return Planner(build_default_world()).resolve_target


# ---------- 文本直通 ----------

def test_text_is_passthrough():
    bk = TextInputBackend()
    assert bk.goal_from("去充电站") == "去充电站"
    assert bk.goal_from("  去充电站  ") == "去充电站"


def test_text_does_not_pretend_to_understand():
    """文本层不做"理解"：认不出的句子照样原样返回（判断交给 Planner）。"""
    assert TextInputBackend().goal_from("去火星") == "去火星"


def test_text_empty_is_none():
    assert TextInputBackend().goal_from("   ") is None
    assert TextInputBackend().goal_from("") is None


# ---------- 口语抽取 ----------

@pytest.mark.parametrize("utterance,expected", [
    ("去充电站", "去充电站"),
    ("麻烦帮我去一下充电站吧", "去充电站"),
    ("能不能前往充电站呢", "前往充电站"),
])
def test_speech_strips_polite_filler(resolver, utterance, expected):
    assert SimulatedSpeechBackend(resolver=resolver).goal_from(utterance) == expected


def test_speech_returns_none_when_it_cannot_understand(resolver):
    """★ 核心纪律：听不懂就说听不懂，**不许猜**。"""
    bk = SimulatedSpeechBackend(resolver=resolver)
    assert bk.goal_from("去火星") is None
    assert bk.goal_from("今天天气不错") is None
    assert bk.goal_from("谢谢啊") is None
    assert bk.goal_from("   ") is None


def test_speech_records_what_it_stripped(resolver):
    bk = SimulatedSpeechBackend(resolver=resolver)
    bk.goal_from("麻烦帮我去一下充电站吧")
    assert bk.stripped == ["去充电站"]           # 去掉客套后的中间结果可查（便于调试规则）


def test_speech_result_is_always_resolvable(resolver):
    """口语层返回的 goal，Planner 必须真的能解析 —— 否则就是"抽了个假目标"。"""
    bk = SimulatedSpeechBackend(resolver=resolver)
    for s in ("麻烦帮我去一下充电站吧", "能不能前往充电站呢", "去充电站"):
        g = bk.goal_from(s)
        assert g is not None and resolver(g) == "charger"


# ---------- 装配 ----------

def test_registry_lists_both_backends():
    assert set(INPUTS) == {"text", "speech"}


def test_build_input_rejects_unknown_name(resolver):
    with pytest.raises(KeyError):
        build_input("脑机接口", resolver)


def test_resolve_goal_helper():
    assert resolve_goal("麻烦去一下充电站吧", "speech") == "去充电站"
    assert resolve_goal("去火星", "speech") is None


# ---------- CLI ----------

def test_cli_say_with_speech_works(capsys):
    assert main(["--input", "speech", "--say", "麻烦帮我去一下充电站吧",
                 "--episodes", "1", "--quiet"]) == 0


def test_cli_say_unheard_is_honest(capsys):
    """听不懂 → 退出码 2 + 明确说没听懂，**不去执行任何猜测**。"""
    code = main(["--input", "speech", "--say", "去火星", "--episodes", "1", "--quiet"])
    assert code == 2
    err = capsys.readouterr().err
    assert "没听懂" in err and "猜" in err


def test_cli_shows_input_and_utterance_when_say_used(capsys):
    main(["--input", "speech", "--say", "去充电站", "--episodes", "1"])
    out = capsys.readouterr().out
    assert "input=speech" in out and "say=" in out
