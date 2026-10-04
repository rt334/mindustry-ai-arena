# AI 竞技场 · 经验教训

按主题归档的实测结论。**每一条都是量出来的，不是推断的** —— 推断错的那几条单独列在最后一节。

---

## 0. 项目坐标

| 项 | 路径 |
|---|---|
| 竞技场工程 | `C:\dsh\ai-arena` |
| 引擎源码 | `C:\dsh\Mindustry-src`（tag `v160.5`） |
| JDK | `C:\dsh\zulu17\zulu17.68.203-ca-jdk17.0.20.1-win_x64` |
| 服务端 jar | `Mindustry-src\server\build\libs\server-release.jar` |
| 客户端 jar | `Mindustry-src\desktop\build\libs\Mindustry.jar` |
| mod 产物 | `ai-arena\mod\ai-arena.jar` → 部署到 `server-run\config\mods\` |
| 观战 mod | `ai-arena\observer\ai-observer.jar` → `%APPDATA%\Mindustry\mods\` |

**所有 java 都要加 `-Djava.net.preferIPv4Stack=true`**，否则 IPv6 解析会拖住连接。

---

## 1. 引擎内部（全部实测）

### 1.1 坐标与朝向

```java
// Block.java:775,1451 —— v8 用**中心坐标**
sizeOffset = -((size - 1) / 2);
```

- `BuildPlan.x/y`、`Building.tileX()/tileY()` 都是**中心**
- `/place` 收中心坐标，`/buildings` 报中心坐标
- size 2 → `sizeOffset = 0`（左上角就是锚点）；size 3 → `-1`；size 5 → `-2`

**旋转约定**（`BuildingComp.nearby(int)`）：`0=东(+x) 1=北(+y) 2=西(-x) 3=南(-y)`

**传送带的 `rotation` = 出料方向，用 `nearby` 约定。入料来自对面那一侧。**

```java
// Conveyor.java:353
public boolean acceptItem(Building source, Item item){
    Tile facing = Edges.getFacingEdge(source.tile, tile);
    int direction = Math.abs(facing.relativeTo(tile.x, tile.y) - rotation);
    return (((direction == 0) && minitem >= itemSpace)
         || ((direction % 2 == 1) && minitem > 0.7f)) && ...;
}
```

**⚠ 这里有个坑：`Tile.relativeTo` 用的是和 `nearby` 相反的一套约定。**

```java
// Tile.java:103
public static int relativeTo(float x, float y, float cx, float cy){
    if(Math.abs(x - cx) > Math.abs(y - cy)){
        if(x <= cx - 1) return 0;   // 目标在 -x（西）
        if(x >= cx + 1) return 2;   // 目标在 +x（东）
    }else{
        if(y <= cy - 1) return 1;   // 目标在 -y（南）
        if(y >= cy + 1) return 3;   // 目标在 +y（北）
    }
    return -1;
}
```

`relativeTo`：**0=西 1=南 2=东 3=北**，恰好是 `nearby` 的对向 `(d+2)%4`。

`acceptItem` 把两者直接相减判 `== 0`，两套约定相消之后，**`rotation` 就是出料方向**（`nearby` 约定）。实测：

| 摆放 | 效果 |
|---|---|
| `rot=0` | 从**西**边收料 → 往**东**送 |
| `rot=1` | 从**南**边收料 → 往**北**送 |
| `rot=2` | 从**东**边收料 → 往**西**送 |
| `rot=3` | 从**北**边收料 → 往**南**送 |

判别实验（一次定论）：矿机在 `(41,92)`，带子摆在 `(41,91) rot=3` —— 带子立刻拿到煤，并把煤送到 `(41,90)`（南边）。矿机在带子的**北**侧，`rot=3` 收北送南 ✓

**注意 `direction == 2`（来源在对面）会被拒收。** 这一条可以用来「堵住」某个方向的出料 —— 例如让入料带拒绝上游建筑把成品倒灌回来。

另外 `proximity` 用 anchor + `Edges.getEdges(size)` 建，**2×2 方块的东西边缘邻居（如 anchor 东移 2 格）也在里面**，所以多块建筑能直接吐给隔着一格 footprint 的邻居。

### 1.2 迷雾（FogControl）

**这是整个项目里最耗时间的一块，值得完整记住。**

```java
// FogControl.java:117
public boolean isVisibleTile(Team team, int x, int y){
    if(!state.rules.fog || team == null || team.isAI()) return true;
    var data = data(team);
    if(data == null) return false;      // ← 没有迷雾数据 = 全图不可见
    return data.read.get(...);
}

