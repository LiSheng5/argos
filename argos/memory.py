"""记忆检索与遗忘合并：NPCMemory（1_NPCSidekick/npc/memory.py）的机器人版移植。

移植对照（1_NPCSidekick/npc/memory.py 只读参考，纯函数化，操作记忆卡列表）：
  NPCMemory.retrieve   → retrieve(entries, query, top_k)
     加权公式（AI Town, MIT, a16z-infra）：recency×0.5 + relevance×3
     + importance×2 + 一跳关联加分；相关度取 max(原词命中, BM25)。
  NPCMemory.consolidate → consolidate(entries, min_group, prune_strength)
     阶段③ 遗忘：同主题合并 + 弱旧修剪（反思/合并/归档/高重要度免疫）。

不移植：温层向量锚点（chromadb 可选开关）、mtype 三分类常量见 brain.py。
条目兼容：旧记忆卡无 id/created_at 字段时按"索引兜底 id / 最旧时间"处理，
不改写卡上旧数据（可编辑文档红线）。
"""
from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from typing import Dict, List, Optional

try:   # 可选依赖: pip install jieba 后自动启用（缺失不影响启动）
    import jieba  # type: ignore
except ImportError:   # pragma: no cover
    jieba = None  # type: ignore

# AI Town 记忆加权参数 (MIT, a16z-infra) — 见模块 docstring
_GW = (0.5, 3, 2)          # (recency, relevance, importance) 权重
_DECAY = 0.99              # 每小时衰减
_HOUR_SECONDS = 3600

# 归档语义（ArgOS 本地）：布尔 archived=True 即管家降级层 ——
# 退出检索/合并、免修剪，条目永不物理删除（证据链红线）。
def _archived(e: Dict) -> bool:
    return bool(e.get("archived"))


def _is_reflection(e: Dict) -> bool:
    return e.get("kind") == "reflection" or e.get("category") == "reflection"


def _is_consolidated(e: Dict) -> bool:
    return e.get("category") == "consolidated"

# 同义词族（机器人世界版）：只收狗世界的稳定名词，避免过度匹配
_ENTITY_SYNONYMS: Dict[str, frozenset] = {
    "充电桩": frozenset({"充电桩", "充电", "回充", "补电"}),
    "家": frozenset({"家", "原点", "老窝"}),
    "桌边": frozenset({"桌边", "桌子"}),
    "门口": frozenset({"门口", "门边"}),
    "巡逻": frozenset({"巡逻", "巡检", "转一圈"}),
    "急停": frozenset({"急停", "紧急停止"}),
}
# 单字别名白名单（同 NPCSidekick 2026-08-28 修复）：语义单义才放行
_SINGLE_CHAR_TERMS = frozenset({"桩"})
# 一跳关联加分: 与 query 实体共现的实体所链接的记忆 +0.8/实体
_ASSOCIATION_WEIGHT = 0.8
# 阶段③ 遗忘: 记忆强度半衰期（小时）— 强度 = importance × 0.5^(小时/半衰期)
_HALF_LIFE_HOURS = 72.0

_PUNCT = ("，", "。", "？", "！", "、", "；", "：", ",", ".", "?", "!", ";", ":")

# ── TDAM 三分类（结构化反思用，与 category 生命周期维度正交）──
MTYPES = ("persona", "episodic", "instruction")
MTYPE_DEFAULT = "episodic"
TYPED_REFLECT_MAX = 3


def parse_typed_reflection(raw: str) -> Optional[List[Dict]]:
    """解析三分类反思输出 → [{"mtype","content","importance"}]；不合法 → None。

    容错链: 剥 Markdown 围栏 → 截取首尾 [] 之间 → json.loads → 逐条校验
    （mtype 白名单外归 episodic；importance 夹取 0-9；空 content 丢弃）。
    任何一步失败整体返回 None —— 调用方无痕落回旧单条反思路径。
    """
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    out: List[Dict] = []
    for item in data[:TYPED_REFLECT_MAX]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        mtype = str(item.get("mtype", "")).strip().lower()
        if mtype not in MTYPES:
            mtype = MTYPE_DEFAULT
        try:
            imp = int(item.get("importance", 5))
        except (TypeError, ValueError):
            imp = 5
        out.append({"mtype": mtype, "content": content,
                    "importance": max(0, min(9, imp))})
    return out or None


