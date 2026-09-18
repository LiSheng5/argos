"""统一入口测试（指令 §21）。

钉三件事：
  1. 一条命令能跑完整个闭环（Goal → … → Memory → Replan）；
  2. **同 seed 可复现**；
  3. `--backend go2` 这类**未实现的 backend 必须如实报错**，
     绝不允许"用假真机代码冒充完成"（指令 §18 / §28 的红线）。
"""
import json
import types

import pytest

from argos import run as runmod
from argos.run import BACKENDS, _route_topology, build_backend, main, run


# ---------- backend 注册表 ----------

def test_simulator_is_registered_and_go2_is_not():
    assert "simulator" in BACKENDS
    assert "go2" not in BACKENDS


def test_unknown_backend_reports_honestly():
    with pytest.raises(KeyError) as e:
        build_backend("go2")
    msg = e.value.args[0]
    assert "go2" in msg
    assert "尚未实现" in msg
    assert "冒充" in msg


def test_main_returns_nonzero_for_unimplemented_backend(capsys):
    code = main(["--backend", "go2"])
    assert code == 2
    err = capsys.readouterr().err
    assert "尚未实现" in err


def test_list_backends(capsys):
    assert main(["--list-backends"]) == 0
    out = capsys.readouterr().out
    assert "simulator" in out
    assert "go2" in out          # 明确说明它没实现


def test_route_topology_is_honest_about_its_limit():
    """Planner 仍绑 MiniWorld —— 换 backend 时若拿不到路线拓扑，要如实报错而不是瞎猜。"""
    fake = types.SimpleNamespace()          # 没有 .world 属性
    with pytest.raises(NotImplementedError):
        _route_topology(fake)


# ---------- 完整闭环 ----------

def test_run_completes_the_learning_loop():
    eps, lessons = run(goal="去充电站", seed=42, episodes=3, verbose=False)
    assert [e["route"] for e in eps] == ["north", "north", "south"]
    assert [e["failures"] for e in eps] == [1, 1, 0]
    assert all(e["ok"] for e in eps)
    assert len(lessons) == 1
    assert lessons[0].avoid == "north" and lessons[0].prefer == "south"
    assert eps[1]["new_lessons"] and not eps[0]["new_lessons"]


def test_run_is_deterministic():
    a, _ = run(seed=7, episodes=3, verbose=False)
    b, _ = run(seed=7, episodes=3, verbose=False)
    assert [(e["steps"], e["failures"], e["sim_time"]) for e in a] == \
           [(e["steps"], e["failures"], e["sim_time"]) for e in b]


def test_run_uses_protocol_methods_not_backend_internals():
    """sim_time 走 observe()（协议），不读 backend 私有属性 —— 换身体时这里才不会断。"""
    eps, _ = run(seed=42, episodes=1, verbose=False)
    assert eps[0]["sim_time"] > 0


def test_run_writes_trace(tmp_path):
    p = tmp_path / "sub" / "t.json"
    run(seed=42, episodes=2, trace_path=str(p), verbose=False)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["meta"]["backend"] == "simulator"
    assert data["meta"]["seed"] == 42
    assert len(data["episodes"]) == 2
    assert all("steps_detail" in e for e in data["episodes"])


def test_main_success_returns_zero(tmp_path, capsys):
    code = main(["--backend", "simulator", "--episodes", "2",
                 "--trace", str(tmp_path / "t.json")])
    assert code == 0
    out = capsys.readouterr().out
    assert "完成：2/2" in out
    assert "避开 north" in out


def test_main_accepts_revalidate_flag(tmp_path, capsys):
    assert main(["--episodes", "1", "--revalidate-every", "2", "--quiet"]) == 0