// FogControl.java:129
@Nullable FogData data(Team team){
    return fog == null || fog[team.id] == null ? null : fog[team.id];
}
```

**`fog[team.id]` 原本只在 `pushStaticBlocks()` 里创建**，而那个方法只在 `WorldLoadEvent` 时跑一次。所以**地图加载之后才出现第一个「带迷雾半径建筑」的队伍，永远拿不到 FogData**。

补救入口 `forceUpdate()` 的第一行就是 `if(state.rules.fog && fog[team.id] != null)` —— **它要求数据结构已存在，救不了从未创建的情况**。

**渲染侧的两级判定**（`FogRenderer.java:46`）：

```java
if(fogControl.getDiscovered(player.team()) == null) return;   // null -> 不画迷雾，世界可见
```

所以：
- `getDiscovered()` 返回 **null** → 不画迷雾 → 世界正常可见
- 返回**全零位图** → 全部判为未探索 → **整屏全黑**

黑屏只可能是后者。

**`Bits.length()` 是「最高置位 +1」，不是分配长度。** 全零的 Bits `length()` 返回 0，看起来像「零长度分配」，实际只是「一个 bit 都没置位」。这一点让我误判过一轮。

**事件链**：`Tile.setBlock` → `fireChanged()` → `TileChangeEvent`（仅当 `!world.isGenerating()`）→ 处理器里 `if(state.rules.staticFog) pushEvent(...)` → `update()` 末尾 notify → `StaticFogThread` → `updateStatic()` → `circle(data.staticData, ...)`。

**这条链上任何一个环节断掉，`staticData` 都会保持全零。** 本次断在「处理器里的 staticFog 门」。

### 1.3 `Groups.build` vs `TeamData.buildings`

**这两个不是一回事，而且 `Groups.build` 会少。**

实测 `setup` 之后：
```
Groups.build.size()            = 2   （只有地图自带的核心）
TeamData.buildings / cores     = 4   （四个队各一个核心）
```

用 `tile.setBlock()` 在**地图加载之后**现建的核心会进 `TeamData.buildings`，但 `isAdded()` 是 **false** —— 没被真正加进实体组。

所以：
- 要列全部建筑 → **用 `TeamData.buildings`**（`Snapshot.collectBuilds` 就是这么做的）
- 而且要**不要**加 `b.isAdded()` 过滤，否则会静默跳过你要找的那些

### 1.4 电力

```java
// BuildingComp.updateEfficiency()
efficiency = shouldConsume() ? (enabled ? 1f : 0f) : 0f;
if(block.hasPower && power != null) efficiency *= power.status;   // 无电源 -> 0
```

**没有电源的耗电建筑 `efficiency` 恒为 0**，表现为「料齐了但一颗都不产」。`/buildings` 的 `powerStatus` 字段能直接看出来。

`PowerGraph` 的连接条件：**相邻**，或通过 `power-node` 在 `laserRange`（默认 6 格）内相连。

### 1.5 其他

| 事实 | 位置 |
|---|---|
| `tile.drop()` 解析顺序：`block.itemDrop` → `overlay.itemDrop` → **`floor.itemDrop`** | 沙在地板层（`darksand`/`sand-floor`），只看 overlay 会全漏 |
| `Block.fogRadius > 0` → `hasFogRadius` 标志，在 `init()` 里设 | 构造器里设 `fogRadius` 有效 |
| `CoreBlock`：`lightRadius = 30 + 20*size`；`fogRadius = lightRadius/8*3 + 13` | size 5 → 61；size 3 → 46 |
| `Team.isAI()` 在 `rules.pvp = true` 时**恒为 false** | 所以 PvP 里 `isOnlyAI()` 也是 false，迷雾不会跳过这些队 |
| `UnitComp.ammof()` 对普通单位**恒返回 1**；`UnitType.ammoCapacity` 默认 1 | `flare`/`gamma` 的弹药永远是 1/1，只有方块单位会变 |
| `CommandAI.attackTarget` 是当前攻击目标 | `WeaponsComp.isShooting` 是开火状态 |
| `PlayerComp.checkSpawn()` 找不到 core 就永远不给单位 | 玩家挂在没有核心的队上 → 没单位也没视野 |
| `PlayerComp.spectator`（`@NoSync`）阻断 `update()`/`checkSpawn()` | 观战者既不生成单位也不重生 |

### 1.6 配方（实测，纠正过两次）

| 方块 | 配方 |
|---|---|
| `silicon-smelter` | **coal 1 + sand 2 + 电 0.5** → silicon 1 |
| `pulverizer` | scrap 1 + 电 0.5 → sand 1 |
| `graphite-press` | coal 2 → graphite 1 |
| `combustion-generator` | copper 25 + lead 15，烧煤 → **电 1.0**（size 1） |
| `solar-panel` | lead 10 + **silicon 8** → 电 0.12（size 1） |
| `solar-panel-large` | lead 60 + silicon 70 + phase-fabric 15 → 电 1.6（size 3） |
| `mechanical-drill` | copper 12，tier 2（size 2） |
| `router` | copper 3（size 1） |
| `unloader` | **titanium 25** + silicon 30 —— 铜铅起步阶段用不了 |

**矿物硬度**：sand 0 / copper 1 / lead 1 / coal 2 / titanium 3 / thorium 4 / tungsten 5

`mechanical-drill` tier=2 → 只能挖硬度 ≤2 的。

**起步闭环**：铜铅 → 沙机 + 煤机 → 硅冶炼厂 → 硅 → 太阳能板/工厂。
**关键**：`solar-panel` 要硅、硅又要电 —— 死循环。**`combustion-generator` 是唯一不依赖硅的电源**（铜 25 + 铅 15）。

---

## 2. API 设计

### 2.1 HTTP 与 WebSocket

mod 用的是 JDK 内置的 `com.sun.net.httpserver.HttpServer` —— **它不支持连接劫持**，做不了 `Upgrade`。WebSocket 必须另开裸 `ServerSocket` 自己实现 RFC 6455（握手 + 分帧），零依赖可行。

- 客户端帧**必须**带掩码，不带直接拒（协议硬性要求）
- 服务端帧**不能**带掩码
- 浏览器没法给 WS 握手设自定义头 → token 走 query string；内部转发回 REST 时改回 `Authorization: Bearer`

**REST 与 WS 的分工**：REST 管一次性查询（`/content`、`/map`、`/ore`、`/block`），WS 管高频状态流 + 命令复用同一条连接。

### 2.2 无头服务端没有文案

```java
// ServerLauncher.java:44
loadLocales = false;
```

而且 **`server-release.jar` 里根本没有 `bundles/` 目录**（只有客户端 jar 有）。所以 `localizedName` / `description` 永远是空。

修法：从客户端 jar 抽出 `bundles/bundle*.properties` 放到服务端工作目录，用 `Core.files.local("bundles/bundle")` 加载。

**⚠ 判断顺序**：不能先看 `b.localizedName` 非空就用它 —— 内容加载时它已被赋成 fallback（就是 `name` 本身），非空但没意义。**bundle 才是权威。**

### 2.3 `/place` 是排队的

`/place` 返回 `ok` 只代表**计划入队**，不代表建筑存在。`BuilderComp` 会逐步执行。

后果：连续对同一格下单会静默失败，或者以为「建好了」其实没有。客户端必须自己维护 `placed_tiles` + `pending_tiles`。

### 2.5 产线诊断三件套（`/rates` + `/stalls` + `/drill`）

单看某一刻的库存**分不清「在产」和「堵住」**。这三个接口是配套的：

| 接口 | 回答的问题 |
|---|---|
| `GET /rates?window=10` | 这个窗口内**产了多少、耗了多少** |
| `GET /stalls` | **堵在哪一格**，出料侧是什么、它收不收 |
| `GET /drill` | 每台矿机的 `dominantItem` / `dominantItems` / `efficiency` |

**`/rates` 返回两组量，对照着看才能定位：**

```
core    该队核心里的物品（= 净产出）
stored  该队所有建筑里的物品总量（含传送带在途）
```

- `core` 不涨 + `stored` 涨 → 东西堵在产线里，没送到核心
- `core` 涨 + `stored` 平 → 健康
- 两者都不涨 → 上游没在挖（矿机空转 / 没料 / 没电）

实测它一眼照出过两次大问题：一次是「沙在全线堆积」（矿机挖错矿种），一次是「所有物品 Δ=0」（全线被沙堵死）。

**`/stalls` 的判据用引擎自己的 `clogHeat`**（`Conveyor.java:291`）：它以 1/60 每帧在 0~1 之间涨落，**涨到 1 本身就约等于「堵了 1 秒」**，不需要自己计时。每条报警给出：

```
x/y/rotation   位置与朝向
items          上面压着什么
stalledSeconds 堵了多久
outputSide     出料侧是什么方块
outputAccepts  它收不收（False = 下游满了或方向不对）
```

**⚠ `clogHeat` 高 = 饱和，不等于死堵。** 一条满载但在流动的带子也会报。真正的死堵特征是「最靠近消费者的那一条 `outputAccepts=False`」—— 那才是堵塞链的头。

**`/drill` 的 `dominantItem` 是每局必须重查的。** 见 §4.11。

### 2.4 对等性标准

所有信息接口严格按「玩家在迷雾下能真正看到什么」实现：

| 信息 | 判定 |
|---|---|
| 建筑 `rotation` | 无条件可见（屏幕上就画着） |
| `powerStatus` | 无条件可见（电力条） |
| `powerLinks[].x/y` | 可见节点的激光线**画到对端真实坐标**，所以位置可见 |
| `powerLinks[].block/team` | **只在目标本身可见时才给** —— 雾里那一端是黑的 |
| 单位 `shooting` | 无条件可见（枪口火光、弹道） |
| 单位 `targetX/targetY` | 可见（弹道往哪飞） |
| 单位 `targetId/Type/Team` | **只在目标可见时才给** |
| 视野事件 | **只发给产生它的那一队** —— 「谁在看我」是对手情报 |

依据：`PowerNode.draw()` 只对通过迷雾检查的建筑调用，但可见节点的激光束会一直画到对端真实坐标。

### 2.6 客户端自动重连（两个客户端都要）

**为什么必须有**：改 mod 就要重启服务端，一重启所有客户端全挂。实测一局里重启三五次是常态，没有重连的话每次都得手动重启所有 AI 客户端，排查节奏完全断掉。

**`ai-client.py`（HTTP）** —— 在 `Arena._call` 里做重试：

| 错误 | 处理 |
|---|---|
| 传输层异常（`WinError 10061` 等） | 指数退避重试，`max_retries` 次后抛 `ArenaError(0, ...)` |
| HTTP **5xx** | 同样重试（服务端暂时不可用） |
| HTTP **4xx** | **立刻返回** —— 那是业务错误，重试没意义 |

退避实测：`0.4 → 0.8 → 1.6 → 3.2 → 6.4 → 8.0`（封顶 `max_delay`）。

主循环里 `ArenaError.code == 0` 不再吞掉，而是标 `offline`、调 `wait_online()` 轮询 `/ping`、回来之后继续跑 —— **整局 AI 不会因为一次重启报废**。

`wait_online(timeout)` 也用在**启动时**：以前服务端还没起来客户端就直接退出，现在会等。

**`ws-client.py`（WebSocket）** —— `connect_with_retry()` + 主循环里 `socket.timeout`/`WsError`/`None` 三种断线都触发重连，并且**重连后必须重新发 `sub`**（订阅是连接级的，不重订就收不到任何频道）。

**注意**：重连是幂等的。agent 与队伍的绑定存在服务端，客户端只要重新发请求即可，不需要重新注册。

实测（杀掉服务端再拉起）：

```
[net] transport: WinError 10061…；0.4s 后重试 (第 1/6 次)
...
[net] transport: …；8.0s 后重试 (第 6/6 次)
[net] 服务端已恢复（累计重连 1 次）
[alpha] 已恢复，中断 12.3s
```

---

## 3. 调试方法论

**这些是这次最省时间的几条。**

1. **测量，不要推理。** 每一轮都先问「我怎么用一条命令把这个假设变成事实」。整条迷雾链是靠 `[fogdbg]` 系列插桩定位的，纯读代码猜了四五轮全是错的。

2. **引擎层插桩要打到无头服务端上。** 我第一次写插桩时加了 `if(!headless)` —— 而服务端就是无头的，结果 0 条输出，白跑一轮。

3. **插桩要逐步打，不要只打一个点。** 「进入处理体 → step1 → step2 → step3 → 即将 pushEvent → 已返回」这样打，一次就能看到断在哪。只打入口和出口会误判成「整段没执行」。

4. **加诊断字段到现有接口。** `/diag` 里加一个 `fogState`（每队的 `bits` / `discovered`），比重新写工具快得多。

5. **时间窗比一次性调用稳。** 核心放进世界后要过一会儿才出现在实体组里，就地推和 30 帧后推都只数到一半。改成「20 秒内逐帧反复推」（操作幂等）一次就对了。

---

## 4. 踩过的坑（按代价排序）

### 4.1 PowerShell 多行替换会静默失败

**LF/CRLF 不匹配**：here-string 里是 LF，文件里是 CRLF，`String.Replace` 匹配不上**且不报错**。

后果：我以为打了插桩，实际没打，然后基于「0 条输出」得出了错误结论，浪费两轮。

**修法**：多行替换一律用 `edit` 工具；用 PowerShell 时必须 `Select-String` 回读确认。

### 4.2 PowerShell 5.1 不支持 `??`

`$a ?? $b` 直接语法错误。用显式 `if/else`。

### 4.3 传送带朝向：来回错了两次

第一次按「rotation = 出料方向」布局，线通了；排查另一个问题时**误判成「rotation = 入料侧」**，把整条线改反，全线哑火，然后又把错误结论写进了本文档。

**真正的坑在于 `Tile.relativeTo` 和 `BuildingComp.nearby` 用两套相反的方向约定**，而 `Conveyor.acceptItem` 把两者直接相减。只看那一行代码会得出相反结论 —— 必须把 `relativeTo` 的实现也读了才看得清（见 §1.1）。

**教训**：结论要从**完整调用链**推，不能只看一行。有疑义时做一次**判别实验**（在两三种摆法里只改一个变量）比继续读代码快得多 —— 这次就是靠「矿机北侧放一条 rot=3」一次定论的。

### 4.4 硅冶炼厂配方记错

一直按「铜 + 煤」写，实际是 **沙 + 煤**。AI 的硅永远是 0，整条经济链哑火 —— 而 `_find_ore` 只筛 `overlay` 的 `ore-*` 前缀，把地板层的沙全漏了。

### 4.5 `isAdded()` 过滤静默跳过目标

补推迷雾时加了 `if(!b.isAdded()) continue;`，而 `setBlock` 现建的核心 `isAdded()` 恰好是 false —— 恰好把所有要找的建筑都跳过了。加防御性检查前要确认它不会排除掉你要找的东西。

### 4.6 观战者「黑屏」被误判成渲染 bug

实际是三层叠加：`staticFog` 门 → 事件丢失 → 全零位图。而 UI 层（队伍名、核心库存）完全正常，极具误导性。

**另一层误导**：相机不跟随。切队后相机留在上一队位置，而新队伍在那片区域大概率没探索过 —— 迷雾**正确地**画成全黑，看起来还是「黑屏」。所以修完迷雾还得单独修相机。

### 4.7 相机每帧覆盖 = 和引擎抢方向盘

`DesktopInput` 本来就有「玩家已死 → 自由平移」分支（WASD / 中键拖拽 / 滚轮）。我每帧 `Core.camera.position.set(...)` 和它互相抵消，表现是「怎么按视角都不动」。

**正解**：只在**视角队伍变化时跳一次**，之后完全交给引擎。

### 4.8 只跑 `setup` 不开端口

`setup` 只准备世界，`host` 才 `openServer()`。少了 `host` 客户端连不上（6567 未监听），而 7199/7200 都正常 —— 看起来像「服务端没问题但连不上」。

**启动顺序**：`setup` → `host` → `start` → 起 AI 客户端 → 起观战端。

### 4.9 `openServer()` 会清空 `Groups.player`

每次 `host` / `start` 之后都要重建 AI 玩家，否则没有 `PlayerComp` 去 `requestSpawn`，AI 一动不动。

### 4.10 看门狗在 `setup` 之前就建玩家

它用**配置队**（100/101）先建出 `[AI] alpha`。`setup` 之后绑到 sharded 并新建了正确的玩家，场上同时存在两个同名玩家；而 `dedupeAgentPlayers` 原来只保留先遇到的 —— 如果旧的排前面就把正确的删了，绑定白做。

**修法**：保留**队伍与 agent 当前绑定一致**的那一个。

### 4.11 每局必须重扫矿脉，`dominantItem` 不能缓存

**⚠ 扫描必须用 `view=all`（裁判 token）。用队伍 token 扫会只拿到自己视野内那 17%，
并得出完全错误的产能上限。**

实测教训：`veins` 图上用 alpha 的 token 扫，得到「煤只有 47 格，2×2 矿机放得下 2 处，
天花板 0.26/s」—— 据此判定「+5/s 煤物理不可达」，白绕了一整轮。
换裁判 token 扫全图（`?view=all`）后：

| 矿 | 队伍视野（错） | 全图（对） |
|---|---|---|
| coal | 47 | **1112** |
| copper | 274 | 2360 |
| lead | 295 | 1306 |
| titanium | 95 | 498 |

重算后的真实上限（`plan-ore.py --all --x0 0 --y0 0 --w 350 --h 200`）：

```
机械矿机      coal 5.49/s   copper 9.51/s   lead 8.31/s   sand 141.3/s
laser 矿机    coal 9.79/s   copper 16.55/s  lead 15.45/s  sand 279.9/s  titanium 4.05/s
```

⇒ `+5/s 煤` **可达**（laser 只要 3.5 台）。**先证明上限，再下结论。**

**换图之后矿脉位置会变。** 实测同一张 `veins`，两次 `setup` 之间煤的位置从 `(59,118)` 变到 `(66,113)` 又变到 `(47,103)`。

更阴的是：`Drill` 的 `dominantItem` 是**按 footprint 内各矿种数量取最多的那个**（`Drill.countOre`）。同一格可能既有煤的 overlay 又有沙的 floor：

```
(42,93) 明细: coal,sand,sand,sand   -> dominantItem = sand   ✗ 挖出来是沙
(41,92) 明细: coal,coal,coal,coal   -> dominantItem = coal   ✓
```

**所以下矿机前必须逐点用 `/ore` 验证 `dominantItem`，不能只看「这里有没有煤」。**

代价：一次「AI 全程没产硅」的排查，根因就是矿机全在挖沙。

### 4.12 路由器（router）会被成品倒灌堵死

`router` 只有 1 格容量、什么都收。冶炼厂把成品硅倒灌进旁边的 router 后，router 就再也收不了煤 —— 整条煤线哑火，而**外表看不出任何异常**。

实测：`(58,110) rot=0 出料侧=router 接受=False`，router 里静静躺着一颗硅。

**修法**：需要「分料但拒收某些物品」时用 `sorter`（`config` 指定物品，匹配的走正面、其余走两侧），不要用 router。`sorter` 造价只要铜 2 + 铅 2。

### 4.13 分拣器的 `rotation` 决定「匹配物品走哪边」

`sorter` 的正面是 `rotation` 方向：**匹配 `config` 的物品走正面，其余物品走两侧**。

实测把 `config=coal` 的分拣器摆成 `rot=0`（正面朝东），煤全被送去了东边的发电机，冶炼厂一颗没拿到。

**关键技巧：把 `config` 设成一个这条线上永远不会出现的物品。**

比如煤线的分拣器设 `config=sand` —— 煤全都不匹配，于是**全部走两侧**，一次喂到北边（冶炼厂）和东边（发电机）两个消费者。比 router 安全（router 会被成品倒灌堵死，见 §4.12），比 `config=coal` 灵活（那个只能喂正面一个方向）。

实测这一改把硅产率从 **0.10/s 提到 0.40/s**。

**⚠ `sorter` 的 `rotation` 有时不跟随 `/place?rot=` 生效**（实测下 `rot=1` 后仍报 `rot=0`）。所以不要依赖朝向，优先用 `config` 选择物品来间接控制流向。

### 4.14 长线施工要分段验证

22 格的传送带一次下单，中间任何一格朝向错或位置被岩石占用，整条线都不通，而 `/place` 全程返回 `ok`。

**做法**：先 `/map` 把路径逐格验一遍（`block == "air"`），再下单；下单后用 `/stalls` 立刻看拐角。实测拐角 `(57,102)` 和 `(57,110)` 各错过一次。

**主干方向由参数显式声明，不要从 y0/y1 的大小去推。** 实测把南主干传成 `y0<y1` 就被自动判成北流，整条线反着堵 —— 物品全被吐向空气。


### 4.15 建造单位不会移动 —— 根因：无头服务端误判「远程玩家」

**现象**：`/place` 下单成功、队列显示 `plans=N`，但建筑永远不出现。
单位只建 `buildRange`（220px ≈ 27 格）内的东西，远处的计划无限期挂起。

**根因链（三段，每段都实测过）：**

**① `BuilderComp` 不含任何移动代码** —— 它的 `update()` 只有 `updateBuildLogic()`。单位移动由**控制器**负责。
而 gamma 被影子 AI 玩家持有（`controller = Player#NNN`），影子玩家永远不发移动输入。
`UnitTypes.gamma.controller = u -> u.team.isAI() ? new BuilderAI(true, 400f) : new CommandAI()`，
PvP 下 `Team.isAI()` 为 false，所以就算不被玩家持有也只会拿到 `CommandAI`（同样不建造、不寻路）。

