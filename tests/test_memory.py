"""记忆检索与遗忘合并（NPCMemory 移植）单测：同义词召回 / BM25 / 合并 / 修剪。"""
import time

from argos.memory import (MTYPES, consolidate, parse_typed_reflection,
                          retrieve)


_mem_seq = 0


def _mem(content, importance=5, created_at=None, category=None, **kw):
    global _mem_seq
    _mem_seq += 1
    e = {"id": f"mem_{_mem_seq}_{int(time.time())}", "content": content,
         "importance": importance, "created_at": created_at or time.time()}
    if category:
        e["category"] = category
    e.update(kw)
    return e


# ── 检索 ────────────────────────────────────────────

def test_retrieve_synonym_recall():
    entries = [_mem("完成: 回充电桩补电", importance=5),
               _mem("完成: 去桌边看看", importance=5)]
    hits = retrieve(entries, "我要回充", top_k=1)
    assert hits and "充电桩" in hits[0]["content"]


def test_retrieve_keyword_match():
    entries = [_mem("完成: 巡逻一圈", importance=5),
               _mem("完成: 去门口", importance=5)]
    hits = retrieve(entries, "巡逻", top_k=1)
    assert hits and "巡逻" in hits[0]["content"]


def test_retrieve_archived_excluded():
    entries = [_mem("完成: 去门口", importance=5),
               _mem("完成: 去门口", importance=5, archived=True)]
    hits = retrieve(entries, "门口", top_k=5)
    assert len(hits) == 1 and not hits[0].get("archived")


def test_retrieve_importance_boosts():
    entries = [_mem("完成: 去门口", importance=3),
               _mem("完成: 去门口", importance=9)]
    hits = retrieve(entries, "门口", top_k=1)
    assert hits and hits[0]["importance"] == 9


def test_retrieve_old_card_without_ids():
    """旧卡条目无 id/created_at → 兜底不炸（可编辑文档兼容）。"""
    entries = [{"content": "完成: 去门口", "importance": 5},
               {"content": "完成: 巡逻一圈", "importance": 5}]
    hits = retrieve(entries, "门口", top_k=1)
    assert hits and hits[0]["content"] == "完成: 去门口"


# ── 遗忘合并（阶段③）─────────────────────────────────

def test_consolidate_merges_same_topic():
    entries = [_mem("完成: 巡逻一圈", importance=5),
               _mem("没做成: 巡逻一圈（撞墙）", importance=4),
               _mem("完成: 巡逻一圈", importance=5)]
    removed = consolidate(entries)
    assert removed == 3
    assert len(entries) == 1
    assert entries[0]["category"] == "consolidated"
    assert "巡逻" in entries[0]["content"] and "3 次" in entries[0]["content"]


def test_consolidate_skips_archived():
    entries = [_mem("完成: 巡逻一圈", importance=5),
               _mem("完成: 巡逻一圈", importance=5),
               _mem("完成: 巡逻一圈", importance=5),
               _mem("完成: 巡逻一圈", importance=5, archived=True)]
    removed = consolidate(entries)
    assert removed == 3                    # 3 条活跃合并，archived 不参与
    assert any(e.get("archived") for e in entries)


def test_consolidate_prunes_weak_old_only():
    old = time.time() - 72 * 3600 * 4      # 4 个半衰期前
    entries = [_mem("完成: 去桌边", importance=5, created_at=old),
               _mem("完成: 去门口", importance=9, created_at=old),
               _mem("反思结论", importance=6, category="reflection", created_at=old),
               _mem("（已合并）……", importance=8, category="consolidated",
                    created_at=old)]
    removed = consolidate(entries)
    assert removed == 1                    # 只有弱旧流水账被修剪
    kept = [e["content"] for e in entries]
    assert "完成: 去门口" in kept and "反思结论" in kept


def test_consolidate_reflection_not_merged():
    entries = [_mem("完成: 巡逻一圈", importance=5),
               _mem("完成: 巡逻一圈", importance=5),
               _mem("完成: 巡逻一圈", importance=5),
               _mem("巡逻很耗电", importance=8, category="reflection")]
    consolidate(entries)
    assert any(e.get("category") == "reflection" for e in entries)


# ── 结构化反思解析 ──────────────────────────────────

def test_parse_typed_reflection_valid():
    raw = '[{"mtype": "episodic", "content": "今天巡逻了两圈", "importance": 7}]'
    out = parse_typed_reflection(raw)
    assert out and out[0]["mtype"] == "episodic" and out[0]["importance"] == 7


def test_parse_typed_reflection_strips_fence():
    raw = '```json\n[{"mtype": "persona", "content": "主人爱让我巡逻", "importance": 6}]\n```'
    out = parse_typed_reflection(raw)
    assert out and out[0]["mtype"] == "persona"


def test_parse_typed_reflection_invalid():
    assert parse_typed_reflection("") is None
    assert parse_typed_reflection("我觉得今天不错") is None
    assert parse_typed_reflection("{}") is None


def test_parse_typed_reflection_unknown_mtype_defaults():
    raw = '[{"mtype": "weird", "content": "x", "importance": 99}]'
    out = parse_typed_reflection(raw)
    assert out and out[0]["mtype"] == "episodic" and out[0]["importance"] == 9


# ── 温层向量锚点（RRF 融合，假 anchor 注入，不依赖真 chromadb）──

class _FakeAnchor:
    """假向量锚点：search 返回预设 {text: score}。"""

    def __init__(self, results=None, available=True):
        self.results = results or {}
        self.available = available
        self.deleted = []

    def search(self, query, top_k=8):
        return dict(self.results)

    def add(self, doc_id, text, metadata=None):
        pass

    def delete(self, doc_id):
        self.deleted.append(doc_id)


def test_retrieve_anchor_rrf_boosts_semantic_hit():
    """关键词路无命中分数相近时，语义路的排名把目标条目顶上来。"""
    entries = [_mem("完成: 去门口", importance=5),
               _mem("完成: 去桌边", importance=5),
               _mem("完成: 巡逻一圈", importance=5)]
    # 语义路认为"桌边"最像（0.9），关键词路三者几乎同分 → RRF 后桌边第一
    anchor = _FakeAnchor({"完成: 去桌边": 0.9})
    hits = retrieve(entries, "桌子", top_k=1, anchor=anchor)
    assert hits and hits[0]["content"] == "完成: 去桌边"


def test_retrieve_anchor_none_zero_change():
    entries = [_mem("完成: 去门口", importance=5),
               _mem("完成: 巡逻一圈", importance=9)]
    a = retrieve(entries, "巡逻", top_k=2, anchor=None)
    b = retrieve(entries, "巡逻", top_k=2,
                 anchor=_FakeAnchor(available=False))
    assert [e["content"] for e in a] == [e["content"] for e in b]


def test_consolidate_anchor_syncs_deletes():
    entries = [_mem("完成: 巡逻一圈", importance=5),
               _mem("没做成: 巡逻一圈", importance=4),
               _mem("完成: 巡逻一圈", importance=5)]
    anchor = _FakeAnchor()
    consolidate(entries, anchor=anchor)
    assert len(anchor.deleted) == 3       # 3 条被合并 → 全部出索引


def test_consolidate_anchor_none_ok():
    entries = [_mem("完成: 巡逻一圈", importance=5),
               _mem("完成: 巡逻一圈", importance=5),
               _mem("完成: 巡逻一圈", importance=5)]
    assert consolidate(entries, anchor=None) == 3
