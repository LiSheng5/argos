"""反思层有效性探测脚本（pytest 不收集：文件名非 test_ 前缀）。

现有 126 个测试钉的是"机制是否按代码跑"（阈值触发、翻篇、降级、解析）。
本脚本探测的是另一件事：**反思产物到底有没有用**。四个维度：

  A 触发     —— 该触发时触发，不该触发时不触发
  B 正确性   —— 反思只准归纳给定事实，禁止编造（代码里的铁律，有无校验？）
  C 可检索   —— 反思产物能不能被 recall 捞回来
  D 可消费   —— 反思产物有没有被任何决策路径读取（闭环接没接上）

用法（仓库根，托管 venv）：
  C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe tests/_probe_reflection.py
"""
from __future__ import annotations

import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from argos.brain import (MAX_MEMORY, REFLECT_IMPORTANCE_THRESHOLD,  # noqa: E402
                         REFLECT_MAX_ENTRIES, RobotBrain)
from argos.llm import LlmError  # noqa: E402
from argos.sim.stub import SimEntity  # noqa: E402


class OffLlm:                      # 无 key：纯规则路径
    def enabled(self):
        return False

    def chat(self, *a, **k):
        raise LlmError("off")


class FakeLlm:                     # 有 key：按序返回预设文本
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def enabled(self):
        return True

    def chat(self, system, user, max_tokens=80, temperature=0.7):
        self.calls.append(user)
        if not self.replies:
            raise LlmError("out of replies")
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def brain(llm=None, **kw):
    kw.setdefault("executor", SimEntity())
    kw.setdefault("memory_path", None)
    kw.setdefault("llm", llm or OffLlm())
    return RobotBrain(**kw)


def facts(b, *items, imp=9):
    for c in items:
        b.memory.append({"content": c, "importance": imp})


def refl(b):
    return [e for e in b.memory if e.get("kind") == "reflection"]


def hdr(t):
    print("\n" + "═" * 64 + f"\n  {t}\n" + "═" * 64)


def verdict(ok, yes, no):
    print(f"  → 结论：{'✅ ' + yes if ok else '❌ ' + no}")


# ══════════════════════════════════════════════════════
# A. 触发 —— 阈值与翻篇（对照已有测试，确认基线一致）
# ══════════════════════════════════════════════════════
def probe_a_trigger():
    hdr("A. 触发：阈值 / 翻篇 / 真实指令流")
    b = brain()
    b.try_command("去门口")
    b.tick()
    s = sum(e.get("importance", 5) for e in b.memory)
    print(f"  一轮指令后未反思重要性之和 = {s}（阈值 {REFLECT_IMPORTANCE_THRESHOLD}）"
          f" → 触发={b.maybe_reflect() is not None}")
    b.try_command("拿小球")
    b.tick()
    print(f"  两轮后反思条数 = {len(refl(b))}，内容 = {refl(b)[-1]['content']!r}")
    verdict(len(refl(b)) == 1, "阈值与翻篇按设计工作",
            "触发异常")

    # A2 真实自主循环里多久反思一次
    b2 = brain()
    b2.rng.seed(11)
    ticks = 0
    while len(refl(b2)) == 0 and ticks < 200:
        if ticks % 4 == 0:
            b2.try_command("去门口" if ticks % 8 == 0 else "巡逻一圈")
        b2.tick()
        ticks += 1
    print(f"  纯自主+间歇指令下，第 {ticks} tick 产出第一条反思；"
          f"此时记忆 {len(b2.memory)} 条")
    verdict(ticks < 200, "真实节奏下能触发", "200 tick 内一次都没触发")


# ══════════════════════════════════════════════════════
# B. 正确性 —— 铁律"禁止编造"有没有代码级校验
# ══════════════════════════════════════════════════════
def probe_b_fabrication():
    probe_b_fabrication_guards()


