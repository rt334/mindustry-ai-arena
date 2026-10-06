#!/usr/bin/env python3
"""边界检查 —— skill/（参赛者可见包）里不许出现游戏内情。

    python drive/check-boundary.py           检查并列出问题
    python drive/check-boundary.py --list-rules   打印全部规则（透明）
    python drive/check-boundary.py --all     连「提示」也一并展开

为什么需要它（见 docs/TODO.md §九 #9）：`skill/` 声称「刻意不含任何游戏内情」，
但那一直是**声明**，靠人写的时候小心。参考项目 `hanhe-mint/-ai-rimworld-ai-teammate`
的做法是让不合规范的东西**进不了上下文**（靠格式与命名，不靠声明）。
这里做一个本地可跑的等价物：**不合规范的 skill 内容，会在提交前被拦下。**

规则刻意保守：宁可少禁（避免噪音把规则变成摆设），但每条都有明确理由。
  违规 → 退出码 1（可挂进 CI / 提交前检查）
  提示 → 只列出，不影响退出码（要人看一眼）

豁免：在命中行的**同一行**或**上一行**写 `boundary-ok: 原因` 即跳过 ——
理由是"这条看起来像游戏内情，但此处是必要的用法示例"。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "skill"

# ---- 违规规则：(名称, 正则, 理由) ----
RULES: list[tuple[str, re.Pattern, str]] = [
    ("引擎内幕", re.compile(r"hardness|drillTime|getDrillTime|liquidBoostIntensity|"
                            r"dominantItems?|sizeOffset|hardnessDrillMultiplier"),
     "引擎公式/字段属于「实测出来的游戏内情」，玩家看不到"),
    ("产率数字", re.compile(r"[+\-]?\d+\.\d+\s*/\s*s"),
     "带小数的每秒产率是实测结论（限流写成整数 60/s，不会命中这条）"),
    ("地图名", re.compile(r"\b(veins|glacier|passage)\b"),
     "官方 PvP 图名暗示地形与资源分布；要选图用 /maps 运行时查"),
    ("方块参数", re.compile(r"\btier\s*[=:]\s*\d|itemCapacity|hardness\s*=\s*\d"),
     "方块的性能参数要 AI 自己在游戏里试出来"),
    ("布局结论", re.compile(r"(放在|贴着|挨着|尽量靠)[^。\n]{0,12}(核心|干线|矿区)"),
     "「该放在哪」是结论，不是规则 —— 按对等约束的红线不给"),
]

# ---- 提示规则：只列出，不算违规 ----
HINTS: list[tuple[str, re.Pattern, str]] = [
    ("指向维护者文档", re.compile(r"docs/[A-Z][A-Z\-]*\.md|ENGINE-NOTES|DESIGN\.md|LESSONS\.md|TODO\.md"),
     "指向 docs/ 本身没问题（那里标注了「非 agent 读物」），但值得确认标注还在"),
    ("具体坐标对", re.compile(r"\(\s*\d{1,3}\s*,\s*\d{1,3}\s*\)"),
     "单个坐标作为用法示例是允许的；若成片出现就变成了布局建议"),
    ("方块/物品名", re.compile(r"\b(conveyor|sorter|router|junction|drill|press|smelter|"
                               r"copper|lead|coal|sand|titanium|graphite|silicon)\b", re.I),
     "名字本身允许（API 示例需要），但若与参数、数量、位置连用就会泄漏"),
]

SKIP_SUFFIX = {".pyc", ".png", ".jpg", ".jar"}
EXEMPT = re.compile(r"boundary-ok\s*[:：]?\s*(.+)")

# 自测样本：每条「违规规则」至少要能命中一个 ——
# 否则规则形同虚设，而报告会显示「违规 0」，看起来像一切正常（假绿）。
SELFTEST = [
    ("引擎内幕", "煤的 hardness = 2，钻机每 500 帧出一个"),
    ("产率数字", "单台机械钻约 0.35/s，实测核心铜 +2.04/s"),
    ("地图名", "在 veins 上开局，或者选 passage"),
    ("方块参数", "pneumatic-drill tier: 3，itemCapacity=10"),
    ("布局结论", "把压机贴着核心放，干线尽量靠矿区铺"),
    ("豁免机制", "这里的 hardness 是用法示例 boundary-ok: 讲解公式用"),
]


def selftest() -> int:
    """验证规则本身有效：每条违规规则的样本都必须被命中。"""
    print("自测：逐条规则喂一个样本，看是否命中\n")
    failed = []
    for expect, sample in SELFTEST:
        hit = None
        for name, pat, _ in RULES:
            if pat.search(sample):
                hit = name
                break
        if expect == "豁免机制":
            # 这一条要验证的是「能识别豁免标记」，不是规则命中
            ok = bool(EXEMPT.search(sample))
            print(f"  {'✓' if ok else '✗'} {expect:<8} 样本含 boundary-ok → {ok}")
            if not ok:
                failed.append(expect)
            continue
        ok = (hit == expect)
        print(f"  {'✓' if ok else '✗'} {expect:<8} 期望 [{expect}] → 实际 [{hit or '未命中'}]")
        if not ok:
            failed.append(expect)
    print()
    if failed:
        print(f"自测失败：{failed} —— 规则需要修")
        return 1
    print(f"自测通过：{len(SELFTEST)} 条样本全部按预期命中 ✓")
    return 0


def scan_file(path: Path) -> tuple[list[str], list[str]]:
    bad: list[str] = []
    hints: list[str] = []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    try:
        rel = path.relative_to(ROOT).as_posix()
    except ValueError:          # --selftest 会在 ROOT 之外放临时样本
        rel = path.name
    for i, line in enumerate(lines):
        # 豁免：本行或上一行有 boundary-ok
        here = EXEMPT.search(line)
        prev = EXEMPT.search(lines[i - 1]) if i > 0 else None
        if here or prev:
            continue
        for name, pat, why in RULES:
            m = pat.search(line)
            if m:
                bad.append(f"{rel}:{i+1}: [{name}] 命中「{m.group(0)}」 —— {why}")
        for name, pat, why in HINTS:
            m = pat.search(line)
            if m:
                hints.append(f"{rel}:{i+1}: [{name}] 「{m.group(0)}」 —— {why}")
    return bad, hints


def main() -> int:
    ap = argparse.ArgumentParser(description="skill/ 边界检查")
    ap.add_argument("--list-rules", action="store_true", help="打印全部规则")
    ap.add_argument("--all", action="store_true", help="连提示一并展开")
    ap.add_argument("--selftest", action="store_true", help="自测规则是否真的能命中")
    ap.add_argument("--target", default="skill", help="检查目标目录（默认 skill/）")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if args.list_rules:
        print("违规规则（命中即退出码 1）：")
        for name, pat, why in RULES:
            print(f"  [{name}] {pat.pattern}\n      {why}")
        print("\n提示规则（只列出）：")
        for name, pat, why in HINTS:
            print(f"  [{name}] {pat.pattern}\n      {why}")
        return 0

    target = Path(args.target)
    if not target.is_absolute():
        target = ROOT / target
    if not target.is_dir():
        print(f"目录不存在：{target}", file=sys.stderr)
        return 1

    files = [p for p in sorted(target.rglob("*")) if p.is_file() and p.suffix not in SKIP_SUFFIX]
    allbad: list[str] = []
    allhints: list[str] = []
    for p in files:
        b, h = scan_file(p)
        allbad += b
        allhints += h

    try:
        shown = target.relative_to(ROOT).as_posix() + "/"
    except ValueError:
        shown = str(target)
    print(f"检查范围：{shown}  {len(files)} 个文件")
    for p in files:
        print(f"  - {p.relative_to(ROOT).as_posix()}")
    print()

    if allbad:
        print(f"违规 {len(allbad)} 条：")
        for x in allbad:
            print(f"  ✗ {x}")
    else:
        print("违规：0 —— skill/ 里没有命中「游戏内情」规则的内容 ✓")

    if allhints:
        print(f"\n提示 {len(allhints)} 条（需要人看一眼，不算违规）：")
        shown = allhints if args.all else allhints[:6]
        for x in shown:
            print(f"  · {x}")
        if not args.all and len(allhints) > len(shown):
            print(f"  …还有 {len(allhints) - len(shown)} 条（--all 展开）")

    return 1 if allbad else 0


if __name__ == "__main__":
    sys.exit(main())
