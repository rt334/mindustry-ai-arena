# 引擎笔记

Mindustry v160.5 上，把两个 AI 放进同一张图对战，需要知道的引擎行为。

**只记录从引擎源码与运行时行为中验证得到的事实**，不包含任何具体对局的数值或坐标。

---

## 一、坐标系与朝向

**`rotation` 是「出料方向」，不是「接收方向」。**

```
0 = 东 (+x)      1 = 北 (+y)
2 = 西 (-x)      3 = 南 (-y)
```

传送带、分拣器、工厂的正面都按这个约定解释。

**陷阱**：`Tile.relativeTo` 用的是**相反**的映射（`0=west 1=south 2=east 3=north`）。
只有 `Conveyor.acceptItem` 这类同时用到两者的地方会相互抵消。
读代码时看到 `nearby()` 和 `relativeTo()` 并列，不要当成同一个约定。

**铺错朝向不会报错。** `/place` 照样返回 ok，方块照样建出来，只是物品不流动 ——
从外部看就是「建筑都在、产率为 0」。

---

## 二、邻近判定（`BuildingComp.updateProximity`）

邻近由「锚点 + `Edges.getEdges(size)` 的偏移集合」决定。

**2×2 建筑的偏移集合**：

```
{(0,-1), (0,2), (-1,0), (2,0), (1,-1), (1,2), (-1,1), (2,1)}
```

**这条的实用价值**：2×2 矿机只要 footprint 与某建筑的 footprint 相邻，产物就会
**直接推进那个建筑**，中间一格传送带都不需要。

多块建筑的锚点是**左上角**。

---

## 三、矿机

```
getDrillTime(item) = (drillTime + hardnessDrillMultiplier × item.hardness) / drillMultipliers
lastDrillSpeed     = speed × dominantItems / delay
hardnessDrillMultiplier = 50
```

**液体加成**：带 `.consumeLiquid(water).boost()` 的矿机有

```
liquidBoostIntensity = 1.6
speed = lerp(1, liquidBoostIntensity, optionalEfficiency) × efficiency
```

**`dominantItem` 按 footprint 内各矿种的数量取最多者**，不是「有没有这种矿」。
同一格既有 overlay 又有 floor 时，数量多的那种胜出 —— 想挖 A，必须让 A 在
footprint 里占多数。

**矿脉硬度**：

| 矿 | 硬度 |
|---|---|
| sand | 0 |
| copper / lead | 1 |
| coal | 2 |
| titanium | 3 |
| thorium | 4 |
| tungsten | 5 |

矿机有 tier，只能挖 `hardness <= tier` 的矿。

---

## 四、方块语义

| 方块 | 行为 |
|---|---|
| `sorter` | 匹配 `config` 的物品走**正面**（`rotation` 侧）；**不匹配的走两侧** |
| `router` | 向四周均分，但**会被成品倒灌堵死** |
| `conveyor` | 吞吐有限；长线上 20 台矿机会把它喂饱和（每格 `outputAccepts=False`） |
| `core-nucleus` | 5×5 |

`sorter` 的实用技巧：把 `config` 设成一个这条线上**永远不会出现的物品**，
则所有物品都不匹配、**全部走两侧** —— 一次喂到两个方向。

⚠ `sorter` 的 `rotation` 有时不跟随 `/place?rot=` 生效。优先用 `config` 间接控制流向。

---

## 五、建造与放置

- `/place` 是**排队**的：接口返回成功只代表计划入队。
- 建造单位必须**物理走到**工地才会施工；`buildRange = 220px ≈ 27 格`。
- 用 `tile.setBlock()` 现建的方块会进 `TeamData.buildings`，但 `isAdded()` 为 **false** ——
  它不在实体组里。按 `Groups.build` 判断「有没有建成」会漏掉这类方块。

---

## 六、三个已修复的引擎缺陷

### 6.1 无头服务端上单位不移动 —— `SyncComp.update()`

**现象**：服务端上任何由玩家持有的单位坐标每帧被拉回出生点，净位移为零。
小步长（3.55px/帧）被完全吃掉，大步长（57px/帧）只被吃掉一部分 ——
**这是「按比例插值」的签名，不是硬赋值**。

**根因**：

```java
// EntityComp
boolean isLocal(){ return ((Object)this) == player || ...; }        // player = Vars.player
boolean isRemote(){ return ((Object)this) instanceof Unitc u && u.isPlayer() && !isLocal(); }

// SyncComp.update()
if((Vars.net.client() && !isLocal()) || isRemote()) interpolate();
```

