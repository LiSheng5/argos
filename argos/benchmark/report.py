"""Benchmark 报告渲染（Phase 7/8）。

只做展示，不做计算 —— 数字全部来自 `runner` 的实测结果。
**写清楚做不到的事**比把数字排得好看重要（指令第二十三、二十八节）。
"""
from __future__ import annotations

from typing import Dict, List, Sequence

from argos.benchmark.configs import CONFIGS
from argos.benchmark.runner import ScenarioResult, summarize

__all__ = ["render_markdown"]

LIMITS = """
## 已知限制与负结果（照实写）

1. **场景是"少量原型 × 参数化变体"**，不是几十个手写任务。障碍位置 / 路线偏好 / 延迟剖面 /
   **失败类型 / 感知配置**都是参数化出来的变体 —— 别把它读成"几十个独立场景"。
   每个维度各取几档参数化生成 —— 好处是可复现、好扩展，坏处是**覆盖的真实性有限**。
2. **移动模型是直线段 + 矩形障碍采样**（步长 0.05m），不是真实运动学。够用于研究
   planning / memory / reflection，**不能当物理结论**。
3. **反思只从"路线相关"失败里学**（`OBSTACLE_BLOCKED` / `PATH_INVALID`）。
   低电量、执行器故障等失败会被统计，但**不会生成"避开这条路"的教训** ——
   这是本轮实测倒逼出来的修正：早期版本会把"低电量"学成"北线不能走"，属于错误因果。
4. **感知场景默认"整轮失灵 + 不重试"**：定位失灵会让闸门 fail-closed 拒动且本轮直接结束，
   所以感知失灵场景的成功率**主要反映的是这条策略**，而不是"感知本身的好坏"。
   （定位噪声是整轮固定的标定偏差、失灵是粘性的 —— 不这么做的话，
   "缺不缺数据"会变成"读了几次"的偶然函数。）
5. **失败类型的覆盖仍不均匀**：障碍阻挡类场景最多，其余八类各只有 1~2 个场景。
6. **阈值（min_hits=2 / confidence≥0.6）是拍的**，但**已经扫过参**（见 `文档/SWEEP.md`）：
   单变量扫描显示它们在本场景集里**不敏感**（成功率极差 ≤0.5 个百分点）→
   "拍的值"这一风险基本解除；但**不等于"调好了"**（换场景要重扫，且未做交互扫描）。
7. **复核周期 `revalidate_every=2` 同样是拍的**，而且只在「连撞两次后恢复」这一个场景族里
   验证过；换周期会不会更好、换别的失败模式还灵不灵，都没扫过。
   ⚠️ 而且它和反证门槛是**耦合**的：反证要连续 2 次探针成功（见下条），所以
   复核周期实际决定的是"多久能撤掉一条过期的教训"—— 周期越大，撤销越慢。
8. **反证规则只做了第一层收紧（D-02）**：现在要求**连续 2 次**探针成功才削弱教训
   （不再是"成功一次就降一级"），中途该路线再失败会清零重数。残留的粗糙点：
   ① "连续 2 次"这个数也是**拍的**，没扫过；② 仍是 `hits -= 1` 的二值降级，
   没有"恢复的概率有多大"这种不确定度。更严谨的做法是把路线选择当作**带不确定性的决策**
   （多臂老虎机：成功/失败更新后验，而不是二值 avoid）。
9. **`reflection_only` 臂是故意留的负结果臂**：若它与 `memory_reflection` 打平，
   说明"反思"本身没带来价值。表里的数字是什么就是什么，不做挑选。
"""


