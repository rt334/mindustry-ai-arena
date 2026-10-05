#!/usr/bin/env python3
"""把「地图每局重随」这条教训写进文档，替换掉写死坐标的布局表。"""
import pathlib
import sys

P = pathlib.Path(r"C:\dsh\ai-arena\docs\PRODUCTION.md")

OLD_START = "## 一、当前布局"
OLD_END = "## 二、实测速率"

NEW = """## 一、⚠ 坐标不能写死 —— 地图每局重随

**这是本项目最贵的一个教训。**

前几版把某一局探查到的坐标写死进脚本（煤钻 (290,100)、沙钻 (289,108)、
冶炼厂 (292,102)…），下一局 `-Map veins` 重新随机后全线崩：

```
煤钻A (290,100)   1009: placement invalid        ← 那格没矿了
冶炼厂 (292,102)  1008: footprint ... blocked    ← 被别的东西占了
沙带 6格          1005: batch rejected accepted=0
```

而**错误信息完全不提「地图换了」**，只会让你以为是这一格的局部问题。

### 正确做法

坐标一律**开跑前现查**。`drive/production.py` 提供原语：

| 方法 | 作用 |
|---|---|
| `World(agent, R)` | 拉核心周边地图，自动等快照就绪 |
| `find_site(kind, size)` | 离核心最近的、size×size 全空且有该矿的点位（按矿格数优先） |
| `find_site_near_core(size)` | 贴核心的空位（冶炼厂/压机这类要直接入库的） |
| `route(a, b)` | BFS 布一条带子路径，自己绕开建筑与已计划格 |
| `lay(pts, end_rot=)` | 逐格下单并算朝向；**末格朝向必须显式给对** |
| `ready(coords)` | 轮询等建成（判据是状态，不是时长） |

`drive/bootstrap.py` 是基于它的硅线引导：从任意局面建到产出硅，零写死坐标。
在一张完全不同的图上实测通过：

```
核心 (289,104)  406 铜 / 460 铅
  冶炼厂 (285,104)     ← 自动找到贴核心的位
  煤钻A (264,111) 矿4格 → BFS 25 格带子 → 冶炼厂  ✓
  沙钻 (289,110) 矿4格  →  8 格带子 → 冶炼厂      ✓
  发电机 (284,104)     ← 贴冶炼厂，自动连电力线
  煤钻B (289,90)  矿1格 → 17 格带子 → 发电机      ✓
冶炼厂 power=1.0 eff=1.0   硅 3 ✓
```

**顺序仍不可换**：煤钻 → 燃煤发电机 → 硅冶炼厂。
（`solar-panel` 要 8 硅而硅要电，先放它就是个死循环。）

**为什么末格朝向要显式给**：`route()` 只知道怎么走到目标旁边，
不知道料该往哪个方向进。末端格子如果朝向错了，整条带子看着通、实际不送料。

"""


def main():
    t = P.read_text(encoding="utf-8")
    a = t.find(OLD_START)
    b = t.find(OLD_END)
    if a < 0 or b < 0 or b <= a:
        print(f"!! 定位失败 a={a} b={b}")
        return 1
    P.write_text(t[:a] + NEW + t[b:], encoding="utf-8")
    print("PRODUCTION.md §一 已换成「坐标不能写死」")
    return 0


if __name__ == "__main__":
    sys.exit(main())