**② 于是给 `BuilderComp` 补了「够不到就自己走过去」的逻辑。** 但写进 `x/y` 的值活不过一帧。

**③ 真正的还原者是 `SyncComp.update()`：**

```java
// SyncComp.java:33-41
public void update(){
    if((Vars.net.client() && !isLocal()) || isRemote()){
        interpolate();
    }
}
```

配合

```java
// EntityComp.java:30-36
boolean isLocal(){ return ((Object)this) == player || ((Object)this) instanceof Unitc u && u.controller() == player; }
boolean isRemote(){ return ((Object)this) instanceof Unitc u && u.isPlayer() && !isLocal(); }
```

**`player` 是 `Vars.player`（本地玩家）。无头服务端上它恒为 null** ⇒ `isLocal()` 恒 false
⇒ `isRemote()` 对**每个**玩家单位恒 true —— 服务端上根本没有「远程玩家」这个概念。

⇒ `interpolate()` 每帧执行，把服务端权威坐标插值回「上次网络同步位置」；
服务端从不给自己回写同步，目标值就永远停在出生点。

**修复**（`EntityComp.java:45`）：

```java
boolean isLocal(){
    if(headless) return true;   // 无头服务端是权威方，不做插值
    return ...;
}
```

**修复后实测（`type.speed`，与玩家同速）**：