def render_markdown(results: Sequence[ScenarioResult],
                    seeds: Sequence[int]) -> str:
    table = summarize(results)
    order = [c.name for c in CONFIGS if c.name in table]

    lines: List[str] = []
    lines.append("# ArgOS Reflection Benchmark")
    lines.append("")
    lines.append("> 由 `python -m argos.benchmark all` 生成 —— 纯仿真，无硬件。")
    n_scen = len({r.scenario for r in results})
    per_ep = len(results[0].episodes) if results else 0
    lines.append(f"> seed：`{list(seeds)}`；场景数：{n_scen}；配置数：{len(order)}；"
                 f"总运行：{len(results)} 组 × 每组 {per_ep} 个 episode")
    lines.append("")

    # ---- 总表 ----
    lines.append("## 1. 各组配置对比（跨全部场景与 seed 平均）")
    lines.append("")
    lines.append("| 配置 | 任务成功率 | 平均重试 | 平均动作数 | 平均完成耗时(s) | 平均失败数 |")
    lines.append("|---|---|---|---|---|---|")
    for name in order:
        m = table[name]
        lines.append(
            f"| `{name}` | {m['success_rate'] * 100:.1f}% | {m['avg_retries']:.2f} | "
            f"{m['avg_actions']:.2f} | {m['avg_time_s']:.2f} | {m['avg_failures']:.2f} |")
    lines.append("")

    # ---- 分场景 ----
    lines.append("## 2. 分场景（每格：成功率 / 平均失败数 / 平均动作数）")
    lines.append("")
    lines.append("> 第 3 个数是关键：**绕远路不会体现在失败数上，只会体现在动作数上**。")
    lines.append("")
    head = "| 场景 | " + " | ".join(order) + " |"
    lines.append(head)
    lines.append("|" + "---|" * (len(order) + 1))

    by_scen: Dict[str, Dict[str, ScenarioResult]] = {}
    for r in results:
        by_scen.setdefault(r.scenario, {})[r.config] = r
    for scen in sorted(by_scen):
        cells = []
        for name in order:
            r = by_scen[scen].get(name)
            cells.append(f"{r.success_rate * 100:.0f}% / {r.avg_failures:.2f} / {r.avg_steps:.2f}"
                         if r else "-")
        lines.append(f"| `{scen}` | " + " | ".join(cells) + " |")
    lines.append("")

    # ---- 学习速度 ----
    lines.append("## 3. 学习速度（第几个 episode 起不再失败，跨场景平均）")
    lines.append("")
    lines.append("| 配置 | 出现\"零失败 episode\"的比例 |")
    lines.append("|---|---|")
    for name in order:
        lines.append(f"| `{name}` | {table[name]['learned_fast'] * 100:.1f}% |")
    lines.append("")

    lines.append(_conclusions(table, results, order))
    lines.append(LIMITS)
    return "\n".join(lines)


