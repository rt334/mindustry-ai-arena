#!/usr/bin/env python3
"""第 0 档：数值与事实勘误。

三条错误：
1. REPORT/DEBUG-LOG 的每格煤产率漏了 getDrillTime 里的 `+50 × hardness` 项
   （煤 hardness = 2 ⇒ 多 100 帧），虚高 25% / 35%。
   正确：pneumatic 60/500 = 0.120，laser 60/380 = 0.158。
2. FEASIBILITY §2 把 mechanical-drill 的水加成标成「无」——
   源码里三种矿机都带 consumeLiquid(water).boost()。
3. REPORT 的结论把约束归因成「矿量」，实际支配项是近处矿量 + 干线成本。
"""
import pathlib
import sys

ROOT = pathlib.Path(r"C:\dsh\ai-arena\docs")

EDITS = {
    "FEASIBILITY.md": [
        ("| `mechanical-drill` | 2 | 600 | 2×2 | 无 |",
         "| `mechanical-drill` | 2 | 600 | 2×2 | 有 |"),
        ("""| `laser-drill` | 4 | 280 | 3×3 | 有 |

**本图无水**""",
         """| `laser-drill` | 4 | 280 | 3×3 | 有 |

**三种矿机都带 `.consumeLiquid(Liquids.water, …).boost()`**
（`mechanical 0.05` / `pneumatic 3.5/60` / `laser 0.08`），`liquidBoostIntensity = 1.6`。
早先这张表把 mechanical 标成「无」是错的，**但对下面的结论无影响**。

**本图无水**"""),
    ],

    "reviews/REPORT.md": [
        ("- pneumatic-drill 全覆盖：50 × 0.15 = **7.5 煤/s**\n"
         "- 就算全换成 laser-drill（材料完全够：石墨 870 / 钛 1959 / 硅 397）：50 × 0.214 = **10.7 煤/s**",
         "- pneumatic-drill 全覆盖：50 × 0.120 = **6.0 煤/s**\n"
         "- 就算全换成 laser-drill（材料完全够：石墨 870 / 钛 1959 / 硅 397）：50 × 0.158 = **7.9 煤/s**\n"
         "\n"
         "> **勘误（2026-10-04）**：本文早期版本写的每格 0.15 / 0.214 **漏掉了\n"
         "> `getDrillTime` 里的 `+50 × hardness` 项** —— 煤 hardness = 2，要多 100 帧。\n"
         "> 正确算式 `每格 = 60 / (drillTime + 50 × 2)`：pneumatic = 60/500 = 0.120，\n"
         "> laser = 60/380 = 0.158。旧值既不是无加成值也不是加成值，就是漏项。\n"
         "> **修正后缺口更大（16 vs 7.9），结论方向不变。**"),
        ("- 合计 **16 煤/s > 10.7 煤/s（理论上限）**",
         "- 合计 **16 煤/s > 7.9 煤/s（理论上限）**"),
        ("**结论：5/s 在这张地图上不可达，原因是矿量而非调度。** 证明见第四节。",
         "**结论：5/s 在这张地图上不可达。近处是「矿量 + 干线成本」双重约束，不是调度问题。**\n"
         "第二节给的是地质事实，`REVIEW-ADDENDUM.md` §6.3 说明工程约束才是支配项 ——\n"
         "把远处的煤接回来要 60+ 格干线，而视野半径 61 格、只有单个建造单位。"),
    ],

    "reviews/DEBUG-LOG.md": [
        ("| 钻机升级 | 用压机产出的石墨把机械钻换成 pneumatic-drill（0.10 → 0.15 每格每秒，且不吃电） | 铜/铅/煤同步 +50% |",
         "| 钻机升级 | 用压机产出的石墨把机械钻换成 pneumatic-drill（每格 0.092 → 0.133；煤因硬度 2 是 0.086 → 0.120。不吃电） | 铜/铅/煤同步 +40~44% |"),
        ("上限 7.5 煤/s（全换激光钻也只 10.7）",
         "上限 6.0 煤/s（全换激光钻也只 7.9）"),
    ],

    "reviews/REVIEW-ADDENDUM.md": [
        ("""**⇒ 如果 REPORT.md 的「每格 0.15」（pneumatic）/「每格 0.214」（laser）
是按有水算的，那与实际不符**（有水应是 0.192 / 0.253）。
但如果那张图确实有水源，就是另一回事 —— **这一条请按本节的公式自行核一遍**，
因为所有下游结论都建立在它上面。""",
         """**⇒ 核完了：两边都不是水加成的问题。** REPORT.md 的「每格 0.15」（pneumatic）/
「每格 0.214」（laser）是**漏掉了 `getDrillTime` 里的 `+50 × hardness` 项** ——
本图煤 hardness = 2，应加 100 帧，正确值是 **0.120 / 0.158**。
0.15 / 0.214 既不是无加成值也不是加成值，就是漏项，虚高 25% / 35%。
（真有水才是 0.192 / 0.253，但本图无水。）
**已在 `REPORT.md` 与 `DEBUG-LOG.md` 里改正**；修正后缺口更大，结论方向不变。"""),
    ],
}


def main():
    bad = []
    for rel, rules in EDITS.items():
        p = ROOT / rel
        if not p.exists():
            bad.append(f"{rel}: 文件不存在")
            continue
        text = p.read_text(encoding="utf-8")
        print(f"  {rel}")
        for old, new in rules:
            n = text.count(old)
            if n == 0:
                bad.append(f"{rel}: 未命中 -> {old.splitlines()[0][:50]}")
                print(f"      !! 未命中: {old.splitlines()[0][:50]}")
                continue
            text = text.replace(old, new)
            print(f"      {n} 处  {old.splitlines()[0][:52]}")
        p.write_text(text, encoding="utf-8")
    print()
    if bad:
        print("有问题：")
        for b in bad:
            print("  " + b)
        return 1
    print("数值勘误完成，全部命中")
    return 0


if __name__ == "__main__":
    sys.exit(main())
