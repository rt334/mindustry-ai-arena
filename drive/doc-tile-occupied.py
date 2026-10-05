#!/usr/bin/env python3
"""记录 tileOccupied 的结论：单人局面下达不到，需要敌方抢建。"""
import pathlib
import sys

T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")
E = pathlib.Path(r"C:\dsh\ai-arena\docs\ENGINE-NOTES.md")

T_OLD_LINE_START = "| `stuckReason` 的四种取值 |"
T_NEW = ("| `stuckReason` 的四种取值 | **三种已实测，`tileOccupied` 判定为「需敌方抢建才可达」**。"
         "`missingMaterials` —— 第 2 轮实测；`builderTooFar` —— 第 29 轮实测（18 条、带像素值）；"
         "`unknown` —— 从没单独测过（旧记录写错）；"
         "**`tileOccupied` 试过两种绕法都不成**：用「先排 2x2 计划占住目标格、再在目标格排 1x1」"
         "构造时序，结果第 2 步直接回 `1008 footprint ... blocked` —— "
         "**`validPlace` 会把已排的**计划**也算进占用**，不只算实体建筑。"
         "所以己方无法自己造出这个状态；能发生的前提是**敌方在我方已排计划的格上先建成**"
         "（敌方校验的是他们自己的计划，我方计划对他们不算占用）。"
         "判定：**真实对局里可达，单人局面下不可达**，不作为待办保留。复现尝试见 "
         "`drive/verify-tile-occupied.py`。 |")

E_SECTION = """

## 三十一、`validPlace` 把**计划**也算进占用

实测：先在 (273,84) 排一个 `graphite-press`（2x2）的计划，紧接着在它的脚印内
(274,85) 排一个 1x1 conveyor：

```
1008 footprint of conveyor (1x1) at (274,85) is blocked by the tile at (274,85)
```

**那格还没有任何实体建筑，只有刚排下的计划。** 所以 `validPlace` 的占用判定
包含**同队的待建计划**，不只是建筑与地形。

两个直接推论：

1. **己方造不出 `tileOccupied`。** 想在已排计划的格上再排东西，第二步就会被 1008 拦住 ——
   所以「计划排下之后那格才被占掉」这件事，己方自己做不到。
2. **同格重复下单是 `transfer` 而不是报错**（见 `/place` 失败码统计）：
   对已有计划的格再下单，是**改派**那个计划，不是新建一个冲突的计划 ——
   这与上面那条是一体的：接口在提交层就把重叠拦住了。

**`tileOccupied` 因此只在一种情况下出现**：敌方在我方已排计划的格上先建成了
（敌方校验的是**他们自己的**计划，我方计划对他们不算占用）。
真实对局里可达，单人试验局面下不可达。
"""


def main():
    t = T.read_text(encoding="utf-8")
    lines = t.splitlines()
    hit = None
    for i, ln in enumerate(lines):
        if ln.startswith(T_OLD_LINE_START):
            hit = i
            break
    if hit is None:
        print("  !! 找不到 stuckReason 汇总行")
        return 1
    lines[hit] = T_NEW
    T.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("  ✓ §三 汇总行已更新")

    e = E.read_text(encoding="utf-8")
    if "## 三十一、" in e:
        print("  · ENGINE-NOTES 已有该节")
    else:
        E.write_text(e.rstrip() + "\n" + E_SECTION, encoding="utf-8")
        print("  ✓ ENGINE-NOTES 追加 §三十一")
    return 0


if __name__ == "__main__":
    sys.exit(main())
