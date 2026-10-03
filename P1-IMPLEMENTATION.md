# AI 竞技场 · P1 实现报告

> 对应 `DESIGN.md` 第 9 节 P1。目标：打通「鉴权 → HTTP → 主线程 → 校验 → 引擎流水线」的完整链路。
>
> **结论：链路全部打通，方块经 HTTP 下令后真正落地。P1 验收标准达成。**

---

## 1. 交付物

```
C:\dsh\ai-arena\mod\
  mod.hjson                    name=ai-arena, main=aiarena.AIArenaMod
  ai-arena.jar                 26 KB（编译产物）
  src\aiarena\
    AIArenaMod.java            入口：配置加载 → 快照监听器 → HTTP 启动
    AIArena.java               配置解析 + token→Team 鉴权
    Json.java                  零依赖 JSON 输出（补全控制字符转义）
    Snapshot.java              主线程只读快照（volatile 引用整体替换）
    Actor.java                 写操作（可见性 → builder → addBuild）
    HttpApi.java               路由 + 端点 + 分页 + 统一信封
```

**部署位置**：`server-run/config/mods/ai-arena.jar`
**配置生成**：`server-run/config/ai-arena.json`（首次启动自动生成，含 3 个 agent 的随机 token）

---

## 2. 端点与验证结果

### 2.1 全部端点

```
GET  /ping                                      存活探测（无鉴权）
GET  /v1/{agent}/state                          只读快照
GET  /v1/{agent}/map?x=&y=&w=&h=                区域地图（视野过滤）
POST /v1/{agent}/place?x=&y=&block=&rot=&config= 下单建造
POST /v1/{agent}/break?x=&y=                     下单拆除
POST /v1/{agent}/config?x=&y=&value=             修改配置
GET  /v1/{admin}/setup?map=&fog=&units=          初始化对局（仅 admin）
```

### 2.2 鉴权验证（全部通过）

| 用例 | 结果 |
|---|---|
| 无 Authorization 头 | `401 {"ok":false,"code":1401,...}` ✅ |
| 错误 token | `401 {"ok":false,"code":1401,...}` ✅ |
| alpha 的 token 访问 beta 端点 | `403 {"ok":false,"code":1403,"error":"token does not belong to agent 'beta'"}` ✅ |
| 正确 token | `200` ✅ |
| 非 admin 调 setup | `403 {"error":"setup requires an admin token"}` ✅ |

### 2.3 `/place` 全部校验路径

| 用例 | 结果 |
|---|---|
| 视野外 (40,40) | `{"ok":false,"code":1005,"error":"target tile is not visible to team team#100"}` ✅ |
| 无建造单位 | `{"ok":false,"code":1005,"error":"team team#100 has no builder unit"}` ✅ |
| 未知方块 | `{"ok":false,"code":1002,"error":"unknown block: not-a-block"}` ✅ |
| 越界 | `{"ok":false,"code":1003,"error":"coordinates out of bounds"}` ✅ |
| 未开局 | `{"ok":false,"code":1005,"error":"game not in playing state"}` ✅ |
| **正常下单** | `{"ok":true,"data":{"message":"queued conveyor at (126,124) by poly; pending plans=1"}}` ✅ |
| **下单后真正落地** | `(96,100) conveyor team=team#100 build=True` ×3 ✅ |

### 2.4 `/map` 分页与视野

| 用例 | 结果 |
|---|---|
| 4×4 请求 | `200`，返回 16 格 ✅ |
| 100×100 请求 | `400 {"code":1004,"error":"region too large: 10000 tiles, max 4096 — split into smaller requests"}` ✅ |
| 视野内格子 | `{"visible":true,"floor":"stone","block":"stone-wall","team":"derelict","build":false}` ✅ |
| 视野外格子 | `{"visible":false,"discovered":false}`（不给方块与队伍）✅ |

### 2.5 `/state` 视野过滤

```
alpha 的 /state（fog=true）:
  units   → 只含视野内的单位（含自己队 + 视野内的敌队）
  buildings → 只有 3 个，而 worldBuilds=4（1 个在视野外被过滤）✅
  teams   → 所有队伍的公开信息（id/name/isAI/alive/cores）✅
```

**关键**：`alpha` 能看到 `team#101` 的单位 —— 两个 `poly` 相距 8 格，**在视野半径（40+ 格）内**，这是正确行为。

---

## 3. 实现要点

