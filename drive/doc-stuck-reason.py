#!/usr/bin/env python3
"""把 stuckReason 写进 API.md。"""
import pathlib
import sys

P = pathlib.Path(r"C:\dsh\ai-arena\docs\API.md")

OLD = """| `stuckSeconds` / `hint` | **只在真的卡住时出现**，见下 |"""

NEW = """| `stuckSeconds` / `stuckReason` / `hint` | **只在真的卡住时出现**，见下 |"""

SECTION_OLD = """判据是**进度连续不变、且建造单位自己也不动**，持续超过 3 秒。"""

SECTION_NEW = """判据是**进度连续不变、且建造单位自己也不动**，持续超过 3 秒。

`stuckReason` 说明**为什么卡** —— 四种取值，前三种都对应玩家能直接看到的现象：

| 取值 | 含义 | 你该做什么 |
|---|---|---|
| `missingMaterials` | 核心里的料不够了（`/place` 时够，后来被别的建造消耗掉） | 补产该物品，或 `POST /queue?clear=true` 清掉这条 |
| `tileOccupied` | 那格上已经站着别的建筑 | `/break` 拆掉，或对同格再 `/place` 一次改目标 |
| `builderTooFar` | 单位离工地比 `buildRange` 还远 | 用 `/control?op=order` 把它送过去 |
| `unknown` | 单位自己的状态机卡死 —— **从外部判定不了，如实报 unknown** | 试 `op=order` 推一把 |

`hint` 按 `stuckReason` 给对应的解法。**注意它只有在 `builderTooFar` 时才建议移动命令** ——
被墙挡住的话推过去还会卡回来，那不是解法。

> `missingMaterials` 是那种「`/place` 时说够、之后悄悄变不够」的情况：
> 材料被别的建造消耗了，队列里的计划就一直卡着。以前只报「卡了 12 秒」，
> 看不出是这个原因。"""

RULES = [
    (OLD, NEW, "字段表加 stuckReason"),
    (SECTION_OLD, SECTION_NEW, "stuckReason 的取值说明"),
]


def main():
    text = P.read_text(encoding="utf-8")
    bad = []
    for old, new, label in RULES:
        n = text.count(old)
        if n != 1:
            bad.append(f"{n} 次命中: {label}")
            print(f"  !! {n} 次  {label}")
            continue
        text = text.replace(old, new)
        print(f"  1 处  {label}")
    if bad:
        print("\n有问题，未写盘")
        return 1
    P.write_text(text, encoding="utf-8")
    print("\nAPI.md 已更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
