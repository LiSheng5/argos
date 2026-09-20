"""LessonStore 持久化测试（D-03a）。

钉三件事：
  1. **round trip 不丢审计信息**（status / history / confidence / hits /
     created_episode / updated_episode 一个都不能掉）；
  2. **文件不存在 → 空库**（首次运行是正常情况）；
  3. **坏文件 → 明确报错，绝不静默变空库**（"没学到"和"文件坏了"必须能区分），
     并且 load 对原文件**只读不改**。
"""
import json

import pytest

from argos.agent.interfaces import Lesson
from argos.agent.memory_agent import LessonStore, LessonStoreError


def _lesson(**kw) -> Lesson:
    base = dict(
        id="lesson:route:north:obstacle_blocked",
        trigger="route:north",
        avoid="north",
        prefer="south",
        evidence="被 north_block 挡住",
        confidence=0.67,
        hits=2,
        scope="route:north",
        status="active",
        history=("support@ep1", "support@ep2"),
        created_episode=1,
        updated_episode=2,
    )
    base.update(kw)
    return Lesson(**base)


# ---------- 1. round trip ----------

def test_lesson_store_round_trips_json(tmp_path):
    path = tmp_path / "lessons.json"
    store = LessonStore()
    # 两次独立证据 → created_episode / updated_episode 才会不同（这样才能验出没搞混）
    store.add(_lesson(hits=1, confidence=0.5, history=()), episode=1)
    store.add(_lesson(), episode=2)
    store.save(path)

    loaded = LessonStore.load(path)
    got = loaded.get("lesson:route:north:obstacle_blocked")
    assert got is not None
    assert got == store.get("lesson:route:north:obstacle_blocked")   # 逐字段相等
    assert got.trigger == "route:north"
    assert got.avoid == "north"
    assert got.prefer == "south"
    assert got.confidence == pytest.approx(0.67)
    assert got.hits == 2
    assert got.scope == "route:north"
    assert got.status == "active"
    assert got.history == ("support@ep1", "support@ep2")
    assert got.created_episode == 1        # 首次创建轮次
    assert got.updated_episode == 2        # 最近一次更新轮次


def test_invalidated_lessons_survive_the_round_trip(tmp_path):
    """失效教训**照样落盘** —— 否则"当初怎么来的、又被什么推翻"就丢了。"""
    path = tmp_path / "lessons.json"
    store = LessonStore()
    store.add(_lesson(), episode=1)
    store.weaken("north", episode=2)
    store.weaken("north", episode=3)
    dead = store.get("lesson:route:north:obstacle_blocked")
    assert dead.status == "invalidated"

    store.save(path)
    loaded = LessonStore.load(path)
    back = loaded.get("lesson:route:north:obstacle_blocked")
    assert back.status == "invalidated"
    assert back.hits == 0 and back.confidence == 0.0
    assert "counter_evidence@ep3" in back.history
    assert loaded.active() == []                              # 失效的不参与规划
    assert [l.id for l in loaded.invalidated()] == [back.id]


def test_history_survives_after_reload_then_continues(tmp_path):
    """载回来之后继续学习：hits / history 在旧基础上累加，不是从头开始。"""
    path = tmp_path / "lessons.json"
    store = LessonStore()
    store.add(_lesson(), episode=2)
    store.save(path)

    again = LessonStore.load(path)
    merged = again.add(_lesson(), episode=9)
    assert merged.hits == 3                                   # 2 → 3，没有归零
    assert merged.created_episode == 2                        # 原始创建轮次保留
    assert merged.updated_episode == 9
    assert merged.history == ("support@ep1", "support@ep2", "support@ep9")


def test_save_creates_parent_directory(tmp_path):
    path = tmp_path / "nested" / "deeper" / "lessons.json"
    LessonStore().save(path)
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == []


def test_save_is_atomic_so_no_leftover_tmp(tmp_path):
    """逐 episode 落盘：临时文件必须被替换掉，不留半截文件在磁盘上。"""
    path = tmp_path / "lessons.json"
    store = LessonStore()
    store.add(_lesson(), episode=1)
    store.save(path)
    assert [p.name for p in tmp_path.iterdir()] == ["lessons.json"]


# ---------- 2. 缺文件 → 空库 ----------

def test_missing_lesson_store_starts_empty(tmp_path):
    loaded = LessonStore.load(tmp_path / "missing.json")
    assert loaded.all() == []
    assert loaded.active() == []


# ---------- 3. 坏文件 → 明确报错，不静默清空 ----------

def test_corrupted_json_is_not_silently_an_empty_store(tmp_path):
    path = tmp_path / "lessons.json"
    path.write_text("{这不是合法 JSON", encoding="utf-8")

    with pytest.raises(LessonStoreError):
        LessonStore.load(path)
    # 原文件**没被动过**（既没被清空、也没被删）
    assert path.read_text(encoding="utf-8") == "{这不是合法 JSON"


def test_wrong_top_level_shape_raises(tmp_path):
    path = tmp_path / "lessons.json"
    path.write_text(json.dumps({"lessons": []}, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(LessonStoreError):
        LessonStore.load(path)


def test_entry_missing_required_field_raises(tmp_path):
    path = tmp_path / "lessons.json"
    path.write_text(json.dumps([{"id": "l", "trigger": "route:north"}],
                               ensure_ascii=False), encoding="utf-8")
    with pytest.raises(LessonStoreError):
        LessonStore.load(path)


def test_entry_with_bad_field_type_raises(tmp_path):
    path = tmp_path / "lessons.json"
    path.write_text(json.dumps([{
        "id": "l", "trigger": "route:north", "avoid": "north", "prefer": "south",
        "confidence": "不是数字",
    }], ensure_ascii=False), encoding="utf-8")
    with pytest.raises(LessonStoreError):
        LessonStore.load(path)


def test_non_object_entry_raises(tmp_path):
    path = tmp_path / "lessons.json"
    path.write_text(json.dumps(["不是对象"], ensure_ascii=False), encoding="utf-8")
    with pytest.raises(LessonStoreError):
        LessonStore.load(path)


def test_lesson_store_error_is_a_value_error(tmp_path):
    """CLI 侧按 ValueError 兜底也不漏（LessonStoreError 是它的子类）。"""
    assert issubclass(LessonStoreError, ValueError)
    path = tmp_path / "lessons.json"
    path.write_text("坏", encoding="utf-8")
    with pytest.raises(ValueError):
        LessonStore.load(path)