### 3.1 读写分离（DESIGN.md 5.2）

```
读 (state)   HTTP 线程直接读 Snapshot 的 volatile 引用 ── 零跨线程、零阻塞
读 (map)     经 postToGame() 回主线程取 tile 数据
写 (place…)  经 postToGame() 投递，带 3 秒超时
```

`postToGame` 的超时是必需的：主线程若因大战场卡住，无超时会让 HTTP 线程池被占满，整个接口失去响应；有超时则最多丢几个请求，服务仍可用。

### 3.2 快照分层

```java
// Snapshot.java —— 轻量状态每 tick，重量级列表 10 Hz
private static final int HEAVY_INTERVAL_TICKS = 6;   // ≈ 10 Hz @ 60 FPS
```

不可变对象 + `volatile` 引用整体替换，HTTP 线程读到的永远是某个完整版本。

### 3.3 鉴权

```java
// 恒定时间比较 + 遍历全部不提前退出，避免用响应时间泄露匹配位置
for (Agent a : agents) {
    if (MessageDigest.isEqual(a.tokenBytes, presented)) found = a;
}
```

token 缺失时自动生成 48 位 hex（`SecureRandom`）并写回配置，**不硬编码默认值**。

### 3.4 建造路径

```java
// Actor.place() 的三步，与 DESIGN.md 4.5 一致
1. Vars.fogControl.isVisibleTile(team, x, y)        ← 对称于「玩家点得到」
2. 找 canBuild() 的单位
3. builder.addBuild(new BuildPlan(x, y, rotation, block, config))
```

之后由引擎完成：`finalPlaceDst` 范围筛选 → 走过去 → `validPlace` → `hasAll` → `buildCounter` → `Call.beginPlace` → `ConstructBlock`。

---

## 4. 过程中查明的引擎行为

### 4.1 `loadMap` 不应用自定义规则

```java
Vars.world.loadMap(map, new Rules());
// 此时 state.rules 被地图自身规则覆盖
Vars.state.rules.pvp = true;          // 必须改 state.rules，不是传入的那个对象
Vars.state.rules.fog = true;
```

### 4.2 tick 只在 playing 状态前进

`world.resize()` 与 `loadMap()` 都不会让 tick 前进，`Time.run()` 也不触发。必须 `Vars.state.set(GameState.State.playing)`。

### 4.3 核心方块是 `BuildVisibility.coreZoneOnly`

```java
// Blocks.java:3127-3129
coreShard = new CoreBlock("core-shard"){{
    requirements(Category.effect, BuildVisibility.coreZoneOnly, with(Items.copper, 1000, Items.lead, 800));
    alwaysUnlocked = true;
```

`coreZoneOnly` 使 `Block.isHidden()` 返回 true（尽管 `unlockedNow()==true`），导致：

```
isHidden()=true → isVisible()=false → isPlaceable()=false → validPlace() 一律 false
```

**核心只能建在地图的 spawn 点附近。** 竞品方案：setup 作为管理员操作，直接检查「size×size 全为空地」后用 `tile.setBlock()` 放置，绕过 `validPlace`。

### 4.4 `Rules.isBanned` 的陷阱

```java
// Rules.java:330
public boolean isBanned(Block block){
    return blockWhitelist != bannedBlocks.contains(block);
}
```

若地图 tags 带入了 `blockWhitelist=true` 而 `bannedBlocks` 为空，则**每个方块都被判为 banned**。setup 中显式重置这两个字段。

### 4.5 无核心无法建造

```java
// BuilderComp.java:106-108
var core = core();
if((core == null && !infinite)) return;
```

**这是引擎自带的对等约束** —— 玩家没有核心时同样不能建造。AI 自动继承，无需额外实现。

### 4.6 `UnitType` 没有 `canBuild()`

`canBuild()` 定义在 `Unit`（实例）上，`UnitType` 用 `buildSpeed > 0f` 判断。选择建造单位时优先取 `mono` / `poly` / `mega`。

### 4.7 两个单位生成到同一坐标会互相顶掉

同一格生成两个单位时，只有一个能存活。setup 用 `takenSpots` 列表保证每个 agent 的生成点间隔 ≥8 格。

---

## 5. 未完成项

### 5.1 已解决 —— `/place` 下单后方块真正落地

**验收证据**（referee 的 admin 视角 `/map`）：

