#!/usr/bin/env python3
"""§7.8 再补条目 5 / 8 / 9 的甄别。"""
import pathlib
import sys

T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")

ANCHOR = "| 6 | `/map` 窗口上限 400 无任何文字 |"

NEW_ROWS = """| 5 | 没有增量查询接口 | **确实没做**（`grep` 增量/since 类端点，0 命中）。每步改动都要重拉全量 `/buildings`（后期 250+ 条）对比。 |
| 8 | `/stalls` / `/diag` 不区分「上游来货不足」与「下游拒收」 | **已实现，而且比复盘要的更细**。`StallWatch.causeOf` 给的是 `starved`（上游没送料，**往上游查**）/ `outputBlocked`（自己满仓、出料侧不收，**往下游查**）/ `outputRefused`（刚堵上，还没满仓）/ `underpowered` / `powerUnconnected` —— 方向都写在注释里了。 |
| 9 | `place` 出视野返回 HTTP 403 而非 JSON | **与现有代码矛盾，待实机确认**。`Actor.java:72/277/309` 三处都返回带完整消息的 `1005 \"target tile is not visible to team X\"`，经 `statusFor` 映射成 HTTP 403 **但 body 是 JSON**。复盘作者现场看到的是无 body 的 `HTTP Error 403: Forbidden` —— 可能是旧版本，也可能是另一条走到 `respond(ex, 403, …)` 之前的路径。**别照着复盘直接改**，先实机看一眼 body。 |
| 6 | `/map` 窗口上限 400 无任何文字 |"""


def main():
    t = T.read_text(encoding="utf-8")
    if t.count(ANCHOR) != 1:
        print(f"  !! 锚点 {t.count(ANCHOR)} 次")
        return 1
    t = t.replace(ANCHOR, NEW_ROWS, 1)

    # 更新「尚未核对」那句
    old_note = ("> 条目 5（增量查询）、7（`/place` 的 config）、8（`/stalls` 区分停机原因）、\n"
                "> 9（403 无 body / 视野半径）、10（队列停滞处理）**尚未核对**，")
    new_note = ("> 条目 7（`/place` 的 config）、10（队列停滞处理）**尚未核对**，")
    if t.count(old_note) == 1:
        t = t.replace(old_note, new_note, 1)
        print("  ✓ 「尚未核对」范围已收窄到 7 / 10")
    else:
        print(f"  · 「尚未核对」句未改（命中 {t.count(old_note)}）")

    # 把「只核了八条」改成十一条
    t = t.replace("> **本次只核了条目 1 / 2 / 3 / 4 / 6 / 13 / 14 / 16 八条。**",
                  "> **本次核了条目 1 / 2 / 3 / 4 / 5 / 6 / 8 / 9 / 13 / 14 / 16 十一条"
                  "（其中早已完成或已修的：1 / 3 / 4 / 6 / 8 / 13 / 14）。**", 1)

    T.write_text(t, encoding="utf-8")
    print("  ✓ §7.8 补入条目 5 / 8 / 9")
    return 0


if __name__ == "__main__":
    sys.exit(main())