def probe_b_fabrication_guards():
    """2026-09-05 修复后：三层护栏的实际覆盖率（含覆盖不到的部分，如实记）。"""
    hdr("B. 正确性：LLM 编造事实外的细节时，系统挡不挡得住")

    # B1 抽象编造 + **假引用** → 层1 evidence 溯源拦下
    b1 = brain(FakeLlm('[{"mtype":"episodic","content":"主人带我去了公园",'
                       '"importance":8,"evidence":"完成: 去公园"}]'))
    facts(b1, "完成: 去门口", "完成: 拿小球", "完成: 去桌边")
    out1 = b1.maybe_reflect()
    leaked1 = [w for w in ("公园",) if out1 and w in out1]
    print(f"  假引用：evidence='完成: 去公园'（源事实里没有）→ 产出 {out1!r}")
    verdict(not leaked1, "层1 溯源拦下", "层1 未拦住")

    # B2 编造**已知地点**（世界实体表内）→ 层2 拦下
    b2 = brain(FakeLlm('[{"mtype":"episodic","content":"我先回充电桩补了电",'
                       '"importance":8,"evidence":"完成: 去门口"}]'))
    facts(b2, "完成: 去门口", "完成: 拿小球", "完成: 去桌边")
    out2 = b2.maybe_reflect()
    print(f"  编造地点：'我先回充电桩补了电'（源事实没提充电桩）→ 产出 {out2!r}")
    verdict(not (out2 and "充电桩" in out2), "层2 世界实体拦下", "层2 未拦住")

    # B3 抽象归纳（合法）→ 必须放行，护栏不能误杀
    b3 = brain(FakeLlm('[{"mtype":"persona","content":"主人喜欢看我干活",'
                       '"importance":8,"evidence":"完成: 去门口"}]'))
    facts(b3, "完成: 去门口", "完成: 拿小球", "完成: 去桌边")
    out3 = b3.maybe_reflect()
    print(f"  合法归纳：'主人喜欢看我干活' → 产出 {out3!r}")
    verdict(out3 == "主人喜欢看我干活", "抽象归纳正常放行（没误杀）", "护栏误杀了合法归纳")

    # B4 LLM 自报 9 分 → 层3 夹取
    b4 = brain(FakeLlm('[{"mtype":"episodic","content":"今天干了不少活",'
                       '"importance":9,"evidence":"完成: 去门口"}]'))
    facts(b4, "完成: 去门口", "完成: 拿小球", "完成: 去桌边")
    b4.maybe_reflect()
    imp = refl(b4)[0]["importance"] if refl(b4) else None
    print(f"  自报 9 分（源批最高 9，上限 min(8, 9+1)=8）→ 实际入库 importance={imp}")
    verdict(imp == 8, "层3 重要性已夹取", "层3 未夹取")

    # B5 覆盖不到的部分（如实记，不装作拦住）
    b5 = brain(FakeLlm("这不是 JSON，逼 typed 解析失败",
                       "主人今天带我去了公园，还见了邻居家的猫。"))
    facts(b5, "完成: 去门口", "完成: 拿小球", "完成: 去桌边")
    out5 = b5.maybe_reflect()
    leaked5 = [w for w in ("公园", "猫") if out5 and w in out5]
    print(f"  ⚠️ 未覆盖场景：单条路径 + 抽象编造（新词不在世界实体表内，也没给依据）")
    print(f"      → 产出 {out5!r}")
    verdict(not leaked5, "拦下了",
            f"未拦住（泄漏 {leaked5}）—— 纯规则做不了通用编造检测，"
            f"这是已知边界，见报告")

    # B6 反向钉：含"家"字但不是地点"家"的合法反思，不能被误杀
    # （单字地名做子串匹配会踩雷："邻居家/大家/回家"里都含"家"）
    b6 = brain(FakeLlm('[{"mtype":"episodic","content":"主人今天带我回了家",'
                       '"importance":8,"evidence":"完成: 去门口"}]'))
    facts(b6, "完成: 去门口", "完成: 拿小球", "完成: 去桌边")
    out6 = b6.maybe_reflect()
    print(f"  含'家'字的合法反思：'主人今天带我回了家' → 产出 {out6!r}")
    verdict(out6 == "主人今天带我回了家",
            "没被单字地名误杀", "被单字地名误杀了（'回家'被当成地点'家'）")


