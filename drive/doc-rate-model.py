#!/usr/bin/env python3
"""用引擎公式替换掉上一版基于猜测的速率模型。"""
import pathlib
import sys

P = pathlib.Path(r"C:\dsh\ai-arena\docs\PRODUCTION.md")

OLD = "## 五、还没定下来的问题：矿格数影响产率吗"

NEW = """## 五、产率模型（已从引擎源码确认，并实测复核）

**公式**（`Mindustry-src/core/src/mindustry/world/blocks/production/Drill.java`）：

```java
// Drill.java:303 —— 注意 dominantItems 是直接乘数
lastDrillSpeed = (speed * dominantItems * warmup) / delay;
// Drill.java:171
delay = (drillTime + hardnessDrillMultiplier * item.hardness) / drillMultiplier;
// hardnessDrillMultiplier = 50
// Drill.java:149 放置预览里直接印了这个式子
text = 60f / getDrillTime(item) * returnCount   // 个/秒
```

即 **每秒产率 = 60 × 矿格数 ÷ (drillTime + 50 × 硬度) × warmup**。

`dominantItems` 是钻机脚印内的主矿格数，**上限 size×size**。所以产率正比于
脚下了几格矿 —— 不是「有矿就行」。上一版用「前后产率差」测这个，
结果被 `Actor.place` 的扣料污染（铜产率一度测成 −0.400/s），白跑一轮。

### 各种钻机

| 钻机 | 占地 | tier | drillTime | 成本 |
|---|---|---|---|---|
| mechanical-drill | 2×2 | 2 | **600** | copper 12 |
| pneumatic-drill | 2×2 | 3 | **400** | copper 18 + graphite 10 |
| laser-drill | 3×3 | 4 | **280** | copper 35 + graphite 30 + silicon 30 + titanium 20 |
| blast-drill | 4×4 | 5 | **280** | copper 65 + silicon 60 + titanium 50 + thorium 75 |

`tier` 是能挖的最高硬度。**mechanical 挖不了钛（tier2 < 硬度3）；
pneumatic 挖不了钍（tier3 < 硬度4）。**

### 实测复核

在 4 格煤矿上放一台机械钻（无输出，自然填满）：

```
矿格=4  硬度=2  warmup≈0.93
引擎公式   60 × 4 / (600 + 50×2) = 0.343 /s
接口字段   itemsPerSecond        = 0.32
比值 0.933  ← 正好是当时的 warmup
```

### ⚠ `lastDrillSpeed` 是**每 tick**，不是每秒

引擎 UI 要 `lastDrillSpeed * 60 * timeScale` 才是每秒（`Drill.java:118`）。
它只有两位小数，`0.01` 可能对应真实 `0.0062` —— 我照着「个/秒」写注释，
结果看到 `0.01` 以为 100 秒才出一个矿，和实测的 0.35/s 对不上，白查一轮。

**已修**：`/drill` 现在同时给出 `itemsPerSecond`（在 Java 里先 ×60 再序列化，
绕开两位小数的舍入）与 `dominantItems`。**读 `itemsPerSecond`。**

## 六、可达性（用正确的模型重算）"""


def main():
    t = P.read_text(encoding="utf-8")
    if t.count(OLD) != 1:
        print(f"!! 锚点 {t.count(OLD)} 次")
        return 1
    t = t.replace(OLD, NEW, 1)

    # 替换掉基于「钻机位 × 0.35」的旧表
    old_tbl_start = "| 矿 | 矿格 | 连通块 | 可放钻机位（含矿≥1） | 按单台 ~0.35/s 外推上限 |"
    i = t.find(old_tbl_start)
    if i < 0:
        print("!! 找不到旧表")
        return 1
    j = t.find("\n\n", i)
    new_tbl = """| 矿 | 矿格 | mechanical | pneumatic | laser | blast |
|---|---|---|---|---|---|
| 铜 | 340 | 113格 / 10.4/s | 113格 / 15.1/s | **95格 / 17.3/s** | 88格 / 16.0/s |
| 铅 | 136 | 41格 / 3.5/s | 41格 / 4.9/s | 31格 / **4.9/s** | 33格 / **5.2/s** |
| 钛 | 90 | — 挖不了 | 18格 / 2.0/s | 16格 / **2.2/s** | 14格 / 2.0/s |
| 钍 | 98 | — 挖不了 | — 挖不了 | 22格 / 2.8/s | 22格 / 2.8/s |
| 煤 | 137 | 13格 / 1.1/s | 13格 / 1.6/s | 11格 / 1.7/s | 8格 / 1.3/s |

**「可盖矿格数」是贪心选位算出来的**（枚举所有 size×size 全为空地的候选，
按盖住的矿格数降序放，跳过与已放重叠的）。关键在于：**决定上限的不是
「有几个钻机位」，而是「能盖住多少矿格」**——因为每个矿格只能被一台钻机盖，
而产率是矿格数的线性倍数。"""
    t = t[:i] + new_tbl + t[j:]
    P.write_text(t, encoding="utf-8")
    print("PRODUCTION.md：速率模型已换成引擎公式 + 覆盖优化表")
    return 0


if __name__ == "__main__":
    sys.exit(main())