```
[s7] u217=(488,832)   ← 起点（核心）
[s7] u217=(488,569)   ← 移动 263px
(61,44) ✓ 已建成
```

视野内 30/40/50/60 格 **4/4 全部建成**。70 格那次失败是**迷雾限制**（`/map` 返回 `block` 为空、
`/place` 直接拒绝、`plans=0`），符合公平竞赛规则，非移动问题。

**关键鉴别特征 —— 量级依赖**：

| 步长 | 结果 |
|---|---|
| `type.speed` = 3.55px/帧 | 累积 **10 帧**后被拉回，之后基本每帧拉回，**净位移为零** |
| `type.speed * 16` ≈ 57px/帧 | 连续累积不被打回，5 帧走完 284px |

**这是「按比例插值」的签名，不是硬赋值** —— 硬赋值会把 57px 也一起抹平。
凡是遇到「小位移被吃掉、大位移能推进」，优先怀疑插值/lerp，而不是碰撞或钳制。

**排除清单（都实测证伪，避免后人重走）**：

| 猜测 | 证伪依据 |
|---|---|
| 单位卡在 solid 核心里 | `elev=1.0 flying=true solid=false` —— gamma 是飞行单位，`solidity()` 返回 null，根本没有碰撞 |
| `PhysicsProcess` 拉回 | 探针一行未触发，物理增量恒为 0 |
| `infiniteResources` 让 `within()` 恒真 | `within=false dst=220.0 infinite=false` |
| 方块未解锁 / 不可建造 | `allow=true unlocked=true env=true placeable=true` |
| `type.bounded` 坐标钳制 | `limitMapArea=false`，`left/bot=0`、`right/top=2800/1600`，钳整图，对 y=828 无效 |
| `isGrounded()` 钳制 | `elevation=1.0`，跳过 |
| 出生点击退 `velAddNet` | 需 `state.hasSpawns()` 且在 `within(spawn, relativeSize)` 内，且方向是朝外推 |
| `warpDst` 回拉 | `warpDst = 8f` 是常量，只在越界分支用 |
| 速度路径 | 帧首 `vel` 恒为 0 |

