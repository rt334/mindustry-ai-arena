#!/usr/bin/env python3
"""A6 + 补4 的文档收尾。"""
import pathlib
import sys

P = pathlib.Path(r"C:\dsh\ai-arena\docs\API.md")

STATE_OLD = """### `GET /state`

| 字段 | 含义 |
|---|---|
| `playing` | 是否在对局中 |
| `tick` | 当前 tick |
| `world.w` / `world.h` | 地图尺寸（格） |"""

STATE_NEW = """### `GET /state`

| 字段 | 含义 |
|---|---|
| `playing` | 是否在对局中 |
| `tick` | 当前 tick |
| `world.w` / `world.h` | 地图尺寸（格） |
| `self` / `teams` | 本队与各队概况（核心数、存活） |
| `limits` | **各接口的上限**，见下 |
| `vision` | **视野半径与所有视野源**，见下 |

#### `limits`

```json
{"mapWindowTiles":4096,"batchMax":200,"plansPerUnit":60}
```

| 字段 | 含义 |
|---|---|
| `mapWindowTiles` | `/map` 单次区域查询的格数上限；超了返回 `1004` |
| `batchMax` | `/place` 一次批量形状最多几格 |
| `plansPerUnit` | 单个建造单位的待办计划上限 |

**写在响应里就不用靠反复试探边界了。** 超限时的 400 响应体也会写明具体上限。

#### `vision`

```json
{"maxRadius":61,
 "sources":[{"kind":"building","x":289,"y":104,"radius":61}]}
```

每个视野源的位置与半径，`maxRadius` 是其中最大的。

**这条决定「能看多远」，超出的格子 `/place` 会返回 `1005`（HTTP 403）
并带 `target tile is not visible to team X`。**

> **两个易混的概念**：视野半径是 `fogRadius`（核心 61，与实测边界吻合），
> 而 `UnitType.buildRange` 是**建造范围** —— 两回事，别拿后者当视野用。
>
> **单位可能不贡献视野**：`UnitType.fogRadius` 默认 `-1`，由 `init()` 改写成正值；
> headless 服务器下部分单位类型仍是 `-1`，此时该实体不出现在 `sources` 里。
> 实测本图只有核心贡献（61 格）。"""

FOG_OLD = """| `acceptsFrom` | **能从哪几个邻格收货**（传送带专用），`[[x,y],...]` |
| `sendsTo` | **把货推到哪几格**，`[[x,y],...]` |"""

FOG_NEW = """| `acceptsFrom` | **能从哪几个邻格收货**（传送带专用），`[[x,y],...]` |
| `sendsTo` | **把货推到哪几格**，`[[x,y],...]` |
| `fogRadius` | 该建筑的视野半径；**仅在该值 > 0 时出现**（核心是 61） |"""

UNITS_FOG_OLD = """| `buildingAt` | **这个建造单位当前在建哪一格**，见下 |"""

UNITS_FOG_NEW = """| `buildingAt` | **这个建造单位当前在建哪一格**，见下 |
| `fogRadius` | 视野半径；**仅在该值 > 0 时出现**（headless 下单位常为 -1，见 `/state` 的 `vision`） |"""

RULES = [
    (STATE_OLD, STATE_NEW, "/state 的 limits 与 vision"),
    (FOG_OLD, FOG_NEW, "/buildings 的 fogRadius"),
    (UNITS_FOG_OLD, UNITS_FOG_NEW, "/units 的 fogRadius"),
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
