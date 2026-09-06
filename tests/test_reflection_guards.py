"""反思层三道护栏的回归钉（评审 2026-09-05，见 文档/反思层有效性探测_20260905.md）。

钉的是三件原来没有的事：
  层1 evidence 溯源   —— typed 反思必须引用源事实原文，对不上 → 丢弃
  层2 世界实体校验    —— 反思提到的地点/对象必须源事实里也有（抽象归纳不误杀）
  层3 重要性夹取      —— 反思重要性不得超过源批最高分 +1（编造内容拿不到高分）
  E1 候选窗口按重要性 —— 大事不会被一堆碎事埋在窗口外（原来会永久哑火）
  E2 重复模式不吞     —— 同一件事反复发生是模式，不再当噪音静默吞掉

每条钉子都做过反向验证：把修复退回旧行为，确认它会炸（见文件末尾注释）。
"""
from argos.brain import (REFLECT_IMPORTANCE_THRESHOLD, REFLECT_MAX_ENTRIES,
                         RobotBrain)
from argos.llm import LlmError
from argos.sim.stub import SimEntity


class _FakeLlm:
    """固定返回同一段文本的假 LLM（同 test_brain，测试永不上网）。"""

    def __init__(self, reply="", disabled=False, fail=False):
        self.reply = reply
        self.disabled = disabled
        self.fail = fail
        self.calls = []

    def enabled(self):
        return not self.disabled

    def chat(self, system, user, max_tokens=80, temperature=0.7):
        self.calls.append(user)
        if self.fail:
            raise LlmError("boom")
        return self.reply


def _brain(llm=None, **kw):
    kw.setdefault("executor", SimEntity())
    kw.setdefault("memory_path", None)
    kw.setdefault("llm", llm or _FakeLlm(disabled=True))
    return RobotBrain(**kw)


def _facts(b, *items, imp=9):
    for c in items:
        b.memory.append({"content": c, "importance": imp})


def _refl(b):
    return [e for e in b.memory if e.get("kind") == "reflection"]


# ── 层1：evidence 溯源 ────────────────────────────────

def test_typed_evidence_must_come_from_facts():
    """给了 evidence 就必须在源事实里逐字找到 —— 假的/改写的引用 → 整条丢弃。

    丢弃后 typed 被判不可信，fail-closed 落到规则摘要（100% 有根），
    **不会再拿同一批事实去问一次单条路径**。
    """
    llm = _FakeLlm('[{"mtype": "episodic", "content": "今天干了不少活",'
                   ' "importance": 7, "evidence": "完成: 去了公园"}]')
    b = _brain(llm=llm)
    _facts(b, "完成: 去门口", "完成: 拿小球", "完成: 去桌边")
    b.maybe_reflect()
    got = _refl(b)
    assert len(got) == 1
    assert got[0]["content"].startswith("我最近做了这些事：")   # 落回有根的规则摘要
    assert "公园" not in got[0]["content"]


def test_typed_evidence_ok_writes_entry():
    """evidence 能对上源事实 → 正常入库，并把依据留在卡上（可人工核对）。"""
    llm = _FakeLlm('[{"mtype": "persona", "content": "主人爱让我巡逻",'
                   ' "importance": 9, "evidence": "完成: 巡逻一圈"}]')
    b = _brain(llm=llm)
    _facts(b, "完成: 巡逻一圈", "完成: 去门口", "完成: 去桌边")
    out = b.maybe_reflect()
    assert out == "主人爱让我巡逻"
    got = _refl(b)
    assert len(got) == 1 and got[0]["mtype"] == "persona"
    assert got[0]["evidence"] == "完成: 巡逻一圈"


# ── 层2：世界实体校验 ─────────────────────────────────

def test_reflect_rejects_unknown_world_entity():
    """反思里冒出源事实没有的世界实体（地点/对象）→ 拦下。

    注意：抽象归纳（"主人喜欢看我干活"）不含任何世界实体，空集 ⊆ 任意集，
    恒真放行 —— 所以这层不会误杀归纳，只拦硬编造。
    """
    llm = _FakeLlm('[{"mtype": "episodic", "content": "我先回充电桩补了电再去门口",'
                   ' "importance": 8, "evidence": "完成: 去门口"}]')
    b = _brain(llm=llm)
    _facts(b, "完成: 去门口", "完成: 拿小球", "完成: 去桌边")   # 全程没提充电桩
    b.maybe_reflect()
    got = _refl(b)
    assert len(got) == 1
    assert "充电桩" not in got[0]["content"]       # 编造的地点被拦
    assert got[0]["content"].startswith("我最近做了这些事：")


