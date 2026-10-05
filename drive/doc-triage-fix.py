#!/usr/bin/env python3
"""修正 §7.8 自己的两处误判。

教训就在眼前：我刚写下「甄别」这张表，两条判决就是错的 ——
因为我是**凭 grep 命中数**猜的，没去读那段文字。

  · 条目14 我判「待搬」→ 实际 ENGINE-NOTES.md §三 早有完整公式
    （getDrillTime / lastDrillSpeed / 液体加成 / dominantItem 语义 / 硬度表）
  · 条目16 我判「待改」→ PRODUCTION.md 里「矿脉密度的硬上限」那句
    在早先重编号时就删掉了，grep 命中 0

结论：**判「已实现」要读内容，不能看命中数。** hit count 只能证伪
（命中 0 就真没有），不能证真。
"""
import pathlib
import sys

T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")

# 行级替换：把两条误判改成正确结论
FIXES = [
    (
        "| 14 | 矿机产出公式没进任何文档 | **部分**：已进 `PRODUCTION.md` §四，但没进 `ENGINE-NOTES.md`（引擎层事实该在的地方）。**待搬**。 |",
        "| 14 | 矿机产出公式没进任何文档 | **已完成**。`ENGINE-NOTES.md` §三「矿机」就有：`getDrillTime` / `lastDrillSpeed` / `hardnessDrillMultiplier = 50`、液体加成 `liquidBoostIntensity = 1.6`、`dominantItem` 取 footprint 内**数量最多**的矿种、硬度表。复盘那条是旧状态。 |",
    ),
    (
        "| 16 | 「5/s 不可达」措辞该改 | **未做**。`PRODUCTION.md` 仍写着「矿脉密度的硬上限」，应改为「近处矿量 + 干线成本」的**工程约束**。**待改**。 |",
        "| 16 | 「5/s 不可达」措辞该改 | **部分**：`PRODUCTION.md` 里「矿脉密度的硬上限」那句已在早先重编号时删掉，但 §五 仍以「可盖矿格数」给出上限（那就是**近处**分析）。复盘点的是：把远矿接回来要 60+ 格干线，而视野只有 61 格、只有**一个**建造单位、还要排队 —— 受支配的是**工程上限**，措辞该往这个方向收。**待改**。 |",
    ),
]

NOTE = """
> **关于这张表自身的教训**：初版里两条判决是错的（条目 14、16），
> 因为我是凭 `grep` 命中数猜的，没读那段文字。
> **命中 0 能证伪，命中 ≥1 不能证真** —— 判「已实现」必须读内容。
"""


def main():
    t = T.read_text(encoding="utf-8")
    ok = True
    for old, new in FIXES:
        n = t.count(old)
        if n != 1:
            print(f"  !! 命中 {n} 次：{old[:40]}…")
            ok = False
            continue
        t = t.replace(old, new, 1)
        print(f"  ✓ 已改：{old[:44]}…")
    if not ok:
        print("未写盘")
        return 1
    if "关于这张表自身的教训" not in t:
        t = t.replace("### 7.9 补进 §六 的边界判定",
                      NOTE.strip() + "\n\n### 7.9 补进 §六 的边界判定", 1)
        print("  ✓ 已加甄别表自身的教训")
    T.write_text(t, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