```
( 96,100) conveyor     team=team#100  build=True    ← AI 通过 HTTP 下令建造
( 96,101) conveyor     team=team#100  build=True
( 96,102) conveyor     team=team#100  build=True
(100,100) core-shard   team=team#100  build=True    ← alpha 的核心
(103, 97) core-shard   team=team#101  build=True    ← beta 的核心
(108,106) core-nucleus team=sharded   build=True    ← 地图自带
```

`/state` 报告 15 个建筑，三条 `conveyor` 全部在内。**P1 验收标准达成。**

#### 追查过程中定位的六个引擎行为

这一节值得完整记录，因为这六个行为互相关联，而且都不在文档里。

**① 核心方块的 `buildVisibility = coreZoneOnly`**

```java
// Blocks.java:3128
requirements(Category.effect, BuildVisibility.coreZoneOnly, with(Items.copper, 1000, Items.lead, 800));

// BuildVisibility.java:14
coreZoneOnly = new BuildVisibility(() -> Vars.indexer.isBlockPresent(Blocks.coreZone) || !Vars.state.isGame()),
```

判定依据是「地图上是否存在 `core-zone` 地板」。

**② `Block.isHidden()` 的两个条件**

```java
// Block.java:1542
public boolean isHidden(){
    return !buildVisibility.visible() && !state.rules.revealedBlocks.contains(this);
}
```

`rules.revealedBlocks` 是绕过 `buildVisibility` 的正规出口。加入核心后 `isHidden()` 变 false。

**③ `staticFog` 造成放置的鸡生蛋困境**

```java
// Build.java:252 —— validPlaceIgnoreUnits 的逐格检查
(state.rules.staticFog && state.rules.fog && !fogControl.isDiscovered(team, wx, wy)) ||
```

放核心需要「该格已被探索」，探索需要视野源，视野源又需要核心。新队伍从未探索过任何格子，这一条拒绝全图。

**解法**：放置期间临时 `staticFog = false`，放完立即恢复（探索记忆本身仍保留，不影响后续游玩）。

**④ `Rules.isBanned` 的白名单陷阱**

```java
// Rules.java:330
public boolean isBanned(Block block){
    return blockWhitelist != bannedBlocks.contains(block);
}
```

地图 tags 若带进 `blockWhitelist=true` 而 `bannedBlocks` 为空，**每个方块都被判为 banned**。

**⑤ `polygonCoreProtection` 封锁核心周围 50 格**

```java
// Rules.java:123 / :291 / :347
public float enemyCoreBuildRadius = 400f;
public boolean protectCores = true;

return !teams.get(team).protectCores ? 0f : enemyCoreBuildRadius + teams.get(team).extraCoreBuildRadius;
```

`Build.validPlaceIgnoreUnits:210` 会调用 `Teams.anyEnemyCoresWithinBuildRadius()`。小地图上全图都在保护圈内，初始放置核心前必须关闭。

**⑥ 无核心无法建造 —— 引擎自带的对等约束**

```java
// BuilderComp.java:106-108
var core = core();
if((core == null && !infinite)) return;
```

玩家没有核心时同样不能建造。**AI 自动继承这条约束，无需额外实现** —— 这是「走引擎流水线」这一设计决策的直接收益。

#### 附带修正：`Groups.build` 不可用于枚举建筑

```java
// 错误写法 —— 实测 4 个建筑只返回 1 个
for (Building b : Groups.build) { ... }

// 正确写法 —— TeamData.buildings 覆盖完整
for (var td : Vars.state.teams.present)
    for (Building b : td.buildings) { ... }
```

`Groups.build` 是给逻辑处理器准备的分组，索引方式与普通实体组不同。

### 5.2 官方 PvP 地图 —— 已查明并使用

**官方 PvP 地图硬编码在引擎里：**

```java
// Maps.java:41-42
/** Maps tagged as PvP */
private static String[] pvpMaps = {"veins", "glacier", "passage"};

// Maps.java:516-518
boolean pvp = !map.custom && Structs.contains(pvpMaps, map.file.nameWithoutExtension());
if(mode == Gamemode.survival || mode == Gamemode.attack || mode == Gamemode.sandbox) return !pvp;
if(mode == Gamemode.pvp) return map.custom || pvp;

// World.java:372-376 —— 引擎强制要求 PvP 图至少两个核心
}else if(checkRules.pvp){ //pvp maps need two cores to be valid
    if(state.teams.getActive().count(TeamData::hasCore) < 2){
        invalidMap = true;
        ui.showErrorMessage("@map.nospawn.pvp");
    }
}
```

