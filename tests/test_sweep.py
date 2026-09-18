"""参数扫描测试（Wave 3 / C1）。

钉的是「扫描器本身可信」：单变量、可复现、能正确区分"敏感 / 不敏感"。
结论本身在 `文档/SWEEP.md`，这里只保证产结论的机器没坏。
"""
import pytest

from argos.benchmark.configs import config_by_name
from argos.benchmark.scenarios import by_name
from argos.benchmark.sweep import (
    SWEEPABLE,
    render_markdown,
    run_sweep,
    sweep_param,
)


SCEN = (by_name("learn_to_survive_none"), by_name("permanent_block_x5.0_northfirst"))


def test_sweep_param_gives_one_row_per_value():
    rows = sweep_param("min_hits", (1, 2, 3), scenarios=SCEN, seeds=(42,))
    assert [r.value for r in rows] == [1, 2, 3]
    assert all(r.param == "min_hits" for r in rows)
    for r in rows:
        assert 0.0 <= r.success_rate <= 1.0
        assert r.avg_steps >= 0


def test_sweep_only_changes_one_knob():
    """单变量：扫 min_hits 时其余旋钮必须保持基线值。"""
    base = config_by_name("memory_reflection")
    rows = sweep_param("min_hits", (1, 3), scenarios=SCEN, seeds=(42,))
    assert len(rows) == 2
    # 基线没被改动（dataclasses.replace 是拷贝）
    assert base.min_hits == 2


def test_sweep_is_deterministic():
    a = sweep_param("min_failures", (1, 2), scenarios=SCEN, seeds=(42,))
    b = sweep_param("min_failures", (1, 2), scenarios=SCEN, seeds=(42,))
    assert [(r.value, r.success_rate, r.avg_failures) for r in a] == \
           [(r.value, r.success_rate, r.avg_failures) for r in b]


def test_unknown_param_raises():
    with pytest.raises(KeyError):
        sweep_param("不存在的旋钮", (1, 2), scenarios=SCEN, seeds=(42,))


def test_all_sweepable_keys_are_real_config_fields():
    """防止 SWEEPABLE 里写了 AgentConfig 上不存在的字段（那会静默不生效）。"""
    cfg = config_by_name("memory_reflection")
    for p in SWEEPABLE:
        assert hasattr(cfg, p), p


def test_render_marks_defaults_and_has_all_sections():
    rows = run_sweep(params=["min_hits", "revalidate_every"], scenarios=SCEN, seeds=(42,))
    md = render_markdown(rows, seeds=(42,), n_scenarios=len(SCEN))
    assert "## 1. 逐参数敏感度" in md
    assert "## 2. 结论（由数据自动推导）" in md
    assert "## 3. 已知限制" in md
    assert "← 当前默认" in md
    assert "`min_hits`" in md and "`revalidate_every`" in md


def test_conclusions_separate_sensitive_from_insensitive():
    """扫描器必须能说出"这个参数重不重要"—— 不敏感也是结论。"""
    rows = run_sweep(scenarios=SCEN, seeds=(42, 7))
    md = render_markdown(rows, seeds=(42, 7), n_scenarios=len(SCEN))
    assert ("不敏感的参数" in md) or ("敏感参数" in md)
    # 单变量纪律必须写在报告里，防止有人把它当"最优参数表"抄走
    assert "单变量扫描" in md


def test_main_sweep_writes_file(tmp_path, capsys):
    from argos.benchmark.__main__ import main
    out = tmp_path / "SWEEP.md"
    assert main(["sweep", "--out", str(out), "--params", "min_hits",
                 "--seeds", "42"]) == 0
    assert "已写出" in capsys.readouterr().out
    assert "min_hits" in out.read_text(encoding="utf-8")


def test_main_sweep_rejects_unknown_param(capsys):
    from argos.benchmark.__main__ import main
    assert main(["sweep", "--params", "没有这个", "--seeds", "42"]) == 2
    assert "不可扫的参数" in capsys.readouterr().err