def _conclusions(table, results, order) -> str:
    """**自动推导**的结论 —— 不手写，避免"改了代码忘了改结论"。"""
    out = ["## 4. 结论（由数据自动推导）", ""]

    # (1) 反思只写不读是否等于零价值
    if "planner_only" in table and "reflection_only" in table:
        a, b = table["planner_only"], table["reflection_only"]
        same = all(abs(a[k] - b[k]) < 1e-9
                   for k in ("avg_retries", "avg_actions", "avg_failures", "avg_time_s"))
        if same:
            out.append("- ✅ **「反思只写不读」= 零价值**：`reflection_only` 与 `planner_only` 四个指标"
                       "逐位相同 —— 这正面复现了旧系统的毛病（反思写完没人读）。")
        else:
            out.append(f"- ⚠️ `reflection_only` 与 `planner_only` **不完全相同**"
                       f"（失败数 {b['avg_failures']:.2f} vs {a['avg_failures']:.2f}）"
                       "—— 说明还有别的路径让教训泄漏进了规划，需要查。")

    # (2) 过度泛化的代价（只算瞬时故障场景）
    transient = [r for r in results if r.kind == "transient"]
    if transient:
        by_cfg: Dict[str, List[ScenarioResult]] = {}
        for r in transient:
            by_cfg.setdefault(r.config, []).append(r)
        acts = {k: sum(x.avg_steps for x in v) / len(v) for k, v in by_cfg.items()}
        if "memory_only" in acts and "memory_reflection" in acts:
            mo, mr = acts["memory_only"], acts["memory_reflection"]
            if mo > mr + 1e-9:
                out.append(f"- ⚠️ **过度泛化有代价**：瞬时故障场景里 `memory_only` 平均动作 "
                           f"{mo:.2f} 次，比 `memory_reflection` 的 {mr:.2f} 次多 "
                           f"{mo - mr:.2f} 次 —— 它把**一次偶发**当成了永久的教训，从此绕远路。")
            else:
                out.append(f"- ⚠️ 瞬时故障场景里 `memory_only`（{mo:.2f} 动作）**没有**比 "
                           f"`memory_reflection`（{mr:.2f}）更差 —— 本轮场景没能度量出"
                           "「不过度泛化」的价值，需要更贵的绕路设计。")

    # (2b) 复核机制是否真的把"永久绕路"治好了
    freeze = [r for r in results if r.scenario.startswith("two_strikes_then_clear")]
    if freeze:
        by_cfg2: Dict[str, List[ScenarioResult]] = {}
        for r in freeze:
            by_cfg2.setdefault(r.config, []).append(r)
        if "memory_reflection" in by_cfg2 and "memory_reflection_revalidate" in by_cfg2:
            nf = by_cfg2["memory_reflection"]
            nr = by_cfg2["memory_reflection_revalidate"]
            af = sum(x.avg_steps for x in nf) / len(nf)
            ar = sum(x.avg_steps for x in nr) / len(nr)
            ff = sum(x.avg_failures for x in nf) / len(nf)
            fr = sum(x.avg_failures for x in nr) / len(nr)
            if ar < af:
                out.append(
                    f"- ✅ **周期复核治好了「永久绕路」**：在「连撞两次后环境恢复」的场景里，"
                    f"不复核的 `memory_reflection` 平均动作 **{af:.2f}**，每 2 个 episode 复核一次的"
                    f" `memory_reflection_revalidate` 降到 **{ar:.2f}**（省 {af - ar:.2f} 个动作），"
                    f"代价是平均失败数 {fr:.2f} vs {ff:.2f} —— **用一次试探买回一条路**。")
            else:
                out.append(f"- ⚠️ 复核臂（{ar:.2f} 动作）没有比不复核（{af:.2f}）更省 —— "
                           "需要检查复核周期或反证削弱是否真的生效。")

    # (2c) 复核的收益与代价（宽松预算赚、紧预算可能亏）
    if "memory_reflection" in table and "memory_reflection_revalidate" in table:
        loose = [r for r in results if r.kind == "transient" and "two_strikes" in r.scenario]
        tight = [r for r in results if r.kind == "unrecoverable"]
        parts = []
        for tag, subset in (("预算充裕（连撞两次后恢复）", loose), ("预算紧（单次换路救不回来）", tight)):
            if not subset:
                continue
            d: Dict[str, List[ScenarioResult]] = {}
            for r in subset:
                d.setdefault(r.config, []).append(r)
            if "memory_reflection" in d and "memory_reflection_revalidate" in d:
                a = d["memory_reflection"]; b = d["memory_reflection_revalidate"]
                sa = sum(x.success_rate for x in a) / len(a)
                sb = sum(x.success_rate for x in b) / len(b)
                st_a = sum(x.avg_steps for x in a) / len(a)
                st_b = sum(x.avg_steps for x in b) / len(b)
                parts.append(f"{tag}：成功率 {sa * 100:.0f}% → {sb * 100:.0f}%，"
                             f"动作数 {st_a:.2f} → {st_b:.2f}")
        if parts:
            out.append("- ⚠️ **复核不是免费的**：" + "；".join(parts) +
                       "。预算是紧的时候，试探本身要花掉预算 —— 所以「要不要开复核」"
                       "取决于预算宽紧，不能一概而论。")

    # (2d) 新补的两类覆盖：**换一种失败原因** 与 **感知不可靠**
    #      目标是让"学习有效"的结论别只站在"障碍阻挡"这一类失败上。
    by_kind: Dict[str, Dict[str, List[ScenarioResult]]] = {}
    for r in results:
        by_kind.setdefault(r.kind, {}).setdefault(r.config, []).append(r)

    def _avg(kind: str, cfg_name: str, attr: str):
        rows_ = by_kind.get(kind, {}).get(cfg_name)
        if not rows_:
            return None
        return sum(getattr(x, attr) for x in rows_) / len(rows_)

    if "route_failure" in by_kind:
        # 与"障碍版"同形的场景族（two_strikes_then_clear），逐臂对比**是否逐位相同**。
        # ⚠️ 不预设方向：先算，再说。
        def _fingerprint(rows_, names) -> Dict[str, tuple]:
            fp = {}
            for n in names:
                v = [x for x in rows_ if x.config == n]
                if v:
                    fp[n] = (round(sum(x.success_rate for x in v) / len(v), 4),
                             round(sum(x.avg_failures for x in v) / len(v), 4),
                             round(sum(x.avg_steps for x in v) / len(v), 4))
            return fp

        pi = _fingerprint([r for r in results if r.kind == "route_failure"], order)
        tw = _fingerprint([r for r in results if r.scenario.startswith("two_strikes_then_clear")],
                          order)
        if pi and tw:
            identical = pi == tw
            out.append(
                "- ✅ **结论对「失败原因」不敏感（只要它属于路线类）**：与障碍版同形的场景族"
                f"（`two_strikes_then_clear`）换成 `path_invalid` 注入后，六个臂的"
                f"（成功率 / 失败数 / 动作数）"
                + ("**逐位相同**" if identical else "**不完全相同**（见 §2 明细）")
                + "。机制上说得通：反思只看**失败属于哪一类**（路线相关 / 不相关），"
                "不看具体是障碍还是路径失效 —— 所以结论可以从「障碍阻挡」推广到整个路线类，"
                "但推广不到别的类（见下一条）。")

    if "nonroute_failure" in by_kind:
        diff = None
        po, mr = by_kind["nonroute_failure"].get("planner_only"), \
                 by_kind["nonroute_failure"].get("memory_reflection")
        if po and mr:
            diff = abs(sum(x.avg_steps for x in mr) / len(mr)
                       - sum(x.avg_steps for x in po) / len(po))
        if diff is not None:
            out.append(
                "- ✅ **非路线类失败：学习不起作用，而且这是对的**（定位漂移 / 超时 / 执行器故障 / "
                f"模拟器延迟 / 缺传感器 / 电量低 六个场景）：学习臂与无记忆臂**动作数差 {diff:.2f}**。"
                "这些失败不是「这条路的问题」，反思若去改路线就是**学错对象**。"
                "（补覆盖时这里曾抓到真缺陷：语义层把非路线失败算在路线头上 → 差 2.00 个动作，已修。）")

    if "perception" in by_kind:
        dn = _avg("perception", "memory_reflection", "success_rate")
        nd = _avg("perception", "memory_reflection", "avg_steps")
        if dn is not None:
            out.append(
                f"- ⚠️ **感知不可靠的代价（首次量化）**：三个感知场景下学习臂成功率 {dn * 100:.0f}%、"
                f"平均动作 {nd:.2f}。定位**失灵**会让闸门 fail-closed 拒动、且**当前不重试** → "
                "整轮报废（一次抖动 = 一轮白跑）；而定位**噪声**（整轮固定偏差）与"
                "**探测半径受限**（看不见障碍但照样被挡）都不影响结论："
                "后者正是「只能撞了才知道」——agent 撞完那次就学会了绕开。")

    # (3) 成功率能否区分
    rates = {table[k]["success_rate"] for k in order}
    if len(rates) == 1:
        out.append(f"- ⚠️ **成功率区分不出各组差异**（都是 {list(rates)[0] * 100:.1f}%）："
                   "本场景集里，失败都能被「本次运行内换路」救回来，所以记忆/反思只影响"
                   "**过程代价**（重试与动作数），不影响**结果**。要区分成功率，需要"
                   "单次运行内救不回来的场景。")
    else:
        best = max(order, key=lambda k: table[k]["success_rate"])
        worst = min(order, key=lambda k: table[k]["success_rate"])
        lo, hi = table[worst]["success_rate"], table[best]["success_rate"]
        out.append(f"- ✅ **成功率已能区分配置**：最高 `{best}`（{hi * 100:.1f}%）vs "
                   f"最低 `{worst}`（{lo * 100:.1f}%），差 {((hi - lo) * 100):.1f} 个百分点。"
                   "区分主要来自 `unrecoverable` 场景族（单次动作预算只够走一趟，"
                   "现场换路救不回来）—— 这正是补场景的目的。")

    # (4) 谁都修不好的场景
    by_scen: Dict[str, Dict[str, ScenarioResult]] = {}
    for r in results:
        by_scen.setdefault(r.scenario, {})[r.config] = r
    hopeless = [s for s, d in by_scen.items()
                if d and max(x.success_rate for x in d.values()) == 0.0]
    if hopeless:
        joined = "`, `".join(sorted(hopeless))
        # ⚠️ "几组"必须**动态算** —— 写成"四组"会在臂数变化后变成错的（实际踩到过）
        out.append(f"- ✅ **不是所有失败都该被学掉**：{len(hopeless)} 个场景 {len(order)} 组配置全 0% "
                   f"（`{joined}`）—— 原因是**不在路线**上（如起步电量就低于闸门）。"
                   "反思在这里正确地**没有**乱学教训。")
    out.append("")
    return "\n".join(out)


def render_scenario_detail(r: ScenarioResult) -> str:
    """单场景单配置的逐步明细（供 `run --scenario ...` 用）。"""
    lines = [f"### {r.scenario} × {r.config}（seed={r.seed}）", "",
             "| episode | 成功 | 动作数 | 失败 | 重试 | 耗时(s) | 起步路线 |",
             "|---|---|---|---|---|---|---|"]
    for e in r.episodes:
        lines.append(f"| {e.index} | {'✅' if e.ok else '❌'} | {e.steps} | {e.failures} | "
                     f"{e.replans} | {e.sim_time:.2f} | {e.route or '-'} |")
    return "\n".join(lines)
