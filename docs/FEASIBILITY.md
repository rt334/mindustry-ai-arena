# 目标可行性评估

**目标**：铜、铅、硅、钛、石墨各 `+5/s`。

**结论：可行。余量充足。**

```
资源       矿格   连通块  不重叠台   总产出/s    目标/s   余量
copper    2360    131     385      142.06      5.0    28×
lead      1306     70     210       77.49      5.0    15×
titanium   498     38      74       32.26      5.0     6×
sand     26654    345    5171     2068.40     10.0   207×
coal      1112     50      56       79.52     15.0     5.3×
```

硅与石墨的煤需求合计 15/s，煤本体上限 79.52/s —— **不构成约束**。

---

## 勘误：本文件前三版全错

| 版本 | 结论 | 错在哪 |
|---|---|---|
| v1 `24fba8c` | 不可行（煤 9.79/s < 需求 15/s） | 漏了 `liquidBoostIntensity` |
| v2 | 可行（9.79 × 1.6 = 15.7/s） | 没验证本图有没有水 |
| v3 `54e0281` | 不可行（无水 ⇒ 回到 9.79/s） | **9.79 这个数本身就是错的** |
| **v4（本文件）** | **可行（79.52/s）** | —— |

**v3 的致命处**：它推翻 v2 时只质疑了「水加成能不能用」，
**没有质疑那个 9.79 本身** —— 而 9.79 是从 `plan-ore.py` 抄来的，我从没验算过。

---

## 一、错在哪：抄了一个没验算的数

`plan-ore.py` 报：

```
laser-drill  候选 117   可选(不重叠) 12   总产出 9.79/s
```

独立复算（自己抓全图、自己分连通块、自己贪心排布）：

```
laser-drill  候选 278   不重叠 56        总产出 79.52/s
```

**候选集都不是同一个（117 vs 278）** —— 差 8 倍的上限源于此。

自算过程可逐步审：

1. 全图 28 块分片查询**全部成功**，共 70000 格
2. 煤 **1112 格**，按 4-邻接分成 **50 个连通块**，最大块 100 格（`x=260..271 y=25..41`）
3. 每块内枚举「3×3 全为煤」的锚点 → **278 个候选**
4. 按 `cells & used` 贪心去重（footprint 真正共享格子才跳过，不留缝）→ **56 台**
5. 56 × 9 = 504 格，占 1112 的 45% —— 对块状分布合理

**⇒ 79.52/s 可信。**

---

## 二、配方与矿机参数（源码 `Blocks.java` / `Drill.java`）

```java
siliconSmelter:  craftTime 40f;  consumeItems(coal 1, sand 2);  consumePower(0.50f);
graphitePress:   craftTime 90f;  consumeItem(coal 2);

Drill.java:301   speed = Mathf.lerp(1f, liquidBoostIntensity, optionalEfficiency) * efficiency;
Drill.java:38    liquidBoostIntensity = 1.6f;
getDrillTime = (drillTime + 50 × hardness) / drillMultipliers
单台产出     = (覆盖格数 / getDrillTime) × 60 × speed
```

| 矿机 | tier | drillTime | size | 水加成 |
|---|---|---|---|---|
| `mechanical-drill` | 2 | 600 | 2×2 | 有 |
| `pneumatic-drill` | 3 | 400 | 2×2 | 有 |
| `laser-drill` | 4 | 280 | 3×3 | 有 |

**三种矿机都带 `.consumeLiquid(Liquids.water, …).boost()`**
（`mechanical 0.05` / `pneumatic 3.5/60` / `laser 0.08`），`liquidBoostIntensity = 1.6`。
早先这张表把 mechanical 标成「无」是错的，**但对下面的结论无影响**。

**本图没有天然液体地块**（全图 70000 格只有 `darksand / shale / moss / spore-moss / core-zone`），
但 **`speed = 1` 这个推论是错的** —— 见下面的更正。

