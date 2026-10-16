#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成物新鲜度门 —— 提交前检查（2026-10-16 固化，方案 C）。

为什么要有它：
  `文档/BENCHMARK.md` / `文档/SWEEP.md` / `文档/demo_trace.md`
  （以及 `examples/sim_trace/demo_trace.json`）都是**生成物**，但它们**入库**——
  因为 GitHub 读者得能直接看到实测数据（那是本项目的卖点）。
  可是历史已经两次出现"生成物与生成器对不上"：
    ① `benchmark/report.py` 把配置组数写死成"四组"，臂数变了之后一直在说谎；
    ② `demo.py` 把"四组配置对比"写死，而仓库里的 `demo_trace.md` 被手改成了"（当前 6 组）"。
  所以把"忘了重生成"从"靠人记得"改成"提交前必然被抓"。

做法：
  把每个生成器各跑一遍到**临时目录**，与仓库里的文件比对（忽略 CRLF/LF 差异）：
    一致   → ✅ 通过；
    不一致 → ❌ 报"哪一份漂了 + 第几行 + 重生成命令"，退出码 1（别提交）。

用法：
    python scripts/check_generated.py                # 全查（慢，见下）
    python scripts/check_generated.py --only demo    # 只查一份：demo / demo-json / benchmark / sweep
    python scripts/check_generated.py --list         # 只列出要查什么（不生成）
    python scripts/check_generated.py --timeout 1800 # 单个生成器超时（默认 900s）

⚠️ 全查要跑完整 benchmark 矩阵（35 场景 × 6 配置 × 3 seed）与参数扫描，**可能要几分钟**；
   只想快速自查"文档改动有没有顺手破坏生成物"时，用 `--only demo`。

设计原则与 `check_docs.py` 一致：**宁可少报，不可假红**（假红会被习惯性忽略）。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: name, 仓库里的相对路径, 生成命令（python 之后的参数；占位符见下）, 被比较的产出文件, 给人看的重生成命令
#: 占位符：{out} = 本次要比对的临时文件；{outdir} = 临时目录（demo 还会往这里写 JSON）
TARGETS = [
    (
        "demo",
        "文档/demo_trace.md",
        ["-m", "argos.demo", "--md", "{out}", "--out-dir", "{outdir}"],
        "{out}",
        "python -m argos.demo",
    ),
    (
        "demo-json",
        "examples/sim_trace/demo_trace.json",
        ["-m", "argos.demo", "--md", "{outdir}/_probe.md", "--out-dir", "{outdir}"],
        "{outdir}/demo_trace.json",
        "python -m argos.demo",
    ),
    (
        "benchmark",
        "文档/BENCHMARK.md",
        ["-m", "argos.benchmark", "all", "--out", "{out}"],
        "{out}",
        "python -m argos.benchmark all --out 文档/BENCHMARK.md",
    ),
    (
        "sweep",
        "文档/SWEEP.md",
        ["-m", "argos.benchmark", "sweep", "--out", "{out}"],
        "{out}",
        "python -m argos.benchmark sweep --out 文档/SWEEP.md",
    ),
]


def read_text(path):
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read().replace("\r\n", "\n")


def first_diff(repo_text, new_text):
    a, b = repo_text.split("\n"), new_text.split("\n")
    for i in range(max(len(a), len(b))):
        x = a[i] if i < len(a) else "<仓库里没有这一行>"
        y = b[i] if i < len(b) else "<重生成没有这一行>"
        if x != y:
            return i + 1, x, y
    return None


def check_one(repo_rel, cmd_tpl, produced_tpl, timeout):
    repo_path = os.path.join(ROOT, repo_rel.replace("/", os.sep))
    if not os.path.exists(repo_path):
        return "missing", "仓库里没有它（生成物应当入库）", None

    with tempfile.TemporaryDirectory(prefix="argos_regen_") as td:
        out = os.path.join(td, "out.md")
        fmt = {"out": out, "outdir": td.replace("\\", "/")}
        cmd = [sys.executable] + [c.format(**fmt) for c in cmd_tpl]
        t0 = time.time()
        try:
            r = subprocess.run(
                cmd, cwd=ROOT, capture_output=True, text=True,
                encoding="utf-8", errors="ignore", timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return "error", f"生成超时（>{timeout}s）", None
        dt = time.time() - t0
        if r.returncode != 0:
            tail = (r.stderr or r.stdout or "").strip().split("\n")[-1][:160]
            return "error", f"生成器退出码 {r.returncode}：{tail}", None

        produced = produced_tpl.format(**fmt)
        if not os.path.exists(produced):
            return "error", f"生成器没有产出 {os.path.basename(produced)}", None
        new_text = read_text(produced)
        repo_text = read_text(repo_path)

    if new_text == repo_text:
        return "ok", f"{dt:.1f}s", None
    return "stale", f"{dt:.1f}s", first_diff(repo_text, new_text)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="check_generated",
                                 description="生成物新鲜度门（提交前检查）")
    ap.add_argument("--only", default="", help="只查一份：" + " / ".join(t[0] for t in TARGETS))
    ap.add_argument("--timeout", type=int, default=900, help="单个生成器超时秒数（默认 900）")
    ap.add_argument("--list", action="store_true", help="只列出要查的生成物，不生成")
    args = ap.parse_args(argv)

    if args.list:
        for name, rel, _cmd, _prod, regen in TARGETS:
            print(f"{name:10s} {rel:34s} ← {regen}")
        return 0

    targets = [t for t in TARGETS if not args.only or t[0] == args.only]
    if args.only and not targets:
        print(f"未知的 --only={args.only}；可选：{[t[0] for t in TARGETS]}", file=sys.stderr)
        return 2

    print("=" * 60)
    print("生成物新鲜度门 ——", ROOT)
    print("=" * 60)

    bad = []
    for name, rel, cmd_tpl, produced_tpl, regen in targets:
        status, info, diff = check_one(rel, cmd_tpl, produced_tpl, args.timeout)
        mark = "✅" if status == "ok" else "❌"
        print(f"\n{mark} {name:10s} {rel}  ({info})")
        if status == "ok":
            continue
        bad.append(name)
        if status == "stale" and diff:
            n, want, got = diff
            print(f"     第 {n} 行起不一致：")
            print(f"       仓库里：  {want[:110]}")
            print(f"       重生成：  {got[:110]}")
        print(f"     修法：{regen}")

    print("\n" + "=" * 60)
    if bad:
        print(f"结论：❌ {len(bad)} 份生成物已漂移：{'、'.join(bad)}")
        print("       → 按上面的命令重生成后，连生成物一起提交")
    else:
        print("结论：✅ 生成物与生成器一致")
    print("=" * 60)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
