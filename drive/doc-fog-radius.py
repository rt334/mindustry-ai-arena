#!/usr/bin/env python3
"""把「单位不一定贡献视野」这个事实记进 ENGINE-NOTES。

验证走过一段弯路：把 gamma 开到敌方核心旁 12 格，/buildings 里依然看不到它，
一度以为是对等性缺陷。查下来是引擎的显式设计 —— UnitTypes.java:2610
给 gamma 写了 fogRadius = 0f，而 FogControl.java:289 拿它当门。
"""
import pathlib
import sys

P = pathlib.Path(r"C:\dsh\ai-arena\docs\ENGINE-NOTES.md")

SECTION = """

---

## 二十八、单位不一定贡献视野 —— `fogRadius` 可以是 0

`FogControl` 遍历 `team.units` 时有一道门（`FogControl.java:287-290`）：

```java
for(var unit : team.units){
    int tx = unit.tileX(), ty = unit.tileY(), pos = tx + ty * ww;
    if(unit.type.fogRadius <= 0f) continue;      // ← 视野为 0 的单位直接跳过
    long event = FogEvent.get(tx, ty, (int)unit.type.fogRadius, team.team.id);
```

**`gamma` 就是被这道门挡住的**：`UnitTypes.java:2610` 显式写着 `fogRadius = 0f`。
全代码库有 6 处这样的显式归零（`2508` / `2558` / `2610` / `4384` / `4449` / `4529`）。

注意它和默认值不是一回事：`UnitType.fogRadius` 默认是 **-1f**（`UnitType.java:151`），
而 `init()` 里有一段 `if(fogRadius < 0) fogRadius = max(174, hitSize*2)/8`
（`UnitType.java:989-991`）。**显式写 0 的单位绕过了这个默认推导** ——
它拿不到 21.75 那类值，就是纯 0。

### 实测表现

把 gamma 从己方核心一路开到 team#103 核心旁 **12 格**（对方核心在 `(198,27)`，
单位停在 `(189,20)`），`/buildings` 里**依然看不到那个核心**。
一开始容易误判成对等性缺陷，其实不是。

### 为什么这不是缺陷

- 服务器的 `FogControl` 是**唯一权威**，客户端渲染用的就是它算出的位图，
  所以 AI 与真人看到的一致；
- 这是原版行为，不是本项目引入的偏离。

### 实践含义

- **想侦察远处，把单位开过去是没用的**（除非该单位 `fogRadius > 0`）；
- 视野只能靠**推进建筑**来扩张 —— 核心 61 格，其余建筑各自的 `fogRadius()`；
- 这从另一个角度解释了「远距离扩张必须分段推进」：视野跟着建筑走，
  而建筑又必须建在视野内。
"""


def main():
    t = P.read_text(encoding="utf-8")
    if "二十八、" in t:
        print("已存在第二十八节，跳过")
        return 0
    P.write_text(t.rstrip() + SECTION, encoding="utf-8")
    print("ENGINE-NOTES.md：追加第二十八节")
    return 0


if __name__ == "__main__":
    sys.exit(main())
