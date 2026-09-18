"""Benchmark CLI（Phase 7/8）。

    python -m argos.benchmark list
    python -m argos.benchmark run  --scenario permanent_block_x5.0_northfirst --seed 42
    python -m argos.benchmark all  --out 文档/BENCHMARK.md

全部在仿真里跑，不碰任何硬件。同 seed 结果可复现。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from argos.benchmark.configs import CONFIGS, config_by_name
from argos.benchmark.report import render_markdown, render_scenario_detail
from argos.benchmark.runner import DEFAULT_SEEDS, run_matrix, run_scenario
from argos.benchmark.scenarios import build_scenarios, by_name, summary_table


def _cmd_list(_args) -> int:
    print(summary_table())
    return 0


def _cmd_run(args) -> int:
    sc = by_name(args.scenario)
    cfg = config_by_name(args.config)
    r = run_scenario(sc, cfg, args.seed)
    print(render_scenario_detail(r))
    print()
    print(f"成功率 {r.success_rate * 100:.0f}% / 平均失败 {r.avg_failures:.2f} / "
          f"平均动作 {r.avg_steps:.2f} / 平均耗时 {r.avg_time:.2f}s")
    return 0


def _cmd_all(args) -> int:
    seeds = tuple(int(x) for x in args.seeds.split(","))
    results = run_matrix(seeds=seeds)
    text = render_markdown(results, seeds)
    if args.out:
        out = Path(args.out)
        out.write_text(text, encoding="utf-8")
        print(f"已写出 {out}（{len(results)} 组结果，seed={list(seeds)}）")
    else:
        print(text)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="argos.benchmark",
                                description="ArgOS Reflection Benchmark（纯仿真）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="列出全部场景").set_defaults(func=_cmd_list)

    pr = sub.add_parser("run", help="跑单个场景 × 单个配置")
    pr.add_argument("--scenario", required=True)
    pr.add_argument("--config", default="memory_reflection",
                    choices=[c.name for c in CONFIGS])
    pr.add_argument("--seed", type=int, default=42)
    pr.set_defaults(func=_cmd_run)

    pa = sub.add_parser("all", help="跑完整矩阵并生成报告")
    pa.add_argument("--out", default="")
    pa.add_argument("--seeds", default=",".join(str(s) for s in DEFAULT_SEEDS))
    pa.set_defaults(func=_cmd_all)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
