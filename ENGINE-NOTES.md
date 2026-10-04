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

## 七、观战视角的快照路由

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

## 八、网络

- 客户端 JVM **必须**带 `-Djava.net.preferIPv4Stack=true`。
  不带的话 UDP 可能绑到 IPv6，服务端按 IPv4 发的快照永远收不到。
- 客户端只对 `KickReason.serverRestarting` 自动重连（`NetClient.kick`）。
  其他断开都只弹对话框，需要自己实现退避重连。
- 数据目录由引擎决定，是 OS 的 app-data 目录（`%APPDATA%\Mindustry`），
  **与 `-WorkingDirectory` 无关**。引擎没有 `-Dmindustry.data.dir` 这个属性。