# ══════════════════════════════════════════════════════
# C. 可检索 —— 反思产物能不能被 recall 捞回来
# ══════════════════════════════════════════════════════
def probe_c_retrievable():
    hdr("C. 可检索：反思产物能否被语义召回（唯一的对外通路）")
    b = brain()                                   # 规则摘要：直接拼原文
    facts(b, "完成: 去门口", "完成: 拿小球", "完成: 去桌边")
    b.maybe_reflect()
    hits = b.recall("门口", top_k=3)
    print(f"  规则摘要反思：{refl(b)[0]['content']!r}")
    print(f"  recall('门口') 是否包含反思条目："
          f"{any(e.get('kind') == 'reflection' for e in hits)}")
    verdict(any(e.get("kind") == "reflection" for e in hits),
            "反思可被检索（因为摘要照抄了原文关键词）", "反思不可检索")

    b2 = brain(FakeLlm("这不是 JSON，逼 typed 解析失败",
                       "我最近总在屋里转悠，主人喜欢看我干活。"))   # 抽象结论
    facts(b2, "完成: 去门口", "完成: 拿小球", "完成: 去桌边")
    b2.maybe_reflect()
    hits2 = b2.recall("门口", top_k=3)
    print(f"  抽象反思：{refl(b2)[0]['content']!r}")
    print(f"  recall('门口') 命中内容：{[e['content'] for e in hits2]}")
    verdict(any(e.get("kind") == "reflection" for e in hits2),
            "抽象反思也能召回",
            "抽象反思召不回 —— 关键词不在反思文本里，反思对检索是'死条目'")

    # C3 反思条目会不会霸榜，挤掉具体事实
    b3 = brain(FakeLlm("这不是 JSON，逼 typed 解析失败",
                       "我最近总在屋里转悠，主人喜欢看我干活。"))
    facts(b3, "完成: 去门口", "完成: 拿小球", "完成: 去桌边", imp=5)
    b3.maybe_reflect()
    top = b3.recall("门口", top_k=1)
    print(f"  事实 importance=5 / 反思 importance=8 时，recall('门口') 第一名："
          f"{top[0]['content']!r}（kind={top[0].get('kind')}）")
    verdict(top[0].get("kind") != "reflection",
            "具体事实仍排在前面", "反思条目霸榜，挤掉了具体事实")


# ══════════════════════════════════════════════════════
# D. 可消费 —— 反思有没有被任何决策路径读取（闭环）
# ══════════════════════════════════════════════════════
def probe_d_consumed():
    hdr("D. 可消费：反思产物有没有通到决策（闭环接没接上）")
    root = pathlib.Path(__file__).resolve().parent.parent
    hits = []
    for f in list((root / "argos").rglob("*.py")):
        if "__pycache__" in str(f) or f.name == "llm.py":
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]          # 去行内注释，否则注释里的字眼会被算成调用
            if re.search(r"\brecall\s*\(", code) and "def recall" not in code:
                hits.append(f"{f.relative_to(root)}:{i}: {code.strip()}")
    print("  生产代码（argos/）里 recall() 的调用点：")
    for h in hits or ["    （无）"]:
        print("   ", h)
    print("  反思产物的读取方：/api/memory 全量列出 + /api/state 最近 5 条（给人看）")
    verdict(bool(hits), "反思进了决策回路",
            "生产代码零调用 recall() —— 反思是'只写不读'的日记，"
            "不改变编译/选日常/安全闸任何一步")

    # D2 证据：反思前后，同一句话的行为完全一致
    b = brain()
    b.try_command("去门口")
    r1 = b.try_command("去门口")
    facts(b, "完成: 去门口", "完成: 拿小球", "完成: 去桌边")
    b.maybe_reflect()
    r2 = b.try_command("去门口")
    print(f"  反思前后同一指令的回复：{r1!r} / {r2!r} → 相同={r1 == r2}")
    verdict(r1 != r2, "反思改变了行为", "反思对行为零影响（回复一字不差）")