def _tokenize(text: str) -> List[str]:
    """中文感知切词: 有 jieba 用 jieba，没装退回空格切。纯标点 token 已剔除。"""
    cleaned = text
    for p in _PUNCT:
        cleaned = cleaned.replace(p, " ")
    if jieba is not None:
        return [w.strip() for w in jieba.lcut(cleaned) if w.strip()]
    return [w for w in cleaned.split() if w]


def _canonical_terms(text: str) -> set:
    """抽取文本里命中的规范词（同义词族归一到规范词）。"""
    found = set()
    for canon, aliases in _ENTITY_SYNONYMS.items():
        if any((len(a) >= 2 or a in _SINGLE_CHAR_TERMS) and a in text
               for a in aliases):
            found.add(canon)
    return found


def _recency_score(created_at: float, now: float) -> float:
    hours = max(0.0, (now - created_at) / _HOUR_SECONDS)
    return _DECAY ** hours


def _relevance_score(content: str, query: str,
                     query_tokens: Optional[List[str]] = None,
                     q_canon: Optional[set] = None,
                     content_canon: Optional[set] = None) -> float:
    """相关度: 原词命中 + 同义词召回。0-1。"""
    words = query_tokens if query_tokens is not None else _tokenize(query)
    raw = sum(1 for w in words if w in content) / len(words) if words else 0.0
    if q_canon is None:
        q_canon = _canonical_terms(query)
    syn = 0.0
    if q_canon:
        if content_canon is None:
            content_canon = _canonical_terms(content)
        syn = len(q_canon & content_canon) / len(q_canon)
    return min(1.0, raw * 0.6 + syn * 0.8)


def _idf_relevance(entry_tokens, query_tokens: List[str], df: Dict[str, int],
                   total: int, avgdl: Optional[float] = None) -> float:
    """真 BM25（与 TDAM 公式对齐）：idf × tf 归一。空 query → 0。"""
    if not query_tokens or total <= 0:
        return 0.0
    tf = Counter(entry_tokens)
    dl = float(sum(tf.values())) or 1.0
    if avgdl is None or avgdl <= 0:
        avgdl = dl
    k1, b = 1.2, 0.75
    score = 0.0
    for t in set(query_tokens):
        f = tf.get(t, 0)
        if f <= 0:
            continue
        dft = max(0, df.get(t, 0))
        idf = math.log(1.0 + (total - dft + 0.5) / (dft + 0.5))
        denom = f + k1 * (1.0 - b + b * dl / avgdl)
        score += idf * (f * (k1 + 1.0)) / denom
    return score


def _entry_id(entry: Dict, idx: int) -> str:
    """条目 id 兜底（旧卡无 id 字段 → 索引位 id，只用于本轮排序）。"""
    return str(entry.get("id", f"mem_old_{idx}"))


def _entry_time(entry: Dict, now: float) -> float:
    """created_at 兜底：旧卡无时间戳 → 0（最旧），recency 分自然最低。"""
    try:
        return float(entry.get("created_at", 0.0))
    except (TypeError, ValueError):
        return 0.0