> ### ⚠ 更正（2026-10-06）：有 1.6 倍，而且拿得到
>
> **「图上没有水」≠「拿不到水」。** 水是**可以被生产**的：
> `water-extractor`（抽水机）在**干地上**就能产水（`SolidPump.baseEfficiency = 1f`，
> `canPump(tile) = !tile.floor().isLiquid` —— 它要的恰恰是「附近没有地表水」），
> 实测 `perSecond 6.6`。
>
> 而钻机的水加成只认**自己建筑内的液体库存**：
>
> ```java
> // ConsumeLiquid.efficiency(Building build)
> return Math.min(build.liquids.get(liquid) / (amount * ed * multiplier.get(build)), 1f);
> ```
>
> **它不检查环境、不检查脚下** —— 只要有人把水**送进这台钻机**（`conduit` 或液体桥），
> `optionalEfficiency` 就是 1，于是
> `speed = Mathf.lerp(1f, liquidBoostIntensity, 1f) = 1.6`。
>
> 所以正确结论是：**一条水线（1 台 `water-extractor` + `conduit`）能给钻机群吃到 1.6×，
> 上表的裸速要乘 1.6**。这也解释了对局里为什么有人建抽水机 —— 不是为了找水，
> 是**给钻机加水加成**。
>
> **尚未实测**（按 §五 第 23 条的纪律，这条是源码推导 + 机制自洽，仍需一局对照：
> 「钻机 + 水线」vs「同位置裸钻机」的 `/buildings` `efficiency` 之比应为 1.6）。
> **上表的绝对数字暂时保持裸速，别急着改数** —— 先补那个对照。

---

## 三、替代配方（已不必用，记录封堵情况）

| 方块 | 优势 | 本图可用？ |
|---|---|---|
| `multi-press` | `coal 3 → graphite 2`（省 25%） | **✓ 可用** —— 它「需水」，而**水可以造**（见 §二 的更正）。原表标 ✗ 是同一个思维缺陷 |
| `silicon-crucible` | `coal 4 + sand 6 + pyratite 1 → silicon 8`（省一半） | ✗ 建造成本要 plastanium，plastanium 需石油 —— **这条是「造不出来」，不是「图上没有」** |
| `silicon-arc-furnace` | `silicon 4` | ✗ 建造成本要 beryllium（Erekir 资源） |

**注意区分两类 ✗**：`silicon-crucible` / `silicon-arc-furnace` 是**建造成本链断了**
（要的材料这张图产不出），而 `multi-press` 只是**要一种可以被生产出来的输入** ——
后者不构成不可行。**别把两者混成一句「需水，所以不行」。**

**基础配方始终够用，所以本节的结论不变；但「✗」的判据要写准。**

---

## 四、真实约束是工程量，不是天花板

矿多在离核心较远处（`x=250..340`），把矿机铺出去并各接一条回核心的干线，
是实打实的工作量 —— 但**可完成**。

| 目标 | 需台数 |
|---|---|
| 煤 15/s | 11 台 laser |
| 砂 10/s | 25 台 mechanical |
| 铜 5/s | 14 台 mechanical |
| 铅 5/s | 14 台 mechanical |
| 钛 5/s | 12 台 pneumatic |
| 硅 5/s | 3.3 台 smelter（需煤+砂+电） |
| 石墨 5/s | 7.5 台 press（需煤） |

---

## 五、方法论

**连续四版出结论，前三版全错。**三条教训，按代价排序：

**一、工具的输出也要验算。**
`plan-ore.py` 给出「候选 117 / 可选 12」，我直接抄进结论，从没验过。
真值是「候选 278 / 不重叠 56」。**一个没验算的数字承载了三轮的判断。**

**二、推翻一个结论时，要连它的前提一起推翻。**
v3 推翻 v2 时只质疑「水能不能用」，却把 v1 传下来的 9.79 当既定事实。
被推翻的是「水加成」，但 **9.79 与它出自同一份不可靠输出**。

**三、承重数字必须能自己复现。**
79.52 之所以可信，是因为我**自己抓图、自己分连通块、自己贪心排布**，每步都能审。

**⇒ 规矩：任何进结论的数字，要么从源码推导，要么自己算一遍。**