def test_reflect_allows_abstract_insight():
    """反向钉：抽象结论（不含世界实体）必须照常放行，护栏不能误杀归纳。"""
    llm = _FakeLlm("我最近总在屋里转悠，主人喜欢看我干活。")
    b = _brain(llm=llm)
    _facts(b, "完成: 去门口", "完成: 拿小球", "完成: 去桌边")
    out = b.maybe_reflect()
    assert out == "我最近总在屋里转悠，主人喜欢看我干活。"


# ── 层3：重要性夹取 ───────────────────────────────────

def test_reflect_importance_clamped_to_source():
    """LLM 自报 9 分不算数：反思重要性上限 = min(8, 源批最高分 + 1)。

    检索里 importance 权重是 2 —— 不夹取的话，一条编造内容拿到 9 分
    就能长期霸占记忆顶部，挤掉真实事实。
    """
    llm = _FakeLlm('[{"mtype": "episodic", "content": "今天干了不少活",'
                   ' "importance": 9, "evidence": "完成: 去门口"}]')
    b = _brain(llm=llm)
    _facts(b, "完成: 去门口", "完成: 拿小球", "完成: 去桌边", imp=6)   # 和 18 ≥ 阈值
    b.maybe_reflect()
    got = _refl(b)
    assert len(got) == 1
    assert got[0]["importance"] == 7               # min(8, 6+1)，不是 LLM 报的 9


# ── E1：候选窗口按重要性 ──────────────────────────────

def test_reflect_window_prioritizes_high_importance():
    """大事不能被一堆碎事埋在窗口外。

    旧行为按卡上顺序（最老优先）取前 8 条：这 8 条碎事重要性之和 16 < 阈值 18，
    maybe_reflect 既不触发也不翻篇 → 第 9 条 importance=9 的大事永远进不了窗口，
    反思层就此哑火且无法自愈。
    """
    b = _brain()
    for i in range(REFLECT_MAX_ENTRIES):           # 8 条低分碎事堵在前面
        b.memory.append({"content": f"碎事{i}", "importance": 2})
    b.memory.append({"content": "完成: 救了主人一命", "importance": 9})
    assert sum(e["importance"] for e in b.memory[:REFLECT_MAX_ENTRIES]) \
        < REFLECT_IMPORTANCE_THRESHOLD             # 前提成立：卡上最老 8 条不够阈值
    out = b.maybe_reflect()
    assert out and "救了主人一命" in out            # 大事进了窗口并被归纳


# ── E2：重复模式不吞 ──────────────────────────────────

def test_reflect_repeated_pattern_not_swallowed():
    """同一件事反复发生是模式，不是噪音 —— 不再静默吞掉。

    旧行为：唯一内容 < 3 一律标记 reflected 并静默翻篇，于是"反复撞同一堵墙"
    这种最该被总结的模式被当噪音吞掉，且**永久失去反思机会**。
    """
    llm = _FakeLlm("废话洞察")
    b = _brain(llm=llm)
    for _ in range(2):
        b.memory.append({"content": "没做成: 去门口（电量不足）", "importance": 9})
    out = b.maybe_reflect()
    assert out and "反复发生" in out and "2 次" in out
    assert llm.calls == []                          # 模式是规则复述，不调 LLM
    got = _refl(b)
    assert len(got) == 1 and got[0]["mtype"] == "episodic"

# ── 反向验证记录（2026-09-05，改一行跑一次，确认钉子会炸）──
#  层1 退回（_evidence_ok 恒 True）        → test_typed_evidence_must_come_from_facts 炸 ✅
#  层2 退回（_grounded_entities 恒 True）  → test_reflect_rejects_unknown_world_entity 炸 ✅
#  层3 退回（cap 改成 9）                  → test_reflect_importance_clamped_to_source 炸 ✅
#  E1 退回（候选改回 cands[:N]）           → test_reflect_window_prioritizes_high_importance 炸 ✅
#  E2 退回（删掉 _repeated_pattern 分支）  → test_reflect_repeated_pattern_not_swallowed 炸 ✅
