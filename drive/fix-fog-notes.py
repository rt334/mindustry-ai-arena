#!/usr/bin/env python3
"""更正 ENGINE-NOTES 第二十八节。

上一版结论写错了：「单位不贡献视野」是过度概括 —— 我只测了 gamma，
而它恰好是 6 个被显式归零的单位之一。实际 56 个单位里 50 个都有视野，
其中 13 个还能建造。

这一节整个替换掉。
"""
import pathlib
import sys

P = pathlib.Path(r"C:\dsh\ai-arena\docs\ENGINE-NOTES.md")

NEW_SECTION = """## 二十八、单位视野：只有 6 个快速飞行单位被显式设为 0

`FogControl` 遍历 `team.units` 时有一道门（`FogControl.java:287-290`）：

```java
for(var unit : team.units){
    int tx = unit.tileX(), ty = unit.tileY(), pos = tx + ty * ww;
    if(unit.type.fogRadius <= 0f) continue;      // 视野为 0 的单位直接跳过
    long event = FogEvent.get(tx, ty, (int)unit.type.fogRadius, team.team.id);
```

**56 个单位里只有 6 个被它挡住** —— `UnitTypes.java` 里显式写了 `fogRadius = 0f`：

| 单位 | buildSpeed | speed | 飞行 |
|---|---|---|---|
| `alpha` | 0.5 | 3.0 | ✓ |
| `beta` | 0.75 | 3.3 | ✓ |
| `gamma` | 1.0 | 3.55 | ✓ |
| `emanate` | 1.5 | 7.5 | ✓ |
| `evoke` | 1.2 | 5.6 | ✓ |
| `incite` | 1.4 | 7.0 | ✓ |

**共同点：全是飞行的快速建造 / 搬运单位**（speed 3.0~7.5，远高于任何地面单位）。
这是**速度换视野**的取舍，不是缺陷 —— 它们负责跑得快、送得多，侦察不归它们管。

其余 **50 个都有视野**，走 `init()` 的默认推导（`UnitType.java:989-991`）：

```java
if(fogRadius < 0){
    fogRadius = Math.max(58f * 3f, hitSize * 2f) / 8f;   // = 21.75
}
```

个别更高：`anthicus` 40、`avert` / `obviate` 25。

### 能建造、又有视野的（13 个）

| 单位 | fogRadius | buildSpeed | speed | 飞行 |
|---|---|---|---|---|
| `oct` | 21.75 | 4.0 | 0.8 | ✓ |
| `navanax` | 21.75 | 3.5 | 0.65 |  |
| `vela` | 21.75 | 3.0 | 0.44 |  |
| `aegires` | 21.75 | 3.0 | 0.7 |  |
| `mega` | 21.75 | 2.6 | 2.5 | ✓ |
| `quad` | 21.75 | 2.5 | 1.2 | ✓ |
| `oxynoe` / `cyerce` | 21.75 | 2.0 | ~0.85 |  |
| `retusa` | 21.75 | 1.5 | 0.9 |  |
| `quasar` | 21.75 | 1.1 | 0.5 |  |
| `pulsar` | 21.75 | 0.5 | 0.7 |  |
| `poly` | 21.75 | 0.4 | 2.6 | ✓ |
| `nova` | 21.75 | 0.3 | 0.55 |  |

**`poly` 和 `mega` 尤其值得注意**：飞行、速度 2.5+、有 21.75 格视野，还能建造。

### 实践含义

- **「派单位去侦察」是可行的，前提是别用那 6 个无视野的**；
- AI 当前默认拿到的 `gamma` 恰好属于那 6 个 —— 所以会有
  「把 gamma 开到敌方核心旁 12 格，`/buildings` 里仍看不见它」的实测结果。
  **这不是对等性问题**（服务器的 `FogControl` 是唯一权威，AI 与真人一致），
  而是选错了单位；
- **要侦察就生产 `poly` / `mega`**：既有视野又能建造，一举两得；
- 视野也能靠推进建筑扩张（核心 61 格，其余建筑各自的 `fogRadius()`），
  两条路可以并用。

> **本文档的更正记录**：本节初版写成「单位不贡献视野，想侦察只能靠建筑」——
> 那是拿 gamma 一种单位做的过度概括。实测 6/56 这个比例后改写。
"""


def main():
    t = P.read_text(encoding="utf-8")
    i = t.rfind("## 二十八、")
    if i < 0:
        # 没有旧节，直接追加
        P.write_text(t.rstrip() + "\n\n---\n\n" + NEW_SECTION, encoding="utf-8")
        print("ENGINE-NOTES.md：追加第二十八节")
        return 0

    head = t[:i].rstrip()
    P.write_text(head + "\n\n---\n\n" + NEW_SECTION, encoding="utf-8")
    print("ENGINE-NOTES.md：第二十八节已更正")
    return 0


if __name__ == "__main__":
    sys.exit(main())
