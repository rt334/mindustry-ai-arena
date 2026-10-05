#!/usr/bin/env python3
"""把产线的实际进展写进 TODO.md。"""
import pathlib
import sys

T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")

OLD = "**「铜/铅 +5/s，石墨/硅/钛尽量高」的产线，一行没做。**"

NEW = """**「铜/铅 +5/s，石墨/硅/钛尽量高」的产线 —— 已开工，未达标。**

**当前实测**（细节与布局见 `PRODUCTION.md`）：

| 资源 | 速率 | 来源 |
|---|---|---|
| 铜 | +0.32 ~ +0.40 /s | 1 台机械钻 |
| 硅 | +0.28 ~ +0.36 /s | 1 台冶炼厂 |
| 煤 | +0.32 /s（净） | 2 台钻机 |
| 铅 / 钛 / 石墨 | 0 | 未建 |

单台机械钻约 **0.35 /s**，所以 +5/s 需要每种约 **14 台**——得靠「长收集带 +
沿线一排钻机」规模化，不能一台一台铺线。

**已建成**：煤钻 ×2、沙钻、铜钻、硅冶炼厂、燃煤发电机、铜带/沙带/煤带。
**已知唯一「建了但不工作」的**：石墨压机 (285,103) —— 煤源没接通。
**已排掉的坑**：`solar-panel` 要 8 硅而硅要电，是个死循环；破局靠
`combustion-generator`（不含硅）烧煤供电。"""


def main():
    t = T.read_text(encoding="utf-8")
    n = t.count(OLD)
    if n != 1:
        print(f"!! 锚点 {n} 次（期望 1）")
        return 1
    T.write_text(t.replace(OLD, NEW), encoding="utf-8")
    print("TODO.md §一 已更新为实测进展")
    return 0


if __name__ == "__main__":
    sys.exit(main())
