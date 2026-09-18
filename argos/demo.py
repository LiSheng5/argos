"""端到端 Demo（Phase 8）—— 指令第十六、十七节要的那条完整链路。

    python -m argos.demo                     # 生成 examples/sim_trace/ + 文档/demo_trace.md
    python -m argos.demo --seed 7 --out-dir examples/sim_trace

故事（纯仿真）：
    用户："去充电站" → 规划走北线 → 被 north_block 挡住 → 反思 → 记住教训
    → 再来说一次："去充电站" → **直接走南线**。

Trace 是**如实记录的**：没有的字段写 null，不编造。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

from argos.agent.brain import AgentBrain, RunResult
from argos.agent.memory_agent import LessonStore
from argos.agent.planner import Planner
from argos.agent.reflection import Reflector
from argos.backends.simulator_backend import SimulatorBackend
from argos.world.mini_world import build_default_world

__all__ = ["run_demo", "render_markdown"]

GOAL = "去充电站"
ARROW = "Goal → Plan → Action → SafetyGate → Simulator → Observation → Failure → Reflection → Memory → Replan"


def _step_rows(r: RunResult) -> List[dict]:
    """把 RunResult 的 trace 摊成"指令里的 trace 形状"（缺的字段 = null，不编造）。"""
    rows = []
    for t in r.trace:
        phase = "action"
        safety = None
        failure = None
        replan = None
        if t.reason == "safety_rejected" or t.reason == "invalid_params":
            safety = f"rejected: {t.reason}"
        elif not t.ok:
            failure = f"{t.reason}: {t.detail}"
        rows.append({
            "step": t.step,
            "phase": phase,
            "route": t.route,
            "plan": t.note or None,
            "action": t.action,
            "safety": safety,
            "simulator": t.detail if t.ok else None,
            "observation": None,          # 世界观测没有逐步留存 → 如实写 null
            "failure": failure,
            "reflection": None,           # 逐条反思不落在 step 上，见 episode 级
            "memory": None,
            "replan": replan,
            "sim_time": round(t.sim_time, 4),
        })
    return rows


def run_demo(seed: int = 42, episodes: int = 3) -> dict:
    """跑完整 demo，返回可直接 json.dumps 的结构。"""
    store = LessonStore()
    reflector = Reflector(store=store, alternatives={"north": "south", "south": "north"})

    out: Dict = {
        "meta": {
            "goal": GOAL,
            "seed": seed,
            "episodes": episodes,
            "backend": "SimulatorBackend（仿真，非真机）",
            "chain": ARROW,
            "world": "Mini Robot World: Room A / Room B / Hallway / Door / north_block / Charger",
        },
        "episodes": [],
    }

    for i in range(episodes):
        world = build_default_world()
        backend = SimulatorBackend(world=world, seed=seed)
        brain = AgentBrain(backend, Planner(world), reflector, store, max_retry=2)
        before = [l.id for l in store.all()]
        r = brain.run(GOAL)
        lessons = [dataclasses.asdict(l) for l in store.all() if l.id not in before]

        out["episodes"].append({
            "episode": i,
            "initial_route": (r.trace[0].route if r.trace else None),
            "steps": _step_rows(r),
            "outcome": {
                "ok": r.ok,
                "steps": r.steps,
                "failures": r.failures,
                "replans": r.replans,
                "stop_reason": r.stop_reason,
                "final_pose": {"x": round(r.final_pose.x, 3), "y": round(r.final_pose.y, 3)},
                "sim_time": round((backend.state.sim_time), 4),
            },
            "reflection": [l for l in lessons],      # 本轮新产生的 Lesson
            "memory_after": {"lessons": [dataclasses.asdict(l) for l in store.all()]},
        })
    return out


def render_markdown(trace: dict) -> str:
    lines: List[str] = []
    lines.append("# ArgOS Demo Trace —— 失败 → 反思 → 换路线")
    lines.append("")
    lines.append("> 由 `python -m argos.demo` 生成。**纯仿真**，不接任何硬件。")
    lines.append(f"> seed = `{trace['meta']['seed']}`；链路：")
    lines.append(">")
    lines.append(f"> `{trace['meta']['chain']}`")
    lines.append("")
    lines.append("## 故事")
    lines.append("")
    lines.append(f"1. 用户说「{trace['meta']['goal']}」→ 规划走**北线** → 被 `north_block` 挡住 → 反思 → 记住教训")
    lines.append("2. 用户再说一次「去充电站」→ 到了够证据的那一次之后，**规划阶段就直接走南线**")
    lines.append("")
    lines.append("## 每轮的逐步 trace")
    lines.append("")
    for ep in trace["episodes"]:
        oc = ep["outcome"]
        flag = "✅" if oc["ok"] else "❌"
        lines.append(f"### Episode {ep['episode']} —— 起步路线 `{ep['initial_route']}` → {flag}")
        lines.append("")
        lines.append("| # | 动作 | 计划理由 | 安全闸 | 仿真结果 | 失败 | sim_time |")
        lines.append("|---|---|---|---|---|---|---|")
        for s in ep["steps"]:
            lines.append(
                f"| {s['step']} | `{s['action']}` | {s['plan'] or '—'} | "
                f"{s['safety'] or '通过'} | {s['simulator'] or '—'} | "
                f"{s['failure'] or '—'} | {s['sim_time']} |")
        lines.append("")
        lines.append(f"- 结果：**{'成功' if oc['ok'] else '失败'}**（{oc['stop_reason']}）"
                     f"，动作 {oc['steps']} 次、失败 {oc['failures']} 次、重规划 {oc['replans']} 次，"
                     f"终点 `({oc['final_pose']['x']}, {oc['final_pose']['y']})`")
        if ep["reflection"]:
            lines.append(f"- 本轮新产生的 Lesson：**{len(ep['reflection'])} 条**")
            for l in ep["reflection"]:
                lines.append(f"  - `{l['id']}`：避开 **{l['avoid']}**，改用 **{l['prefer']}**"
                             f"（置信度 {l['confidence']:.2f}，证据：{l['evidence']}）")
        lines.append("")
    lines.append("## 怎么自己复现")
    lines.append("")
    lines.append("```bash")
    lines.append("python -m argos.demo                                  # 生成本文件 + JSON trace")
    lines.append("python -m argos.benchmark all --out 文档/BENCHMARK.md  # 四组配置对比")
    lines.append("python -m argos.benchmark run --scenario transient_jam_latency_none --config memory_only")
    lines.append("```")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="argos.demo", description="ArgOS 端到端 Demo（仿真）")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--episodes", type=int, default=3)
    p.add_argument("--out-dir", default="examples/sim_trace")
    p.add_argument("--md", default="文档/demo_trace.md")
    args = p.parse_args(argv)

    trace = run_demo(seed=args.seed, episodes=args.episodes)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "demo_trace.json"
    json_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")

    md_path = Path(args.md)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_markdown(trace), encoding="utf-8")

    print(f"已写出 {json_path} 与 {md_path}")
    for ep in trace["episodes"]:
        oc = ep["outcome"]
        print(f"  episode {ep['episode']}: 起步 {ep['initial_route']} → "
              f"{'成功' if oc['ok'] else '失败'}，失败 {oc['failures']} 次")
    return 0


if __name__ == "__main__":
    sys.exit(main())
