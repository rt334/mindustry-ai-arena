#!/usr/bin/env python3
"""§7.8 补最后两条（7 / 10），并给出总账。"""
import pathlib
import sys

T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")

ANCHOR = "| 5 | 没有增量查询接口 |"

NEW_ROWS = """| 7 | `/place` 的 `config` 参数无效 | **已修，而且代码里记着这条教训**。`Actor.java:134-141` 专门把字符串 config 解析成引擎对象，注释写明：`BuildingComp.configured()` 按 `value.getClass()` 查 `block.configurations`，**直接传 String 一律匹配不上，配置会静默失效**（方块建出来了，config 是空的）。正是从复盘那次踩坑学到并修掉的。（同一行的「sorter `rotation` 回读恒 0」是条目 11，仍待实机确认。） |
| 10 | 队列停滞的处理手段与坐标语义没文档化 | **已文档化**。`API.md` L507 写明「`/control?op=order` 收**格坐标**，实测 `plans` 一次从 56 降到 1，沿线方块真的建成」；L471/L472 的 `stuckReason` 表把 `builderTooFar` 与 `unknown` 两种都指向它；L843 有一段完整流程。 |
| 5 | 没有增量查询接口 |"""

TALLY = """
### 7.8.1 总账

**核了 13 条**（1–10 里除 11、12 之外的十条，加 13 / 14 / 16 / 18）。

其中 **九条早已完成或已修**：`1 / 3 / 4 / 6 / 7 / 8 / 10 / 13 / 14`。

**真正还没做的只有两条**：

| # | 项 | 为什么没做 |
|---|---|---|
| 2 | 钻机「实际往哪几格推货」的**独立字段** | 部分已实现（塞在 `sendsTo` 里），缺的是「实际生效的 rot」与 footprint 锚点差异的解释 |
| 5 | **增量查询接口** | 真缺口，没有 `since` 类端点 |

外加三条**只能实机确认**的（11 的 sorter rotation 回读、9 的 403 body、15 的机制文档化）。

**这说明什么**：§七 这 25 条是**把复盘笔记当待办收进来的**，而复盘记的是当时状态。
收进来时没有逐条对照代码，于是九成条目在写下时就已经过时了。
条目 25 自己就批评过这件事（「坑应尽早变成接口该怎么改，而不是留给自己反复踩」）——
这批笔记后来又作为待办被读了一遍，是同一问题的另一半。

**往后收复盘内容时的做法**：先跑一遍对照，把「已完成」标出来再收，
否则清单会一次比一次虚。
"""


def main():
    t = T.read_text(encoding="utf-8")
    if t.count(ANCHOR) != 1:
        print(f"  !! 锚点 {t.count(ANCHOR)} 次")
        return 1
    t = t.replace(ANCHOR, NEW_ROWS, 1)

    tail = "### 7.9 补进 §六 的边界判定"
    if "### 7.8.1 总账" not in t:
        t = t.replace(tail, TALLY.strip() + "\n\n" + tail, 1)
        print("  ✓ 已加 §7.8.1 总账")

    old = ("> 条目 7（`/place` 的 config）、10（队列停滞处理）**尚未核对**，\n"
           "> 动手前请先按上面的方法读一遍内容 —— 别凭 `grep` 命中数下结论。")
    new = "> 条目 11、12（待验类）**未核**。\n> 动手前请先按上面的方法读一遍内容 —— 别凭 `grep` 命中数下结论。"
    if t.count(old) == 1:
        t = t.replace(old, new, 1)
        print("  ✓ 「尚未核对」已更新")

    T.write_text(t, encoding="utf-8")
    print("  ✓ §7.8 补入条目 7 / 10")
    return 0


if __name__ == "__main__":
    sys.exit(main())