无头服务端上 `Vars.player` 恒为 `null` ⇒ `isLocal()` 恒 false ⇒ `isRemote()` 对
**每个**玩家单位恒 true ⇒ 每帧 `interpolate()`，把服务端权威坐标插值回
「上次网络同步位置」。服务端从不给自己回写同步，目标值就永远停在出生点。

**修复**：在 `SyncComp.update()` 开头短路。

```java
if(Vars.headless || Vars.net.server()) return;
```

**⚠ 不要改 `isLocal()` 来达到这个目的。** `NetServer.sync()` 用它跳过玩家：

```java
if(p.isLocal() || p.con == null || !p.con.hasConnected) continue;
```

把 `isLocal()` 全局改成 true 会导致服务端**一个实体快照都不发**，
客户端 20 秒后（`NetClient.entitySnapshotTimeout`）报 UDP 快照超时并断开。

**通用教训**：修改语义宽泛的判定函数（`isLocal` / `isRemote` / `isVisible`）之前，
先把**所有调用点**列出来。同一函数在不同位置可能承载**语义相反**的用途。

### 6.2 服务端不发快照 —— `Logic.update()`

`NetServer.sync()` 没有在 `Logic.update()` 里被调用 ⇒ 快照路由段从不执行 ⇒
`NetServer` 的三个诊断计数器 `diagTeamBatchSends` / `diagFullViewSends` /
`diagSpectatorRouted` 恒为 0。

**修复**：在 `!state.isPaused()` 分支内每帧调用。

**诊断技巧**：这三个计数器是排这类问题的第一手证据，先读它们再读代码。

### 6.3 建造单位不会移动 —— `BuilderComp.updateBuildLogic()`

`BuilderComp` **不含任何移动代码** —— 它的 `update()` 只有 `updateBuildLogic()`。
单位移动由**控制器**负责。正常游戏里那是玩家（按键）；无头服务端上影子 AI 玩家
永远不发移动输入，于是建造单位只建 `buildRange` 内的东西，远处的计划无限期挂起。

`UnitTypes.gamma.controller` 是

```java
u -> u.team.isAI() ? new BuilderAI(true, 400f) : new CommandAI()
```

而 PvP 下 `Team.isAI()` 为 false —— **就算不被玩家持有也只会拿到 `CommandAI`**，
那个同样不建造、不寻路。

**修复**：在 `!within(tile, finalPlaceDst)` 分支里补上朝目标移动，步长与玩家单位一致。

---

## 七、电力

**判据是 `powerStatus`，不是 `powerLinks`。**

- `powerStatus > 0` = 这个建筑在电网里拿到了电。
- `powerLinks` 只统计**显式连线**，多数情况下为 0，**不能用来判断有没有电**。
  实测一个正在满效率运行的 `silicon-smelter`，`powerLinks=0` 而 `powerStatus=1.0`。

**电网靠相邻合并，但「贴着什么」很关键。**

实测：把 `combustion-generator` 贴在**核心**旁边，`silicon-smelter` 一点电都拿不到；
换成一串 `power-node` 从发电机搭到冶炼厂，`powerStatus` 立刻变 1.0。

⇒ **不要指望「发电机贴着核心、冶炼厂贴着核心」就能自动并网。** 用 `power-node` 显式搭桥。

---

## 八、`sorter` 的接收规则与一个副产品用法

```java
// Sorter.SorterBuild
public boolean acceptItem(Building source, Item item){
    return items.total() == 0 && (sortItem == null || sortItem == item);
}
```

**`sorter` 只接收与 `config` 相同的物品，其他一律拒绝**（不是「送到侧面」）。
所以：

- 想让 **A 通过、B 被挡**：把 `sorter` 的 `config` 设成 A。B 会被拒收、退回上游。
- `sorter` 的 `rotation` **不随 `/place?rot=` 生效**（实测传 `rot=3`，建成后是 `r0`）。
  依赖方向的分流不可靠，别用。

**副产品用法（很有用）**：把**消耗型建筑直接放在混料传送带的正下方**。

实测：一条煤带从远处捎带进了沙，末端一格 `(x,y)` 被沙塞死。
把那一格换成 `combustion-generator` 后 —— 发电机**只收煤**，沙被拒收退回上游的矿机
（矿机另有别的出口，不会因此堵死），而煤直接进发电机点火。

一处改动同时解决了「混料堵塞」和「发电机燃料」两个问题，比 `sorter` 可靠。

同理适用于任何 `consumeItem` 的建筑：**它天然的物品过滤本身就是一层分离器。**

---

## 九、多原料配方的循环死锁

