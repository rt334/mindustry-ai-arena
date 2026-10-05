#!/usr/bin/env python3
"""§7.8 再补两条甄别：条目 3、4 也已实现。

这次**读了内容**才下的结论（上回凭 grep 命中数猜，两条判错）。
"""
import pathlib
import sys

T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")

OLD = "| 6 | `/map` 窗口上限 400 无任何文字 |"

NEW_ROWS = """| 3 | `/queue` 只给数量不给坐标与进度 | **已实现**。`Operations.java:447-483` 每个计划带 `x` / `y` / `block` / `breaking` / `constructing` / `progress` / `stuckSeconds` / `stuckReason` / `hint` —— 坐标、进度、卡住原因都有。复盘那条是旧状态。 |
| 4 | `/units` 缺「当前在建哪个方块」 | **已实现**。`HttpApi.java:4239` 给 `buildingAt: {x, y, progress, block}`，正是复盘要的那四个字段。 |
| 6 | `/map` 窗口上限 400 无任何文字 |"""


def main():
    t = T.read_text(encoding="utf-8")
    n = t.count(OLD)
    if n != 1:
        print(f"  !! 锚点 {n} 次")
        return 1
    t = t.replace(OLD, NEW_ROWS, 1)

    # 顺带把「未核」的范围说清，别让人以为剩下的都核过了
    tail_anchor = "### 7.9 补进 §六 的边界判定"
    note = ("> **本次只核了条目 1 / 2 / 3 / 4 / 6 / 13 / 14 / 16 八条。**\n"
            "> 条目 5（增量查询）、7（`/place` 的 config）、8（`/stalls` 区分停机原因）、\n"
            "> 9（403 无 body / 视野半径）、10（队列停滞处理）**尚未核对**，\n"
            "> 动手前请先按上面的方法读一遍内容 —— 别凭 `grep` 命中数下结论。\n\n")
    if "本次只核了条目" not in t:
        t = t.replace(tail_anchor, note + tail_anchor, 1)
        print("  ✓ 已注明哪些条目尚未核对")

    T.write_text(t, encoding="utf-8")
    print("  ✓ 追加条目 3 / 4 的甄别")
    return 0


if __name__ == "__main__":
    sys.exit(main())