**⚠ 调试教训**：中途我拿 `[A]`/`[B]`（打给 id=217/219/222/225）去对照 `[M]`（id=221 的建造单位），
**根本不是同一台单位**，由此推出的「`unit:` 块头尾恒等」完全无效，白绕了好几轮。
**对照组必须带 id 且确认是同一台。**

---

### 4.16 「性能消耗大」先测进程，别猜游戏

**现象**：感觉整体变卡、占用大。

**实测（服务端根本不忙）**：`TPS = 60.0`（满帧）、`worldUnits=4 worldBuilds=2`、日志 50 行。

**真凶是 `gradle.properties` 的 `-Xmx8192m`：**

```
org.gradle.jvmargs=-Xms256m -Xmx8192m ...
```

Gradle daemon 拿到 8 GB 堆上限后长期驻留 **3,410 MB**，把 15.7 GB 机器的可用内存
压到 **2.2 GB（86% 占用）** —— 而它只在我偶尔重建时才干活。

**修复**：`-Xmx8192m` → `-Xmx3072m`；daemon 常驻降到 **714 MB**，构建仍 11.3s 成功。
不重建时 `gradlew --stop` 直接释放。可用内存 2.2 GB → **5.6 GB**。

**顺带修掉的 mod 每帧浪费（规模化后才明显）**：