**现象**：`silicon-smelter`（配方 sand 2 + coal 1，`itemCapacity = 10`）
`eff = 0.0`、`items = {"coal":10}` —— 一种原料塞满全部格子，另一种进不来。

**机理是一条自己解不开的闭环**：

```
煤比沙到得快
  → 10 格全被煤占满
  → 沙被拒收
  → 不合成 ⇒ 煤不消耗 ⇒ 永远停在 10 格煤
  → 沙在传送带上堆积
  → 沙矿机出口堵死（drillBlocked）
  → 沙彻底断供
```

实测两个队在同一张图上先后掉进同一个坑（`{"coal":10}` 与 `{"sand":1,"coal":10}`），症状一致。

**触发条件**：某种原料的**供应路数**多于另一种。
实测一方有两列煤带、只有一列沙带 —— 煤必然赢下这场竞速。

**处理**：

1. **掐掉多余的原料路数**，让各路到达速率之比贴近配方比例（2:1 就该是煤慢、沙快）。
2. **拆掉重建**已塞死的工厂来清空。光等它自己恢复是等不到的。
3. **根治**：两种原料走**独立的邻格**进厂，不要共用入口 —— 共用入口时谁先到谁通吃。

**通用面**：只要某种原料能**单独填满** `itemCapacity`，多原料机器就有这个死锁面。

---

## 十、混料：不要用「贴得近」来省传送带

**实测教训**：为了省带子把新矿机挂在现有主干旁边，结果是**双向污染**。

**一、矿机向四周所有空格推货** —— 只要 footprint 与某条带子相邻就会往里灌。
一台**沙**矿机挂在**煤**带上，就把沙灌进了煤线：

```
煤柱 (288,109) {sand:2, coal:1}     ← 沙卡在队首
煤柱 (288,111) {sand:1, coal:1}     ← 发电机拒收沙，煤全被挡在后面
```

下游是消耗型建筑（只收煤）时尤其致命：被拒收的沙**永久占住那一格**，
该格上游彻底断流。表现为「发电机 `items={}`，可煤明明在远处流过」。

**二、主干很快饱和。** 一次性挂上 7 台沙矿机后，其中 **6 台 `eff=0.0`、
`items={"sand":10}` 满仓推不出去** —— 带子吞吐撑不住，矿机白建。

**⇒ 规则：沙和煤各走独立的列，各自的矿机只贴自己那一条。**
省下的几格带子，代价是整条链反复死锁。

**排查口诀**：矿机 `eff=0.0` 且 `items` 满 = **出口推不出去**（下游堵或吞吐不够），
不是矿脉挖不动。去查它相邻的那条带子。

---

## 十一、三条工程纪律（本项目反复踩到）

**一、改语义宽泛的判定函数前，先列出所有调用点。**
`isLocal()` / `isRemote()` / `isVisible()` 这类函数在不同位置可能承载**相反**的语义。
本项目在 `isLocal()` 上踩过：为修一个「单位不移动」而改成全局 true，
结果打断 `NetServer.sync()` 的玩家过滤，服务端一个快照都不发（见 6.1）。

**二、先证明上限，再下结论。**
用受限视野扫出来的数字会安静地偏低，看起来完全合理。评估容量前先确认覆盖比例。

**三、一次只改一个变量。**
铺一片再测，出问题无法归因；测出的差异也不知道是哪一处造成的。


`NetServer.sync()` 在 `rules.fog` 下的路由逻辑：

```java
for(Player p : Groups.player){
    Team view = viewTeamFor(p);
    boolean full = view == null && isFullView(p);
    if(view == null && !full) continue;      // 两者都不满足 -> 一个快照都不发
    ...
}
```

`isFullView(p) = p.spectator && p.team() == Team.derelict`。

`viewTeamFor` 走 `NetServer.viewTeamProvider` 这个回调。**它是一个可选注入点，
不注册就返回 null** —— 于是任何「观战者绑定到某个真实队伍」的用法都会
静默掉进 `continue`，收不到任何快照。

要支持「以某队视角观战」，必须注册该回调。

---

## 十二、网络

- 客户端 JVM **必须**带 `-Djava.net.preferIPv4Stack=true`。
  不带的话 UDP 可能绑到 IPv6，服务端按 IPv4 发的快照永远收不到。
- 客户端只对 `KickReason.serverRestarting` 自动重连（`NetClient.kick`）。
  其他断开都只弹对话框，需要自己实现退避重连。
- 数据目录由引擎决定，是 OS 的 app-data 目录（`%APPDATA%\Mindustry`），
  **与 `-WorkingDirectory` 无关**。引擎没有 `-Dmindustry.data.dir` 这个属性。
