#!/usr/bin/env python3
"""修 §三 里那条过时的 stuckReason 汇总行。

它写着「只有 unknown 是实测的」，但实际已有三种验证过：
  missingMaterials  第 2 轮（shock-mine needs 12 silicon, core has 0）
  builderTooFar     本轮（18 条计划，带像素值）
  unknown           —— 这条其实**没有**单独实测过，是旧记录写错了
而 tileOccupied 仍未验。

这正是本 TODO 自己的老毛病：状态没回填，旧行留在原地与新的打架。
"""
import pathlib
import sys

T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")


def main():
    lines = T.read_text(encoding="utf-8").splitlines()
    idx = None
    for i, ln in enumerate(lines):
        if "stuckReason` 的四种取值" in ln or "stuckReason 的四种取值" in ln:
            idx = i
            break
    if idx is None:
        print("  !! 找不到该行")
        return 1
    print(f"  原行 L{idx+1}: {lines[idx][:150]}")
    lines[idx] = ("| `stuckReason` 的四种取值 | **三种已实测，一种未验**。"
                  "`missingMaterials` —— 第 2 轮实测（`shock-mine needs 12 silicon, core has 0`）；"
                  "`builderTooFar` —— 本轮实测（18 条计划，带像素值与 `buildRange 220`）；"
                  "`unknown` —— **从没单独测过**（旧记录写成「只有它是实测的」是错的）；"
                  "`tileOccupied` —— **仍未验**，要构造「下完单之后该格才被别的建筑占掉」的时序。 |")
    T.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("  ✓ 已改")
    return 0


if __name__ == "__main__":
    sys.exit(main())
