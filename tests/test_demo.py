"""Demo / Trace 测试（Phase 8）。

钉两件事：
  1. 故事必须一直是"撞一次 → 再撞一次 → 第三次规划期就换路"（不能悄悄退化成 demo 台词）；
  2. trace 必须**如实**：没有的字段是 null，不许编造 observation / reflection。
"""
import json

from argos.demo import ARROW, run_demo, render_markdown


def test_demo_story_is_learn_then_change_route():
    trace = run_demo(seed=42, episodes=3)
    routes = [e["initial_route"] for e in trace["episodes"]]
    assert routes == ["north", "north", "south"]        # 学到了，真的换路
    fails = [e["outcome"]["failures"] for e in trace["episodes"]]
    assert fails == [1, 1, 0]                           # 第三次零失败到达
    assert all(e["outcome"]["ok"] for e in trace["episodes"])


def test_lesson_appears_only_after_two_occurrences():
    trace = run_demo(seed=42, episodes=3)
    assert trace["episodes"][0]["reflection"] == []     # 一次还不够
    assert len(trace["episodes"][1]["reflection"]) == 1  # 第二次形成教训
    lesson = trace["episodes"][1]["reflection"][0]
    assert lesson["avoid"] == "north"
    assert lesson["prefer"] == "south"
    assert lesson["evidence"]                            # 有证据，不是编的
    assert lesson["scope"] == "route:north"


def test_trace_json_is_serialisable_and_complete():
    trace = run_demo(seed=42, episodes=2)
    raw = json.dumps(trace, ensure_ascii=False)
    assert "去充电站" in raw
    back = json.loads(raw)
    assert back["meta"]["chain"] == ARROW
    for ep in back["episodes"]:
        for s in ep["steps"]:
            assert set(s) >= {"step", "action", "safety", "failure", "sim_time"}


def test_trace_does_not_fabricate_missing_fields():
    """诚实钉：世界观测没有逐步留存 → 必须是 None，不许编一段观察文本。"""
    trace = run_demo(seed=42, episodes=1)
    for s in trace["episodes"][0]["steps"]:
        assert s["observation"] is None
        assert s["memory"] is None


def test_trace_records_the_blocking_failure():
    trace = run_demo(seed=42, episodes=1)
    failures = [s["failure"] for s in trace["episodes"][0]["steps"] if s["failure"]]
    assert failures and "obstacle_blocked" in failures[0]


def test_markdown_renders_chain_and_lesson():
    trace = run_demo(seed=42, episodes=3)
    md = render_markdown(trace)
    assert ARROW in md
    assert "north_block" in md
    assert "Episode 2" in md
    assert "avoid" in md or "避开" in md