# ══════════════════════════════════════════════════════
# E. 边界 —— 窗口堵死 / 噪音闸误吞 / 长跑增长
# ══════════════════════════════════════════════════════
def probe_e_edges():
    hdr("E. 边界：候选窗口会不会被低分旧记忆堵死")
    b = brain()
    for i in range(REFLECT_MAX_ENTRIES):           # 8 条碎事，各 2 分
        b.memory.append({"content": f"碎事{i}", "importance": 2})
    s = sum(e["importance"] for e in b.memory[:REFLECT_MAX_ENTRIES])
    b.memory.append({"content": "完成: 救了主人一命", "importance": 9})
    print(f"  最老 {REFLECT_MAX_ENTRIES} 条重要性之和 = {s} < "
          f"{REFLECT_IMPORTANCE_THRESHOLD}；其后压着一条 importance=9 的大事")
    got = [b.maybe_reflect() for _ in range(20)]
    idx = b.memory.index(b.memory[-1])
    print(f"  连调 20 次 maybe_reflect() → 产出 {sum(1 for g in got if g)} 条")
    joined = " ".join(g for g in got if g)
    print(f"  那条大事在卡上位次 = {idx}（旧行为按卡上顺序只取前 "
          f"{REFLECT_MAX_ENTRIES} 条 → 它永远排在外面）")
    print(f"  现在是否进了反思：{'救了主人一命' in joined}；"
          f"reflected={b.memory[-1].get('reflected')}")
    verdict(any(got),
            "窗口能老化，大事最终会进反思",
            f"窗口堵死：{REFLECT_MAX_ENTRIES} 条低分旧记忆永久占位，"
            f"后面的大事永远进不了候选（且不翻篇 → 永不前进）")

    hdr("E2. 噪音闸会不会吞掉高重要性记忆")
    b2 = brain(FakeLlm("本不该被调用"))
    b2.memory.append({"content": "完成: 去门口", "importance": 9})
    b2.memory.append({"content": "完成: 去门口", "importance": 9})   # 唯一内容=1
    out = b2.maybe_reflect()
    print(f"  2 条 9 分（和 18 ≥ 阈值）但唯一内容 1 种 → 产出={out!r}，"
          f"LLM 调用次数={len(b2.calls) if hasattr(b2, 'calls') else len(b2.llm.calls)}")
    print(f"  两条记忆已被标记 reflected="
          f"{[e.get('reflected') for e in b2.memory]} → 永久失去反思机会")
    verdict(out is not None, "高重要性记忆被保住",
            "唯一内容 <3 时静默翻篇：高重要性记忆被吞，且再也不会被反思")

    hdr("E3. 长跑：反思会不会无限堆积 / 撑爆记忆卡")
    b3 = brain()
    b3.rng.seed(3)
    for t in range(400):
        if t % 3 == 0:
            b3.try_command(["去门口", "拿小球", "巡逻一圈", "去桌边"][t % 4])
        b3.tick()
    total = len(b3.memory)
    rs = refl(b3)
    active = [e for e in b3.memory if not e.get("archived")]
    uniq = len({e["content"] for e in rs})
    print(f"  400 tick 后：记忆卡共 {total} 条，活跃 {len(active)} 条"
          f"（上限 {MAX_MEMORY}），反思 {len(rs)} 条，去重后 {uniq} 条")
    verdict(len(active) <= MAX_MEMORY and uniq > 1,
            "记忆规模有界，反思内容不重复",
            "记忆无限增长或反思内容自我重复")


