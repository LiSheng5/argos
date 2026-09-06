"""反思闭环的回归钉（2026-09-06）：让反思产物被决策路径消费，不再只写不读。

两条通路：
  话术层  try_command 的 LLM 措辞附带 recall 记忆（狗"记得"往事）
  行为层  instruction 类记忆命中白名单动作词 → 对应自主日常权重放大

铁律不变：记忆只影响"说"和"选日常"，编译/落账/安全闸永不读记忆。
"""
from argos.brain import (RobotBrain, _INSTRUCTION_ACTION_WORDS, _INSTRUCTION_BOOST)
from argos.llm import LlmError
from argos.sim.stub import SimEntity


class _FakeLlm:
    def __init__(self, reply="汪！", disabled=False, fail=False):
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


# ── 话术层：recall 记忆注入 LLM 措辞 ──────────────────

def test_recall_context_empty_when_no_memory():
    b = _brain()
    assert b._recall_context("去门口") == ""


def test_recall_context_returns_related_memory():
    b = _brain()
    b.remember("没做成: 去门口（电量不足）", importance=6)
    ctx = b._recall_context("去门口")
    assert "没做成: 去门口（电量不足）" in ctx


def test_try_command_injects_memory_into_llm_wording():
    """核心闭环钉：recall() 从此有真实生产调用方，反思产物进入回复措辞。"""
    llm = _FakeLlm(reply="汪！我记得。")
    b = _brain(llm=llm)
    b.remember("没做成: 去门口（电量不足）", importance=6)
    b.try_command("去门口")
    assert any("没做成: 去门口" in c for c in llm.calls), (
        "LLM 措辞的 prompt 里应带上相关记忆，实际 calls: " + repr(llm.calls))


def test_try_command_without_llm_rule_wording_unchanged():
    """无 LLM 时规则话术不读记忆、不被记忆污染（确定性兜底不动）。"""
    b = _brain()
    b.remember("没做成: 去门口（电量不足）", importance=6)
    reply = b.try_command("去门口")
    assert reply == "好，我去门口。"          # 纯规则话术，一字不差


# ── 行为层：instruction 记忆 → 自主日常权重 ──────────

def test_instruction_hints_whitelist_only():
    """只认白名单动作词；编造词（如"公园"）不产生任何动作命中。"""
    b = _brain()
    b.memory.append({"mtype": "instruction",
                     "content": "主人要求我每天巡逻，还让我去公园", "importance": 8})
    hints = b._instruction_hints()
    assert hints == {"navigate": 1}
    assert "grab" not in hints                     # "公园"没触发任何动作


def test_instruction_hints_ignores_non_instruction():
    b = _brain()
    b.memory.append({"mtype": "episodic",
                     "content": "主人要求我巡逻", "importance": 8})   # 不是 instruction
    assert b._instruction_hints() == {}


def test_instruction_boosts_routine_weight(monkeypatch):
    """行为层闭环钉：instruction 命中 navigate → 该日常权重 ×_INSTRUCTION_BOOST。"""
    b = _brain()
    b.memory.append({"mtype": "instruction",
                     "content": "主人要求我每天巡逻", "importance": 8})
    captured = {}

    def fake_choices(pop, weights=None, k=1):
        captured["weights"] = list(weights)
        captured["actions"] = [p.get("action") for p in pop]
        return [pop[0]]

    monkeypatch.setattr(b.rng, "choices", fake_choices)
    b._choose_routine()
    actions = captured["actions"]
    weights = captured["weights"]
    assert "navigate" in actions                 # 满电时巡逻在候选里
    i = actions.index("navigate")
    default_nav = 3                              # DEFAULT_ROUTINE 里巡逻原权重
    assert weights[i] == default_nav * _INSTRUCTION_BOOST, (
        f"instruction 命中后 navigate 权重应 ×{_INSTRUCTION_BOOST}，实际 {weights}")


def test_no_instruction_weight_unchanged(monkeypatch):
    """反向对照：没有 instruction 记忆时，权重是原值（不放大）。"""
    b = _brain()
    captured = {}

    def fake_choices(pop, weights=None, k=1):
        captured["weights"] = list(weights)
        captured["actions"] = [p.get("action") for p in pop]
        return [pop[0]]

    monkeypatch.setattr(b.rng, "choices", fake_choices)
    b._choose_routine()
    i = captured["actions"].index("navigate")
    assert captured["weights"][i] == 3           # 原权重，未被放大
