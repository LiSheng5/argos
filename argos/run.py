"""统一运行入口（指令 §21）。

    python -m argos.run --list-backends
    python -m argos.run --backend simulator --goal "去充电站" --episodes 3
    python -m argos.run --backend go2        # ← 会**如实报未实现**，不伪造

设计要点
--------
* **backend 用名字选**，`Brain / Planner / Memory / Reflector / SafetyGate` 一行都不用改
  —— 这就是"换身体不改大脑"的落点（验收项 §25-9「可替换」）。
* `go2` 之类**没有实现的 backend 必须明确报错**。本项目当前没有真机，
  绝不写一个假的 real executor 来"看起来完成"（指令 §18 / §28）。
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Dict, List, Optional

from argos.agent.brain import AgentBrain
from argos.agent.memory_agent import LessonStore
from argos.agent.planner import Planner
from argos.agent.reflection import Reflector
from argos.world.mini_world import build_default_world
from argos.backends.simulator_backend import SimulatorBackend
from argos.input import INPUTS, build_input

__all__ = ["BACKENDS", "register_backend", "build_backend", "run", "main"]

#: backend 注册表。未来接真机就在这里加一行（例：`"go2": build_go2_backend`），
#: **上层零改动**。刻意不用自动扫描：显式注册才能一眼看出"到底有哪些身体可用"。
BACKENDS: Dict[str, Callable[..., object]] = {}

DEFAULT_GOAL = "去充电站"
DEFAULT_ALTERNATIVES = {"north": "south", "south": "north"}


def register_backend(name: str):
    def deco(fn: Callable[..., object]) -> Callable[..., object]:
        BACKENDS[name] = fn
        return fn
    return deco


@register_backend("simulator")
def build_simulator_backend(*, seed: int = 42, start_at: str = "room_a", **kw):
    """**仿真**后端（本阶段唯一的 embodiment）。不接任何硬件。"""
    return SimulatorBackend(seed=seed, start_at=start_at, **kw)


def build_backend(name: str, **kw):
    """按名字装配 backend。名字不存在 → 明确报错，不静默退回 simulator。"""
    if name not in BACKENDS:
        known = "、".join(sorted(BACKENDS))
        raise KeyError(
            f"没有名为 {name!r} 的 backend。当前可用：{known}。\n"
            f"  说明：{name!r} 尚未实现 —— 本项目**当前没有真实机器人硬件**，"
            "也不会写一个假的真机 backend 来冒充完成。规划见 文档/ROADMAP.md。"
        )
    return BACKENDS[name](**kw)


def _route_topology(be):
    """取路线拓扑。

    ⚠️ **已知限制**：`Planner` 目前仍依赖 `MiniWorld` 的路线图，
    所以它读的是 backend 的 `world` 属性 —— 严格说这不属于 `EmbodimentBackend` 协议。
    真机 backend 必须提供路线拓扑（或 Planner 改成从 `Observation` 里取），
    在那之前这里**如实报错**，不假装"完全 backend 无关"。
    """
    world = getattr(be, "world", None)
    if world is None:
        raise NotImplementedError(
            "该 backend 没有提供路线拓扑：Planner 目前仍绑在 MiniWorld 上。"
            "这是已知限制（见 文档/ROADMAP.md Wave 3），不在这里伪造。")
    return world


def resolve_goal(utterance: str, input_name: str = "text", planner=None) -> Optional[str]:
    """一句话 → goal。认不出返回 None（**不猜**）。

    `speech` 需要 resolver 校验地点名，所以要么给 planner，要么它会明确报错。
    """
    if planner is None:
        planner = Planner(build_default_world())
    be = build_backend("simulator", seed=0)
    return build_input(input_name, planner.resolve_target).goal_from(utterance)


def run(goal: str = DEFAULT_GOAL, backend: str = "simulator", seed: int = 42,
        episodes: int = 3, revalidate_every: int = 0,
        trace_path: Optional[str] = None, verbose: bool = True):
    """跑完整闭环：Goal → … → Memory → Replan，跨 episode 共享记忆。

    返回 `(episodes_trace, lessons)`，便于测试直接断言而不靠打印。
    """
    store = LessonStore()
    reflector = Reflector(store=store, alternatives=dict(DEFAULT_ALTERNATIVES),
                          revalidate_every=revalidate_every)
    out: List[dict] = []

    for i in range(episodes):
        be = build_backend(backend, seed=seed)
        brain = AgentBrain(be, Planner(_route_topology(be)), reflector, store,
                           lesson_threshold=0.6)
        before = {l.id for l in store.all()}
        r = brain.run(goal)
        new_lessons = [asdict(l) for l in store.all() if l.id not in before]

        out.append({
            "episode": i,
            "ok": r.ok,
            "steps": r.steps,
            "failures": r.failures,
            "replans": r.replans,
            "stop_reason": r.stop_reason,
            "final_pose": {"x": round(r.final_pose.x, 3), "y": round(r.final_pose.y, 3)},
            # 走协议方法取时间，不碰 backend 私有属性
            "sim_time": round(be.observe().sim_time, 4),
            "route": (r.trace[0].route if r.trace and r.trace[0].route else None),
            "new_lessons": new_lessons,
            "steps_detail": r.as_rows(),
        })

        if verbose:
            flag = "✅" if r.ok else "❌"
            extra = f"，新教训 {len(new_lessons)} 条" if new_lessons else ""
            print(f"  episode {i}: 起步 {out[-1]['route'] or '-'} → {flag} "
                  f"动作 {r.steps}，失败 {r.failures}，重规划 {r.replans}{extra}")

    if trace_path:
        p = Path(trace_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "meta": {"goal": goal, "backend": backend, "seed": seed,
                     "episodes": episodes, "revalidate_every": revalidate_every},
            "episodes": out,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        if verbose:
            print(f"trace 已写出：{p}")

    return out, store.all()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="argos.run",
        description="ArgOS 统一运行入口（Simulator 是当前唯一的 embodiment）")
    p.add_argument("--backend", default="simulator",
                   help="用哪个 embodiment 跑；未知名字会明确报错")
    p.add_argument("--list-backends", action="store_true", help="列出可用 backend")
    p.add_argument("--goal", default=DEFAULT_GOAL)
    p.add_argument("--input", default="text", choices=sorted(INPUTS),
                   help="输入后端：text=直通 / speech=口语规则抽取（不是语音识别）")
    p.add_argument("--say", default="",
                   help="用一句话指定目标（配合 --input）；听不懂会明确报错，不会瞎猜")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--episodes", type=int, default=3)
    p.add_argument("--revalidate-every", type=int, default=0,
                   help="每隔几个 episode 复核一次被避开的路线（0=不复核）")
    p.add_argument("--trace", default="", help="把逐步 trace 写成 JSON")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    if args.list_backends:
        print("可用 backend：")
        for name in sorted(BACKENDS):
            print(f"  - {name}")
        print("（未列出、但指令提过的 `go2` 等：尚未实现，本项目当前没有真机硬件）")
        return 0

    goal = args.goal
    if args.say:
        goal = resolve_goal(args.say, args.input)
        if goal is None:
            print(f"没听懂：{args.say!r}（--input {args.input}）。"
                  "不会猜一个目标去执行 —— 换个说法或直接用 --goal。", file=sys.stderr)
            return 2

    verbose = not args.quiet
    if verbose:
        print(f"backend={args.backend}  goal={goal!r}  seed={args.seed}  "
              f"episodes={args.episodes}"
              + (f"  input={args.input}  say={args.say!r}" if args.say else ""))

    try:
        eps, lessons = run(goal=goal, backend=args.backend, seed=args.seed,
                           episodes=args.episodes,
                           revalidate_every=args.revalidate_every,
                           trace_path=args.trace or None, verbose=verbose)
    except KeyError as e:
        print(f"错误：{e.args[0] if e.args else e}", file=sys.stderr)
        return 2

    if verbose:
        ok = sum(1 for e in eps if e["ok"])
        print(f"完成：{ok}/{len(eps)} 个 episode 成功；累计教训 {len(lessons)} 条")
        for l in lessons:
            print(f"  · 避开 {l.avoid}，改用 {l.prefer}"
                  f"（置信度 {l.confidence:.2f}，证据数 {l.hits}）")
    return 0 if all(e["ok"] for e in eps) else 1


if __name__ == "__main__":
    sys.exit(main())