注意这三张图被**排除在生存模式之外**（`return !pvp`）—— 它们就是为 PvP 而生的。

**实测每张图的核心布局：**

| 地图 | 尺寸 | 核心布局 |
|---|---|---|
| `Veins` | 350×200 | `core-nucleus` @ (61,104) `sharded` / (289,104) `crux` |
| `Glacier` | 150×250 | `core-nucleus` @ (81,26) `sharded` / (81,224) `crux`（纵向对称） |
| `Passage` | 500×120 | `core-foundation` ×5：`derelict` 1 + `sharded` 2 + `crux` 2 |

**setup 现在的行为**：加载地图后自动检测地图自带的带核心队伍（排除 `derelict`），
按顺序把非 admin agent 绑定过去，只为它们补一个建造单位，**不再自造核心**。

```
officialPvp=true, mapCoreTeams=[sharded,crux]
bind[alpha]->sharded; unit[alpha]=poly@58,101
bind[beta]->crux;     unit[beta]=poly@286,101

alpha: team=1(sharded) cores=2 alive=True
beta:  team=2(crux)    cores=2 alive=True
```

核心不够时才回退到自建核心的路径（`findCoreSpot` + `layCoreZone` + `validPlace`）。

### 5.3 换图相关的三个坑（已修）

**① `state.tick` 回退导致快照停止刷新**

```java
// 错误写法 —— loadMap 把 tick 重置为 0，而 lastHeavyTick 还留着上一局的 1500
boolean heavy = (lastHeavyTick < 0) || (tick - lastHeavyTick >= HEAVY_INTERVAL_TICKS);
// 0 - 1500 >= 6 恒为 false，快照永远返回上一张地图的数据

// 正确写法 —— 把回退本身当成刷新信号
boolean heavy = (lastHeavyTick < 0) || tick < lastHeavyTick
             || (tick - lastHeavyTick >= HEAVY_INTERVAL_TICKS);
```

**症状**：`setup` 日志里的坐标是正确的（直读实时世界），但 `/state` 一直报上一张地图的坐标 —— 在 150 宽的 `Glacier` 上报出了 `289` 这样的越界值。

**② `TeamData` 在换图后保留旧建筑的引用**

`loadMap` 重建世界，但 `TeamData.cores` / `TeamData.buildings` 仍持有上一张地图的 `Building`。
`TeamData` 没有 `reset()`，需手动清空：

```java
for (Team t : Team.all) {
    if (t == null) continue;
    var td = t.data();
    if (td == null) continue;
    td.cores.clear();
    td.buildings.clear();
}
```

**③ `teams.present` 需要下一帧才填充**

`state.set(playing)` 之后同一帧内读 `state.teams.present` 得到的是空的或残留的数据。
setup 因此改成两阶段：主线程 post 完成地图与规则设置，`Time.run(2f, ...)` 延后一帧再读队伍。

```java
Core.app.post(() -> {
    // 阶段 1：state.set(menu) → 清 TeamData → loadMap → 设规则 → state.set(playing)
    arc.util.Time.run(2f, () -> {
        // 阶段 2：读 teams.present → 绑定队伍 → 生成单位 → complete future
    });
});
// HTTP 线程等待 future，8 秒超时
```

---

## 6. 对 DESIGN.md 的修正

| 项 | 修正 |
|---|---|
| 4.5 建造路径 | 已实现，链路正确 |
| 5.2 主线程桥 | 读走快照、写走队列，已按设计实现 |
| **新增** | **核心方块的 `coreZoneOnly` 分类**（第 4.3 节），影响 setup 与 P7 地图制作 |
| **新增** | **`Rules.isBanned` 的白名单陷阱**（第 4.4 节），需在 setup 中重置 |
| **新增** | **无核心无法建造是引擎自带的对等约束**（第 4.5 节） |

---

## 附录 · 服务器运行方式

```powershell
# 构建 mod
$javac -encoding UTF-8 -cp server-release.jar -d classes src/aiarena/*.java
jar cf ai-arena.jar -C classes . ; jar uf ai-arena.jar mod.hjson

# 部署
Copy-Item ai-arena.jar server-run/config/mods/

# 启动
java -jar server-release.jar      # 工作目录 = server-run
# 数据目录自动为 ./config，mod 目录 ./config/mods，配置 ./config/ai-arena.json
```
