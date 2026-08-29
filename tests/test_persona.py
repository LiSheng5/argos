"""persona 加载单测：默认兜底 / 坏文件兜底 / 字段覆盖 / system 铁律。"""
import json

from argos.persona import DEFAULT_PERSONA, load_persona, system_prompt


def test_default_persona_when_missing(tmp_path):
    p = load_persona(str(tmp_path / "nope.json"))
    assert p == DEFAULT_PERSONA
    assert p["name"] == "阿戈斯"


def test_bad_json_falls_back(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_persona(str(bad)) == DEFAULT_PERSONA


def test_partial_overrides_merge(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"name": "二狗", "style": "汪汪叫"}), encoding="utf-8")
    out = load_persona(str(p))
    assert out["name"] == "二狗" and out["style"] == "汪汪叫"
    assert out["personality"] == DEFAULT_PERSONA["personality"]  # 未覆盖字段兜底


def test_system_prompt_has_rules_and_name():
    s = system_prompt({"name": "阿戈斯", "personality": "忠诚", "style": "简短",
                       "reflect_style": ""})
    assert "阿戈斯" in s and "忠诚" in s
    assert "禁止编造没发生的事" in s
    assert "任务描述不许改动" in s