def retrieve(entries: List[Dict], query: str = "", top_k: int = 5) -> List[Dict]:
    """加权检索 + 一跳关联（阶段② 轻量海马体）。

    score = recency×0.5 + relevance×3 + importance×2 + 关联加分；
    relevance = max(原词/同义词命中, BM25)；archived 不参与检索。
    """
    now = time.time()
    active = [e for e in entries if not _archived(e)]
    q_canon = _canonical_terms(query)
    assoc: set = set()
    canon_by_id: Dict[str, set] = {}
    if q_canon:
        for i, e in enumerate(active):
            e_canon = _canonical_terms(e["content"])
            canon_by_id[_entry_id(e, i)] = e_canon
            if q_canon & e_canon:
                assoc |= e_canon
        assoc -= q_canon
    q_tokens = _tokenize(query)
    df: Dict[str, int] = {}
    tok_by_id: Dict[str, List[str]] = {}
    total = len(active)
    avgdl = 1.0
    if active:
        for i, e in enumerate(active):
            toks = _tokenize(e.get("content", ""))
            tok_by_id[_entry_id(e, i)] = toks
            for t in set(toks):
                df[t] = df.get(t, 0) + 1
        avgdl = sum(len(v) for v in tok_by_id.values()) / total
    scored = []
    any_hit = False
    for i, e in enumerate(active):
        eid = _entry_id(e, i)
        rel = _relevance_score(e["content"], query, q_tokens, q_canon,
                               canon_by_id.get(eid))
        rel = max(rel, _idf_relevance(tok_by_id.get(eid, []),
                                      q_tokens, df, total, avgdl))
        if rel > 0:
            any_hit = True
        score = (
            _recency_score(_entry_time(e, now), now) * _GW[0]
            + rel * _GW[1]
            + e.get("importance", 5) * _GW[2]
        )
        if assoc:
            score += len(canon_by_id.get(eid, set()) & assoc) * _ASSOCIATION_WEIGHT
        scored.append((score, e))
    if not any_hit:      # 毫不相关 → 空（诚实：没有相关记忆，不塞无关条目）
        return []
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored[:top_k]]


def consolidate(entries: List[Dict], min_group: int = 3,
                prune_strength: float = 1.0) -> int:
    """遗忘合并（阶段③）: 重复主题合并成一条 + 弱旧记忆修剪。

    - 合并: 同主题(规范词交集)的非反思记忆 ≥ min_group 条 → 合并成一条
      consolidated（"模式留存，流水账淡去"），只复述事实不编造。
    - 修剪: 强度 = importance × 0.5^(小时/半衰期)，低于 prune_strength 的
      旧条目移除；反思/合并/归档条目与高重要度(≥8)免疫。
    - archived 永不参与也不被卷走（证据链红线）。
    - 返回被移除（含被合并）的条目数。原地修改列表。
    """
    now = time.time()
    removed = 0
    # ── 1. 同主题合并 ──
    groups: Dict[frozenset, List[int]] = {}
    for i, e in enumerate(entries):
        if _archived(e):
            continue
        key = frozenset(_canonical_terms(e["content"]))
        if key:
            groups.setdefault(key, []).append(i)
    drop = set()
    for key, idxs in groups.items():
        cand = [i for i in idxs if not _is_reflection(entries[i])]
        if len(cand) < min_group:
            continue
        top = max(cand, key=lambda i: entries[i].get("importance", 5))
        topic = "、".join(sorted(key))
        summary = (f"（已合并）关于{topic}的经历共 {len(cand)} 次；"
                   f"最近一次：{entries[top]['content']}")
        entries.append({
            "id": f"mem_c_{len(entries) + 1}_{int(now)}",
            "content": summary,
            "importance": max(8, entries[top].get("importance", 5)),
            "category": "consolidated",
            "created_at": _entry_time(entries[top], now),
        })
        for i in cand:
            drop.add(i)
        removed += len(cand)
    if drop:
        entries[:] = [e for i, e in enumerate(entries) if i not in drop]
    # ── 2. 弱旧修剪 ──
    keep = []
    for e in entries:
        if _is_reflection(e) or _is_consolidated(e) or _archived(e):
            keep.append(e)
            continue
        if e.get("importance", 5) >= 8:
            keep.append(e)
            continue
        hours = max(0.0, (now - _entry_time(e, now)) / _HOUR_SECONDS)
        strength = e.get("importance", 5) * (0.5 ** (hours / _HALF_LIFE_HOURS))
        if strength >= prune_strength:
            keep.append(e)
        else:
            removed += 1
    entries[:] = keep
    return removed
