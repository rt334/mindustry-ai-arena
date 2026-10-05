#!/usr/bin/env python3
"""TODO §四 的 /place 失败码统计行。"""
import pathlib
import sys

T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")

OLD = "| **`/place` 的失败码没有统计** | 这一轮造了多少次 `1008` / `1009`、哪些是误报，没有记录 |"
NEW = ("| **`/place` 的失败码没有统计** | **已做（一轮样本）**：`drive/collect-place-failures.py` "
       "造出各类失败并统计，写进 [place-failure-stats.md](place-failure-stats.md)。"
       "三个比数字更重要的发现：**`rot` 越界被静默环绕**（`9→1`、`-1→3`、`4→0`，全部 `code=0`）；"
       "**材料不足下单时不拒**，排队后由 `stuckReason` 暴露；"
       "**同格重复放置是 `transfer` 而非 1008**（1008 只在有**实体建筑**时出现）。"
       "**局限**：每类只跑 1–3 次，是「各类报什么」不是频率分布。 |")


def main():
    t = T.read_text(encoding="utf-8")
    n = t.count(OLD)
    if n != 1:
        print(f"  !! 锚点 {n} 次")
        return 1
    T.write_text(t.replace(OLD, NEW, 1), encoding="utf-8")
    print("  ✓ TODO §四 已更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