| 位置 | 原状 | 改后 |
|---|---|---|
| `StallWatch.update()` | **每帧**遍历所有队伍的所有建筑，且给每栋楼拼 String key、每帧新建两个 HashSet | 节流 10 Hz（判定阈值本就是 1000ms） |
| `AIArena.fogRepushTick()` | 20 秒窗口内每帧（约 1200 次）遍历所有建筑逐个 `forceUpdate`；建筑不动、迷雾半径不变 | 节流 10 Hz |

**方法论**：遇到「卡 / 占用大」，先量 TPS + 逐进程 CPU/内存，再动代码。
这次若先改游戏逻辑，就是白费功夫 —— 只有 4 个单位、TPS 满帧。

---

### 4.17 观战端断线自动重连

**问题**：Mindustry 客户端**只对 `KickReason.serverRestarting` 自动重连**（`NetClient.kick`）。
其他任何断开（超时、连接重置、服务端抖动）都只弹一个对话框等人手动点。
观战端跑一整局，中途断一次就得人工干预 —— 而手动重连还会重置视角。

**修复**（三处）：

| 文件 | 改动 |
|---|---|
| `core/src/mindustry/net/Net.java` | 新增 `autoReconnect`（默认 false，`-Dmindustry.autoreconnect=true` 开启）+ `updateAutoReconnect()`：检测「本来连着、现在断了」→ 每 3 秒退避重连 |
| `core/src/mindustry/net/Net.java` | `JoinDialog.lastIp/lastPort` 改为 `public`（`Net` 在 `mindustry.net` 包，读不到包级私有字段） |
| `core/src/mindustry/core/Logic.java` | `update()` 开头调用 `net.updateAutoReconnect()` |
| `live-match.ps1` | 传 `-Dmindustry.autoreconnect=true`；默认 `$GameJar` 从 vanilla 改为自建客户端 |