def probe_f_real_llm():
    """配了 ARGOS_API_KEY 才跑：看**真模型**在护栏下的真实表现。

    前面 B 节全用假 LLM 注入 —— 那只能证明"护栏的逻辑对"，证明不了
    "真模型会触发它"。真模型会不会按格式给 evidence？给了能不能对上源事实？
    编造率多少？这些只有真跑才知道。没 key 就跳过（不花钱、不联网）。
    """
    hdr("F. 真 LLM 下的护栏表现（需 ARGOS_API_KEY）")
    if not os.environ.get("ARGOS_API_KEY", "").strip():
        print("  ⏭  未配置 ARGOS_API_KEY → 跳过（本脚本不联网、不花钱）")
        print("     配好 key 后重跑本脚本即可看到真模型数据：")
        print("       set ARGOS_API_KEY=sk-xxx   # 或放仓库根 api_key.txt（已 gitignore）")
        print("     要关注的四个数：typed 解析成功率 / evidence 提供率 /")
        print("                     evidence 命中率 / 最终入库条数")
        return

    from argos.llm import LlmClient           # 真客户端（默认 deepseek-chat）
    rounds = 5
    stat = {"typed_ok": 0, "with_ev": 0, "ev_hit": 0, "written": 0, "blocked": 0}
    print(f"  真模型：{os.environ.get('ARGOS_MODEL', 'deepseek-chat')}"
          f" @ {os.environ.get('ARGOS_BASE_URL', 'api.deepseek.com')}，跑 {rounds} 轮")
    src = ("完成: 去门口", "完成: 拿小球", "完成: 去桌边", "没做成: 回充电桩（电量不足）")
    for i in range(rounds):
        b = brain(llm=LlmClient(timeout=180))   # 慢模型/推理型要给足读超时
        for c in src:
            b.memory.append({"content": c, "importance": 6})
        facts_txt = "\n".join(f"- {c}" for c in src)
        typed = b._reflect_typed(facts_txt)
        if not typed:
            print(f"  轮{i + 1}: typed 解析失败（模型没按 JSON 出）→ 落回单条路径")
            continue
        stat["typed_ok"] += 1
        for t in typed:
            ev = t.get("evidence")
            stat["with_ev"] += 1 if ev else 0
            stat["ev_hit"] += 1 if (ev and ev in facts_txt) else 0
            verdict = "入" if b._grounded(t, facts_txt) else "拦"
            stat["written" if verdict == "入" else "blocked"] += 1
            print(f"  轮{i + 1}: [{verdict}] {t['content']!r}"
                  f"  evidence={ev!r}{'' if not ev else (' ✅命中' if ev in facts_txt else ' ❌对不上')}")
    total = stat["written"] + stat["blocked"]
    print("\n  汇总：")
    print(f"    typed 解析成功率 {stat['typed_ok']}/{rounds}")
    print(f"    evidence 提供率  {stat['with_ev']}/{total or 1}（给了依据的条数 / 总条数）")
    print(f"    evidence 命中率  {stat['ev_hit']}/{stat['with_ev'] or 1}"
          f"（能在源事实里逐字找到的比例）")
    print(f"    最终入库 {stat['written']} 条 / 被拦 {stat['blocked']} 条")
    print("  ⚠️  上面每条 content 请**人工过一眼** —— 有没有编造只有人能最终判定：")
    print("     护栏拦的是「引用对不上」和「实体凭空冒出」，不等于「内容正确」。")


def main():
    print(f"ArgOS 反思层有效性探测 · 阈值={REFLECT_IMPORTANCE_THRESHOLD} "
          f"窗口={REFLECT_MAX_ENTRIES} 记忆上限={MAX_MEMORY}")
    for f in (probe_a_trigger, probe_b_fabrication, probe_c_retrievable,
              probe_d_consumed, probe_e_edges, probe_f_real_llm):
        f()
    print("\n" + "═" * 64 + "\n  探测结束（本脚本只读状态、不落盘、不联网）\n" + "═" * 64)


if __name__ == "__main__":
    main()
