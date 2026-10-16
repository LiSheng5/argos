#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""文档一致性检查 —— 提交前硬门用（P2，2026-09-21 固化）。

用法：
    python scripts/check_docs.py                 # 常规：1/2/3 有问题才算失败
    python scripts/check_docs.py --strict        # 连第 4 项"提示"也算失败

查四样：
  1. 死链：文档/代码里**带目录前缀**的引用（文档/ 商议/ 待办/，含 文档/archive/ 子目录）是否真实存在。
     扫描范围含 *.py —— 死链常藏在代码注释与测试 docstring 里（2026-09-21 实测：
     9 处断链里 2 处在 .py）。
  2. 数字漂移：测试数 / 场景数 / 配置数 与唯一权威源是否一致。
  3. 索引完整性：文档/README.md 列出的文件是否存在，目录里是否有文件没被索引。
  4. 过期词提示：出现"当前/现在/现状/计划/待做"且同行有数字。

豁免规则（不豁免的话历史快照会全红）：
  - 文件级：文件名含 8 位日期，或开头 300 字含"不随代码更新 / 快照 / 当时 / 审计 / 立项"
  - 行级：该行含"截至 / 当时 / 快照 / 历史 / 审计当时 / 那次"

设计原则：**宁可少报，不可假红** —— 假红会被习惯性忽略，等于没有检查。
"""

import os
import re
import sys
import glob

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DOC_DIRS = ["文档", "商议", "待办"]
REF_RE = re.compile(r"((?:文档|商议|待办)/(?:[\w\u4e00-\u9fff（）()_\-\.]+/)*[\w\u4e00-\u9fff（）()_\-\.]+\.md)")

# 豁免词：命中即为"历史快照"，不做数字与过期词检查
HEAD_EXEMPT = ["不随代码更新", "快照", "当时", "审计", "立项", "历史流水账"]
LINE_EXEMPT = ["截至", "当时", "当日", "快照", "历史", "审计当时", "那次", "曾经", "装好", "上游 SDK", "→", "从 "]
DATE_IN_NAME = re.compile(r"\d{8}")


def all_md_files():
    files = []
    for d in DOC_DIRS:
        files += glob.glob(os.path.join(ROOT, d, "*.md"))
    files.append(os.path.join(ROOT, "README.md"))
    return sorted(files)


def all_code_files():
    files = []
    for pat in ("argos/**/*.py", "tests/*.py", "scripts/*.py"):
        files += glob.glob(os.path.join(ROOT, pat.replace("/", os.sep)), recursive=True)
    return sorted(files)


def read(p):
    with open(p, encoding="utf-8", errors="ignore") as f:
        return f.read()


def rel(p):
    return os.path.relpath(p, ROOT).replace("\\", "/")


def is_exempt_file(path, text):
    if DATE_IN_NAME.search(os.path.basename(path)):
        return True
    return any(w in text[:300] for w in HEAD_EXEMPT)


# ---------- 1. 死链 ----------
def check_links():
    bad = []
    total = 0
    for f in all_md_files() + all_code_files():
        for m in REF_RE.finditer(read(f)):
            total += 1
            p = m.group(1)
            if not os.path.exists(os.path.join(ROOT, p.replace("/", os.sep))):
                bad.append((rel(f), p))
    return total, sorted(set(bad))


# ---------- 2. 数字一致性 ----------
def read_authority():
    """从唯一权威源读当前数字。

    passed 可能有两个**都合法**的值：裸环境值 与 "装了上游 SDK 后" 的值 —— 两者都算对。
    """
    auth = {"passed": set()}
    base = os.path.join(ROOT, "文档", "测试基线.md")
    if os.path.exists(base):
        for m in re.finditer(r"(\d{3,4})\s*passed", read(base)):
            auth["passed"].add(m.group(1))
    bm = os.path.join(ROOT, "文档", "BENCHMARK.md")
    if os.path.exists(bm):
        t = read(bm)
        m = re.search(r"场景数：(\d+)", t)
        if m:
            auth["scenarios"] = m.group(1)
        m = re.search(r"配置数：(\d+)", t)
        if m:
            auth["configs"] = m.group(1)
    return auth


# 场景数只认 1~2 位：三位数（"630 场景"）说的是"场景运行次数"，不是场景库大小。
# (?<!\d) 防止从 "630" 里截出 "30" 这种假匹配。
NUM_PATS = [
    ("passed", re.compile(r"(\d{3,4})\s*passed")),
    ("scenarios", re.compile(r"(?<!\d)(\d{1,2})\s*场景")),
    ("configs", re.compile(r"(?<!\d)(\d)\s*(?:组配置|臂)")),
]


def check_numbers(auth):
    problems = []
    sources = {os.path.join(ROOT, "文档", "测试基线.md"), os.path.join(ROOT, "文档", "BENCHMARK.md")}
    for f in all_md_files() + all_code_files():
        if f in sources:
            continue
        text = read(f)
        if is_exempt_file(f, text):
            continue
        for line in text.split("\n"):
            if any(w in line for w in LINE_EXEMPT):
                continue
            for key, pat in NUM_PATS:
                if key not in auth:
                    continue
                m = pat.search(line)
                if not m:
                    continue
                got = m.group(1)
                ok = got in auth[key] if isinstance(auth[key], set) else got == auth[key]
                if not ok:
                    want = "/".join(sorted(auth[key])) if isinstance(auth[key], set) else auth[key]
                    problems.append((rel(f), key, got, want, line.strip()[:70]))
    return problems


# ---------- 3. 索引完整性 ----------
def check_index():
    idx = os.path.join(ROOT, "文档", "README.md")
    if not os.path.exists(idx):
        return ["文档/README.md 不存在（索引缺失）"], []
    text = read(idx)
    listed = set(re.findall(r"`([\w\u4e00-\u9fff（）()_\-\.]+\.md)`", text))
    missing = [m for m in listed if not os.path.exists(os.path.join(ROOT, "文档", m))]
    actual = {os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "文档", "*.md"))}
    unlisted = sorted(actual - listed - {"README.md"})
    return (
        [f"索引列出但不存在：{m}" for m in sorted(missing)],
        unlisted,
    )


# ---------- 4. 过期词提示 ----------
def check_stale():
    hits = []
    pat = re.compile(r"(当前|现在|现状|计划|待做)[^\n]{0,40}\d")
    for f in all_md_files():
        text = read(f)
        if is_exempt_file(f, text):
            continue
        for i, line in enumerate(text.split("\n"), 1):
            if any(w in line for w in LINE_EXEMPT):
                continue
            if pat.search(line):
                hits.append((rel(f), i, line.strip()[:70]))
    return hits


def main():
    strict = "--strict" in sys.argv
    print("=" * 60)
    print("文档一致性检查 ——", ROOT)
    print("=" * 60)

    total, bad = check_links()
    print(f"\n1) 死链：扫描引用 {total} 处，失效 {len(bad)} 处")
    for s, p in bad:
        print(f"     {s} -> {p}")

    auth = read_authority()
    print(f"\n2) 数字一致性：权威源 = {auth}")
    probs = check_numbers(auth) if auth else []
    print(f"     不一致 {len(probs)} 处")
    for s, k, got, want, line in probs:
        print(f"     {s}  {k}: 写了 {got}，权威源 {want}  |  {line}")

    miss, unlisted = check_index()
    print(f"\n3) 索引完整性：缺失 {len(miss)}，未被索引 {len(unlisted)}")
    for m in miss:
        print(f"     {m}")
    for u in unlisted:
        print(f"     未索引：{u}")

    stale = check_stale()
    print(f"\n4) 过期词提示（{len(stale)} 条，默认不算失败）")
    for s, i, line in stale[:5]:
        print(f"     {s}:{i}  {line}")
    if len(stale) > 5:
        print(f"     ... 另有 {len(stale) - 5} 条")

    failed = bool(bad) or bool(probs) or bool(miss)
    if strict and stale:
        failed = True

    print("\n" + "=" * 60)
    print("结论：", "❌ 失败（请修完再提交）" if failed else "✅ 通过")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