**⚠ 踩到的坑（自毁式条件）**：第一版写的是

```java
if(!headless && net.client()) net.updateAutoReconnect();
```

`net.client()` = `active && !server` —— **断线时 `active` 就是 false**，
于是重连函数永远没被调用，测试日志里一条 `[autoreconnect]` 都没有。
方法内部本来就判 `active/server/autoReconnect`，外层不该再加这道门。

**关键设计点**：`arWasConnected` 标志。只有**曾经成功连上过**才触发重连，
否则第一次进游戏前（还没点连接）也会被当成断线狂重试。

**验证**：杀掉服务端 → 1 秒内触发 `[autoreconnect] lost connection, retrying 127.0.0.1:6567`，
每 3 秒重试一次；服务端重启后自动连回，视角自动恢复：

```
Connecting to server: /127.0.0.1:6567
Received world data: 30.3 kB
[observer] view -> derelict (FULL MAP)
[diag] ... spectator=true ... net=up
```

服务端侧同步确认 `rt has connected` + `auto-spectate rt -> ok team=derelict view=all`
—— **视角是服务端在 PlayerJoin 时下发的，所以重连后不用额外处理**。

**残留**：重连会把相机重置到默认位置（日志里的 `cam=(198,27)`），
不像视角那样能自动恢复。要保留相机位置得额外在客户端记一份。

**另注**：数据目录（存档/设置/mods）由引擎决定，是 OS 的 app-data 目录
（`%APPDATA%\Mindustry`），**与 `-WorkingDirectory` 无关**。
不要试图用工作目录去隔离它 —— 引擎里没有 `-Dmindustry.data.dir` 这个属性。

---

### 4.18 UDP 快照超时 —— 根因是我自己前一轮的修复

**现象**：观战端连上后每隔十几秒报
`Timed out after not received UDP snapshots.` 并断开（有自动重连所以表现为反复断连）。

**判定**：`NetClient.java:666`，阈值 `entitySnapshotTimeout = 1000 * 20`（20 秒）——
客户端 20 秒收不到任何 UDP 快照就断开。

**根因（一条完整的自伤链）**：

**① 前一轮为了让建造单位能动，我改了 `EntityComp.isLocal()`：**

```java
boolean isLocal(){
    if(headless) return true;        // ← 我加的
    return ...;
}
```

**② 而 `NetServer.sync()` 恰恰用它来跳过玩家**：

```java
for(Player p : Groups.player){
    if(p.isLocal() || p.con == null || !p.con.hasConnected) continue;
    ...
}
```

⇒ 无头服务端下**每个玩家都被判成 local 而跳过** ⇒ **一个实体快照都不发**。

**③ 表现**：`NetServer` 的三个路由计数器
（`diagTeamBatchSends` / `diagFullViewSends` / `diagSpectatorRouted`）恒为 **0**。
这三个计数器本来就是为这类问题留的诊断口，这次正好用上。

**正确修法** —— 改在 `SyncComp.update()`，而不是 `isLocal()`：

```java
// SyncComp.java:51
public void update(){
    // 服务端是权威方，一律不插值
    if(Vars.headless || Vars.net.server()) return;
    if((Vars.net.client() && !isLocal()) || isRemote()){
        interpolate();
    }
}
```

