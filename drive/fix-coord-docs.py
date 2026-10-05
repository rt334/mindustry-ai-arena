#!/usr/bin/env python3
"""澄清坐标语义 —— 「锚点」这个词被用在了两套坐标系上。

实测证据（dump-cells.py）：
  core-nucleus 覆盖 (287,102)-(291,106)，而 /buildings 报 (289,104)。
  后者是**中心**。

源码依据：
  Tile.getLinkedTiles()  用 x + dx + block.sizeOffset 往外扩
     → tile.x 存的是中心，sizeOffset 才是往左上角的换算
  Building.tileX()       直接 return tile.x
     → 所以 /buildings 报的、以及 /place 收的都是**中心**

两套坐标系：
  对外接口（/buildings、/place、/map）  → 坐标是**中心**
  引擎内部（Edges.getEdges、getLinkedTiles、Tile 索引）→ 从**左上角**起算
  block.sizeOffset = -((size-1)/2) 就是两者之间的换算

ENGINE-NOTES 第 42 行写「多块建筑的锚点是左上角」、第 943 行写「锚点是中心」，
单看矛盾，其实是各说一套。统一措辞。
"""
import pathlib
import sys

D = pathlib.Path(r"C:\dsh\ai-arena\docs")

NOTES_LINE31_OLD = """邻近由「锚点 + `Edges.getEdges(size)` 的偏移集合」决定。"""

NOTES_LINE31_NEW = """邻近由「左上角 + `Edges.getEdges(size)` 的偏移集合」决定。"""

NOTES_LINE42_OLD = """多块建筑的锚点是**左上角**。"""

NOTES_LINE42_NEW = """多块建筑的**内部起点是左上角** —— 本节说的偏移都是相对它。

> **别和接口坐标搞混**。引擎内部有两套坐标系：
>
> | 用在哪 | 坐标 |
> |---|---|
> | `/buildings`、`/place`、`/map` 等**对外接口** | **中心** |
> | `Edges.getEdges`、`getLinkedTiles`、Tile 索引等**引擎内部** | **左上角** |
>
> 换算是 `block.sizeOffset`（`Tile.java:485` 的 `getLinkedTiles` 用的就是它）：
>
> ```
> sizeOffset = -((size - 1) / 2)      // 整数除法
>   2x2 → 0      中心落在左上那一格
>   3x3 → -1     中心在正中
>   5x5 → -2     中心在正中
> ```
>
> 实测：`core-nucleus` 覆盖 `(287,102)-(291,106)`，`/buildings` 报 `(289,104)`。
> **拿 `sizeOffset = 0` 硬套 3x3 及以上的方块会整体偏一格。**"""

API_208_OLD = """| `x` `y` | 锚点坐标 |"""
API_208_NEW = """| `x` `y` | **中心坐标**（多格方块取中心，不是左上角） |"""

API_369_OLD = """| `x` `y` | 目标格（锚点） |"""
API_369_NEW = """| `x` `y` | 目标格（**多格方块传中心**） |"""

RULES = [
    (D / "ENGINE-NOTES.md", [
        (NOTES_LINE31_OLD, NOTES_LINE31_NEW, "第 31 行用词"),
        (NOTES_LINE42_OLD, NOTES_LINE42_NEW, "第 42 行补坐标系对照表"),
    ]),
    (D / "API.md", [
        (API_208_OLD, API_208_NEW, "/buildings 的 x y 说明"),
        (API_369_OLD, API_369_NEW, "/queue 的 x y 说明"),
    ]),
]


def main():
    bad = []
    for path, rules in RULES:
        text = path.read_text(encoding="utf-8")
        print(f"  {path.name}")
        for old, new, label in rules:
            n = text.count(old)
            if n != 1:
                bad.append(f"{path.name}: {n} 次命中 -> {label}")
                print(f"      !! {n} 次  {label}")
                continue
            text = text.replace(old, new)
            print(f"      1 处  {label}")
        path.write_text(text, encoding="utf-8")
    print()
    if bad:
        print("有问题：")
        for b in bad:
            print("  " + b)
        return 1
    print("坐标语义已澄清")
    return 0


if __name__ == "__main__":
    sys.exit(main())
