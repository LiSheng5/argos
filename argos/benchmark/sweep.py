"""参数扫描（Wave 3 / C1）—— 把"拍的值"变成"测过的值"。

背景：`min_hits=2` / `confidence≥0.6` / `window=3` / `min_failures=2` / `revalidate_every=2`
全都是当初手拍的。本模块用**单参数扫描**回答三个问题：

  1. 这个参数**到底重不重要**（改它，指标动不动）？
  2. 动的话，**哪个值更好**？
  3. 有没有**看着更好其实是过拟合**的假象（比如"学得最快"和"过度泛化"是两回事）？

纪律：一次只动一个参数（单变量），其余保持基线 —— 否则分不清是谁的效果。
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from argos.benchmark.configs import AgentConfig, config_by_name
from argos.benchmark.runner import DEFAULT_SEEDS, ScenarioResult, run_matrix
from argos.benchmark.scenarios import Scenario, build_scenarios

__all__ = ["SWEEPABLE", "SweepRow", "sweep_param", "run_sweep", "render_markdown"]

#: 可扫参数 → 建议的候选值（都从"当前默认值"往两边铺）
SWEEPABLE: Dict[str, Tuple[float, ...]] = {
    "min_hits": (1, 2, 3, 4),
    "min_confidence": (0.4, 0.5, 0.6, 0.8),
    "window": (1, 2, 3, 5),
    "min_failures": (1, 2, 3),
    "soft_threshold": (0.34, 0.5, 0.67),
    "revalidate_every": (0, 1, 2, 3),
}

#: 注释（报告里会带上，免得读者只看数字不懂含义）
NOTES: Dict[str, str] = {
    "min_hits": "Procedural 门槛：要几次独立失败才升级成硬策略",
    "min_confidence": "读/写同一个门槛：confidence = hits/(hits+1) 要过线才生效",
    "window": "Semantic 滑窗长度：只看最近几次尝试",
    "min_failures": "软降权的最少失败次数",
    "soft_threshold": "软降权的失败率阈值",
    "revalidate_every": "每几个 episode 主动复核一次被避开的路线（0=不复核）",
}


@dataclass
class SweepRow:
    param: str
    value: object
    success_rate: float
    avg_failures: float
    avg_steps: float
    avg_retries: float
    avg_time_s: float


def _variant(base: AgentConfig, **over) -> AgentConfig:
    return dataclasses.replace(base, **over)


def _aggregate(results: Sequence[ScenarioResult]) -> Dict[str, float]:
    n = max(1, len(results))
    return {
        "success_rate": sum(r.success_rate for r in results) / n,
        "avg_failures": sum(r.avg_failures for r in results) / n,
        "avg_steps": sum(r.avg_steps for r in results) / n,
        "avg_retries": sum(r.avg_replans for r in results) / n,
        "avg_time_s": sum(r.avg_time for r in results) / n,
    }


def sweep_param(param: str,
                values: Iterable,
                base: Optional[AgentConfig] = None,
                scenarios: Optional[Sequence[Scenario]] = None,
                seeds: Sequence[int] = (42,)) -> List[SweepRow]:
    """单参数扫描：只改这一个，其余保持基线。"""
    if param not in SWEEPABLE and not hasattr(AgentConfig, param):
        raise KeyError(f"不可扫的参数：{param}")
    base = base or config_by_name("memory_reflection")
    scenarios = scenarios or build_scenarios()

    rows: List[SweepRow] = []
    for v in values:
        cfg = _variant(base, **{param: v})
        res = run_matrix(scenarios=scenarios, configs=[cfg], seeds=seeds)
        rows.append(SweepRow(param=param, value=v, **_aggregate(res)))
    return rows


def run_sweep(params: Optional[Iterable[str]] = None,
              base: Optional[AgentConfig] = None,
              scenarios: Optional[Sequence[Scenario]] = None,
              seeds: Sequence[int] = DEFAULT_SEEDS) -> Dict[str, List[SweepRow]]:
    params = list(params or SWEEPABLE.keys())
    return {p: sweep_param(p, SWEEPABLE[p], base=base, scenarios=scenarios, seeds=seeds)
            for p in params}


def _defaults(base: AgentConfig) -> Dict[str, object]:
    return {p: getattr(base, p) for p in SWEEPABLE if hasattr(base, p)}


def render_markdown(rows: Dict[str, List[SweepRow]], base: Optional[AgentConfig] = None,
                    seeds: Sequence[int] = DEFAULT_SEEDS,
                    n_scenarios: int = 0) -> str:
    base = base or config_by_name("memory_reflection")
    defaults = _defaults(base)

    out: List[str] = []
    out.append("# 参数扫描（阈值/窗口/复核周期）")
    out.append("")
    out.append("> 由 `python -m argos.benchmark sweep` 生成 —— 纯仿真。")
    out.append(f"> 基线臂：`{base.name}`；seed：`{list(seeds)}`；场景数：{n_scenarios}；"
               "每次只动一个参数（单变量）。")
    out.append("")
    out.append("## 1. 逐参数敏感度")
    out.append("")

    for param, rs in rows.items():
        dv = defaults.get(param)
        out.append(f"### `{param}` —— {NOTES.get(param, '')}")
        out.append("")
        out.append("| 取值 | 任务成功率 | 平均失败数 | 平均动作数 | 平均重试 | 平均耗时(s) |")
        out.append("|---|---|---|---|---|---|")
        for r in rs:
            mark = " ← 当前默认" if dv is not None and r.value == dv else ""
            out.append(f"| {r.value}{mark} | {r.success_rate * 100:.1f}% | "
                       f"{r.avg_failures:.2f} | {r.avg_steps:.2f} | "
                       f"{r.avg_retries:.2f} | {r.avg_time_s:.2f} |")
        out.append("")
        out.append(f"> 极差（该参数能带来多大变化）：成功率 "
                   f"{(max(r.success_rate for r in rs) - min(r.success_rate for r in rs)) * 100:.1f} 个百分点，"
                   f"失败数 {max(r.avg_failures for r in rs) - min(r.avg_failures for r in rs):.2f}。")
        out.append("")

    out.append(_conclusions(rows, defaults))
    out.append(LIMITS)
    return "\n".join(out)


def _conclusions(rows: Dict[str, List[SweepRow]], defaults: Dict[str, object]) -> str:
    """自动推导：哪些参数敏感、哪些不敏感（**不敏感也是结论**）。"""
    out = ["## 2. 结论（由数据自动推导）", ""]
    insensitive, sensitive = [], []

    for param, rs in rows.items():
        spread = max(r.avg_failures for r in rs) - min(r.avg_failures for r in rs)
        succ_spread = (max(r.success_rate for r in rs) - min(r.success_rate for r in rs)) * 100
        if spread < 0.05 and succ_spread < 1.0:
            insensitive.append((param, spread, succ_spread))
        else:
            sensitive.append((param, spread, succ_spread, rs))

    if insensitive:
        names = "、".join(f"`{p}`" for p, _, _ in insensitive)
        out.append(f"- ✅ **不敏感的参数**：{names} —— 在本次场景集里，怎么取几乎不影响结果。"
                   "含义：这些值**不必纠结**，选一个可解释的即可（但换场景要重扫）。")
    for param, spread, succ_spread, rs in sorted(sensitive, key=lambda x: -x[1]):
        best_succ = max(rs, key=lambda r: r.success_rate)
        best_fail = min(rs, key=lambda r: r.avg_failures)
        dv = defaults.get(param)
        tag = ""
        if dv is not None:
            cur = next((r for r in rs if r.value == dv), None)
            if cur is not None and (cur.avg_failures - min(r.avg_failures for r in rs)) > 0.05:
                tag = (f" —— ⚠️ **当前默认值 {dv} 不是最佳**：最优（按失败数）是 "
                       f"{best_fail.value}（{best_fail.avg_failures:.2f}），"
                       f"默认是 {cur.avg_failures:.2f}")
        out.append(f"- ⚠️ **敏感参数 `{param}`**：失败数极差 {spread:.2f}、"
                   f"成功率极差 {succ_spread:.1f} 个百分点；"
                   f"成功率最高是 {best_succ.value}（{best_succ.success_rate * 100:.1f}%）{tag}")

    out.append("")
    out.append("> ⚠️ **别把这张表当「最优参数」**：它是**单变量扫描**，参数之间有交互；"
               "而且只在本场景集上测过 —— 换个世界结论可能不同。它的用途是"
               "**判断该不该纠结某个参数**，而不是给出可以直接抄的配置。")
    out.append("")
    return "\n".join(out)


LIMITS = """
## 3. 已知限制

1. **单变量**：一次只动一个参数，**没有做交互扫描**（如 min_hits × window）。真实影响可能是耦合的。
2. **场景集有限**（见 `文档/BENCHMARK.md` 的限制）：结论只在这个世界里成立。
3. **seed 数量有限**：默认 3 个 seed，统计涨落可能盖过小差异 —— 差异小于 0.05 的"变化"别当真。
4. **指标有取舍**：成功率最高的配置**未必**是失败数最少的；本表两个都列出来，不做单一排名。
"""