`EntityComp.isLocal()` 已**还原**成原版。

**验证**：90 秒零超时；计数器 `full=449 spec=449`；客户端 `net=up`；
建造单位移动无回归（55 格外 7 次轮询建成）。

**这条的教训**：改一个语义宽泛的判定函数（`isLocal()` / `isRemote()` / `isVisible()`）之前，
先把**所有调用点**列出来。我只看了一处 `SyncComp.update()`，而它在
`NetServer.sync()` 里还有一个**语义完全相反**的用途。用 grep 数调用点只要几秒。

**顺带修掉的**：

| 位置 | 问题 |
|---|---|
| `Logic.java:627` | `Logic.update()` 里**完全没有** `netServer.sync()` 调用（补上；不是超时的主因，但确实是缺失） |
| `AIArenaMod.java:61` | `viewTeamProvider` 从没注册过 —— 观战者切到真实队伍后会被 `sync()` 静默跳过 |
| `live-match.ps1` | 客户端缺 `-Djava.net.preferIPv4Stack=true`（服务端一直带着） |

---

## 5. 已知未解 / 待办

| 项 | 状态 |
|---|---|
| **单台煤矿机供不上「发电机 + 冶炼厂」** | 实测：发电机把煤烧光 → `powerStatus` 掉到 0 → 冶炼厂 `efficiency` 归零 → 整链停摆，核心硅卡在 5~27 之间反复。第二台煤机放在 (57,119) 但**没铺传送带**，自己 `{"coal":10}` 满仓 `eff=0.00` 堵死。**下一步：给第二台煤机铺线，或改用太阳能板分担** |
| 起步阶段的电源死循环 | `solar-panel` 要硅 8，硅又要电。**`combustion-generator`（铜 25 + 铅 15，不依赖硅）是唯一破局点**。拿到第一批硅后应尽快补太阳能板降低煤耗 |
| 传送带混料会永久堵死 | 朝向改过一次之后，旧朝向进去的异物会卡在带上不动。**改朝向必须连带拆掉重建那条带子**，否则整线哑火 |
| `Recorder` 在对局进行中写 0 字节文件 | 未解 |
| 服务端 `worldBuilds` 与客户端 `builds` 计数不一致 | `hiddenSnapshot` 只按 id 删除，可能有残留 |
| `/control?action=enter` 报 `Player attempted to control invalid unit` | 影子玩家的 `allowAction` 校验，未解。导致 AI 无法主动移动自己的单位 |
| 仓库未提交：观战架构、引擎补丁、`ai-client.py`、新端点、本文档 | 待整理 |

### 5.1 已经跑通的完整链条（作为基线）

`setup` → `host` → `start` 之后，纯手工操作 alpha 走通的路径：

```
沙机 (61,108) ──┐
                ├──> 硅冶炼厂 (59,108) ──> 出料带 (59,107) rot=3 ──> 核心
煤矿机 (59,118) ──┘         ↑
   传送带 x8 rot=3 (59,117→59,110)        │ 电
   router (59,111) ──> 发电机 (60,111) ────┘
                     └─> 入料带 (59,110) rot=3
```

关键点：
- 沙机**直连**冶炼厂（相邻即 dump，省一条带子）
- 入料带 `rot=3` 让冶炼厂**无法把硅往南漏**（`direction == 2` 拒收）
- 出料带 `rot=3` 从南边收硅、往北送核心（核心底边 y=106，冶炼厂顶边 y=108，正好差一格）
- 发电机与冶炼厂**相邻**即同属一个 `PowerGraph`，不需要节点；节点是留给远距离的

实测产出：核心 `{"copper":383,"lead":447,"silicon":27}`，硅在稳定增长。

---

## 6. 引擎补丁清单

改动都带中文注释说明「为什么」，不要静默回退。

| 文件 | 改动 | 原因 |
|---|---|---|
| `game/FogControl.java` | `TileChangeEvent` 处理器与 `forceUpdate()` 都改成**缺就建 `FogData`** | 否则地图加载后新建迷雾建筑的队伍永远拿不到数据 |
| `entities/comp/PlayerComp.java` | 加 `@NoSync boolean spectator`，`update()`/`checkSpawn()` 早退 | 观战者既不生成单位也不重生 |
| `core/NetServer.java` | 玩家清理守卫 `p.con != null`；`ViewTeamProvider`；全图快照 | 修复玩家被误踢 / 观战视角路由 |
| `net/NetworkIO.java` | `writeWorld` 对全图观战者跳过迷雾过滤 | 裁判视角 |
| `world/blocks/units/UnitFactory.java` | 已回退 | 物料必须真实消耗 |

**重建**：`gradlew.bat server:dist`（先杀 java，`JAVA_HOME` 指向 JDK17）。

---

## 7. 一句话总结

**这个项目里几乎每一个「看起来像渲染/网络/绑定的问题」，根因都在服务端某个静默丢弃数据的分支上。** 迷雾黑屏、AI 没视野、AI 不动 —— 三次都是同一个模式：一个条件判断把事件或对象默默丢掉了，而表象完全指向别处。

**先查数据在哪一步丢的，再查它为什么没到。**
