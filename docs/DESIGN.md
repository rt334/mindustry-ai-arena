# AI 竞技场 · 设计文档

> Mindustry 多人 PvP 环境下的多 AI 对抗系统。本文档是设计与实现的唯一事实源。
>
> **状态**：P0–P7 已实现并实测。服务器侧 33 个端点、压测 62/62 通过；
> 客户端观察者 Mod 编译通过但图形未实测，图形回放未做。余项见第 10 节。
> **所有技术结论均标注源码位置**，可逐条核对。未验证项集中在第 10 节。

---

## 0. 定位与目标

### 目标

让多个外部 AI 程序在同一张 Mindustry PvP 地图上互相对抗，并支持真人观战、裁判判定与赛后回放。

### 三条设计红线

1. **公平** —— AI 能看到和做到的，不多于同一队伍的人类玩家。
2. **零客户端**（AI 侧）—— AI 不跑游戏客户端，只通过 HTTP 与服务器 Mod 通信。
3. **数据即画面** —— 观战与回放共用服务器侧的同一套数据流与过滤逻辑。

### 非目标

- 不做 AI 决策算法（那是使用方的自由）
- 不做游戏视频录制渲染（回放以游戏内客户端形式呈现，不导出视频）
- 不兼容有真人玩家混战的对局（本设计假设所有参战方都是 AI；真人只能以观察者身份进入）

---

## 1. 架构总览

```
┌──────────────────────────────────────────────────────────┐
│  Dedicated Server (headless)  ~300 MB                    │
│  └── Mod「AI 竞技场」                                     │
│       ├── Gate     token → Team 鉴权（含特权标记）         │
│       ├── Reader   只读状态，过滤调引擎判定                │
│       ├── Actor    写操作，validPlace → 建造模拟           │
│       ├── Intel    「确认核心数据」状态机                  │
│       ├── Stream   统一事件流 ──→ SSE（实时）             │
│       │                        └─→ 文件（录像）           │
│       └── HTTP     :PORT  绑定 127.0.0.1                  │
└────────────────────┬─────────────────────────────────────┘
                     │ HTTP（本机或受控网络）
        ┌────────────┼────────────┬────────────┐
        ▼            ▼            ▼            ▼
      AI-1         AI-2         AI-3         AI-N         ← 纯外部进程
                                                         任意语言
                     │
                     │ SSE / 纯 HTTP
                     ▼
┌──────────────────────────────────────────────────────────┐
│  客户端 Mod「观察者」（跑在有画面的电脑上）                │
│    ├─ 实时观战   数据源=HTTP   视角=队视角 / 可切全图      │
│    ├─ 裁判       数据源=HTTP   视角=全图（特权）           │
│    └─ 回放       数据源=文件   时间线可控 + 事件标注       │
│    └─ 共用：只读输入拦截 + 自由相机 + 渲染 + 数据解析      │
└──────────────────────────────────────────────────────────┘
```

**为什么零客户端**：每 AI 一个 Mindustry 客户端进程约 400 MB（GL 上下文 + 全量资源），8 个 AI 就是 3.2 GB；服务器 Mod 方案单进程约 300 MB，且天然支持多 AI 共存。

---

## 2. 角色定义

| 角色 | 归属 | 单位 | 权限 | 实现要点 |
|---|---|---|---|---|
| **AI 玩家** | 一个独立 Team | 有 | 受全部对等约束 | 通过 HTTP 操作，见第 4 节 |
| **观战者** | **不属于任何有核心的 Team** | 无 | 只看，按队视角 | 见下 |
| **裁判** | `derelict` 队（无核心） | 无 | 全图 + intel 全可见 | 见下 |

### 观战者为什么必须「无核心队」

引擎会自动给无单位的玩家补一个单位：

```java
// PlayerComp.java:233-241
}else if((core = bestCore()) != null){
    deathTimer += Time.delta;
    if(deathTimer >= deathDelay){       // deathDelay = 60f（1 秒）
        core.requestSpawn(self());       // ← 1 秒后强制重生
        deathTimer = 0;
    }
}
```

所以观战者所属队伍**不能有核心**，否则 `bestCore()` 非空，1 秒后被塞一个单位，就不再是纯观察者。

### 观战者的相机

无单位时 `player.dead()` 为 true（`PlayerComp.java:322`：`return unit == null || !unit.isValid();`），进入自由相机分支：

```java
// DesktopInput.java:277-295
if(((player.dead() || state.isPaused() || detached) && ...)){
    if(input.keyDown(Binding.mouseMove)) panCam = true;
    Core.camera.position.add(...axis(Binding.moveX, Binding.moveY)...);   // 键盘平移
}
if(panCam){
    Core.camera.position.x += ...;                                        // 鼠标拖拽
    Core.camera.position.y += ...;
}
```

**键盘平移 + 鼠标拖拽天然可用**，只需补缩放与快速跳转。

### 接管的防护

三条接管路径（`InputHandler.java:770`、`:1006`、`:2149`）**全部要求同队**：

```java
// InputHandler.java:783
}else if(unit.isAI() && unit.team == player.team() && !unit.dead && unit.playerControllable()){
```

观战者/裁判不在战斗队伍中，**队伍判定天然挡住全部三条路径**。但仍需两道显式防护：

1. **不放入 `derelict`**（避免接管地图上可能存在的 `derelict` 单位）
2. **`allowAction` 钩子显式拒绝 `ActionType.control`**（纵深防御）

```java
// InputHandler.java:775 —— 引擎已提供服务器侧校验点
if(net.server() && (!state.rules.possessionAllowed
   || !netServer.admins.allowAction(player, ActionType.control, action -> action.unit = unit))){
    throw new ValidateException(player, "Player cannot control a unit.");
}
```

---

## 3. 规则配置

```java
rules.pvp            = true;    // 关键：使 Team.isAI() 恒 false
rules.fog            = true;    // 关键：迷雾生效，FogControl 可用
rules.staticFog      = true;    // 记住已探索区域
rules.cleanupDeadTeams = true;
rules.pvpAutoPause   = false;   // 不等玩家，AI 自动开局
rules.polygonCoreProtection = true;   // 默认 false，需显式开
```

### `rules.pvp` 是全局关键

```java
// Team.java:112 —— isAI() 的最后一项
public boolean isAI(){
    return (state.rules.waves || state.rules.attackMode || state.isCampaign())
           && this != state.rules.defaultTeam
           && !state.rules.pvp;                    // ← pvp 时恒 false
}

// FogControl.java:117 —— 迷雾判定的短路
public boolean isVisibleTile(Team team, int x, int y){
    if(!state.rules.fog || team == null || team.isAI()) return true;   // ← 靠 isAI() 放行 AI 队
    ...
}
```

**不开 `pvp` 的话，`FogControl` 会对 AI 队短路返回「全部可见」** —— 迷雾形同虚设。这是整个公平性设计的开关。

### 副作用已核查

| 位置 | 影响 | 判断 |
|---|---|---|
| `NetServer.java:58` | PvP 开启自动托管 | dedicated server 无妨 |
| `Logic.java:555` | `buildAi && !pvp` → 原版建造 AI 不跑 | 正合适 |
| `Logic.java:182/363` | 死队清理 + 胜负判定 | 需要 |
| `World.java:372` | **PvP 地图必须 ≥2 个核心**，否则 `@map.nospawn.pvp` | **建图时必须满足** |

---

## 4. 六项对等约束

这是本设计的核心。**AI 的可见与可为，必须严格等于同一队伍的人类玩家。**

### 4.1 实体可见性 —— 直接复用引擎判定

```java
for(Syncc entity : Groups.sync){
    if(entity.isSyncHidden(team)) continue;    // ← 与引擎 writeEntitySnapshotsTeam 同一函数
    // 读取该实体
}
```

**依据**：

```java
// NetServer.java:1154 —— 引擎自己的实体同步循环
for(Syncc entity : Groups.sync){
    if(entity.isSyncHidden(team)){ hiddenIds.add(entity.id()); continue; }
    writeEntity(entity, dataStream);
}

// Syncc.java:15 —— 公开接口
boolean isSyncHidden(Team team);

// UnitComp.java:216
public boolean isSyncHidden(Team team){
    //shooting reveals position so bullets can be seen
    return !isShooting() && inFogTo(team);
}
```

**不要复刻 `isSyncHidden` 的逻辑** —— 直接调用。这样 `isShooting` 特例、`isDiscovered` 静态迷雾、多格建筑逐格采样、大单位绕圈采样全部自动跟随，且结构上不可能与引擎产生偏差。

**注意**：`isSyncHidden` 的参数是 `Team` 而非 `Player`（`NetServer.java:1142` 的签名同样是 `Team`），即**同一队伍的所有玩家看到的完全一致**。这对 AI 是好事 —— 与「该队玩家」的可见集合天然等同。

### 4.2 地形可见性 —— `FogControl`

实体之外，地形（floor/overlay/block）需要另一套判定：

```java
Vars.fogControl.isVisibleTile(team, x, y)     // 当前可见
Vars.fogControl.isDiscovered(team, x, y)      // 曾经发现过（静态迷雾）
```

```java
// FogControl.java:117
public boolean isVisibleTile(Team team, int x, int y){
    if(!state.rules.fog || team == null || team.isAI()) return true;
    var data = data(team);
    if(data == null) return false;
    return data.read.get(Mathf.clamp(x, 0, ww-1) + Mathf.clamp(y, 0, wh-1) * ww);
}

// Vars.java:293 —— 公开全局单例
public static FogControl fogControl;
```

服务端的 `fogControl` 即权威值（`FogControl` 实现 `write(DataOutput)` / `read(DataInput)`，会同步给客户端），所以服务端判定与客户端玩家所见是同一份数据。

**`fogRadius` 单位为「格」**，证据：

```java
// FogControl.java:258-260 —— tx/ty 是格坐标
int tx = unit.tileX(), ty = unit.tileY(), pos = tx + ty * ww;
if(unit.type.fogRadius <= 0f) continue;
long event = FogEvent.get(tx, ty, (int)unit.type.fogRadius, team.team.id);
```

典型值：单位 25 / 40 格，建筑 1–6 格，核心类 34 格。

### 4.3 听觉 —— 无需处理（已论证）

```
Core.audio.falloff = 16000           // arc.audio.Audio 构造器
falloff = clamp(1 - max(dst²(pos, camera) - falloffOffset², 0) / 16000)
```

换算（`Vars.tilesize = 8`）：

| 音效 | 有效半径 |
|---|---|
| 普通 | `sqrt(16000)` = 126.5 单位 = **15.8 格** |
| `blockExplodeElectricBig`（offset 70） | 144.6 单位 = **18.1 格** |
| `explosionCore`（offset 100） | 161.2 单位 = **20.2 格** |

**单位视野最小 25 格 > 最大声学半径 20.2 格**。玩家听到的一切都在其视野范围内，声音不构成额外情报。

且 `SoundControl.java:368` 在 headless 下直接 return，服务器侧根本不播放声音。

**结论：不为 AI 模拟听觉。**

### 4.4 核心库存 —— 刻意偏离（须「确认核心数据」）

这是唯一一处**主动偏离**「与玩家完全一致」。

**原版行为**：所有队伍的核心库存无条件同步给每个客户端：

```java
// NetServer.java:1101-1107 —— writeStateSnapshot()
//block data isn't important, just send the items for each team, they're synced across cores
for(TeamData data : state.teams.present){
    if(data.cores.size() > 0){
        dataStream.writeByte(data.team.id);
        data.cores.first().items.write(dataWrites);      // ← 每队库存，发给所有人
    }
}
```

**改为「按视野给」**，详见第 6.2 节。

### 4.5 建造位置与速度 —— 走引擎流水线，自动对等

**结论先行：AI 的建造只做两件事 —— 可见性校验、把计划交给建造单位。其余全部由引擎完成。**

#### 引擎的建造流水线

```
BuildPlan  →  BuilderComp.updateBuildLogic()  →  Call.beginPlace()  →  ConstructBlock
（纯数据）    （范围/合法性/资源/速度）           （@Remote，网络广播）   （施工进度）
```

```java
// BuildPlan.java —— 三种构造器
public BuildPlan(int x, int y, int rotation, Block block)                 // 放置（自动规范朝向）
public BuildPlan(int x, int y, int rotation, Block block, Object config)  // 带配置
public BuildPlan(int x, int y)                                            // 拆除（自动 breaking = true）

// BuilderComp.java:272 —— 入队接口，Unit 实现
void addBuild(BuildPlan place);
```

```java
// BuilderComp.java:106-126 —— 引擎自动做的第一层
var core = core();
if((core == null && !infinite)) return;          // 无核心不能建造

float dst = plan.dst2(this);
boolean within = dst <= finalPlaceDst*finalPlaceDst;    // 建造范围筛选
```

```java
// BuilderComp.java:164-173 —— 引擎自动做的第二层
if(!current.initialized && !current.breaking && Build.validPlaceIgnoreUnits(...) && allowBuildCurrent){
    if(Build.checkNoUnitOverlap(...)){
        boolean hasAll = infinite || current.isRotation(team) ||
            !Structs.contains(current.block.requirements, i -> !core.items.has(i.item, ...));   // 资源检查
        if(hasAll){
            Call.beginPlace(self(), current.block, team, current.x, current.y, current.rotation, ...);
        }else{
            current.stuck = true;
        }
    }
}else if(!current.initialized && current.breaking && Build.validBreak(team, current.x, current.y)){
    Call.beginBreak(self(), team, current.x, current.y);
}
```

#### 关键：不能跳过 `BuilderComp` 直接调 `beginPlace`

```java
// Build.java:70-74 —— beginPlace 只做 validPlace 校验
@Remote(called = Loc.server)
public static void beginPlace(@Nullable Unit unit, Block result, Team team, int x, int y, int rotation, @Nullable Object placeConfig){
    if(!validPlace(result, team, x, y, rotation)){ return; }
    ...
}
```

**`beginPlace` 不检查资源，也不检查范围。** 资源检查（`hasAll`）、范围筛选（`finalPlaceDst`）、建造速度（`buildCounter`）**全在 `BuilderComp` 中**。直接调 `beginPlace` 会让 AI 凭空建造。

#### AI 的建造实现

```java
// 1. 可见性（对称于「玩家点得到」）
if(!Vars.fogControl.isVisibleTile(team, x, y)) return error;

// 2. 找队伍的建造单位
Unit builder = <队伍里 canBuild() 为 true 的单位>;
if(builder == null) return error;         // 无建造单位即无法建造 —— 与玩家一致

// 3. 入队，之后引擎全自动
builder.addBuild(new BuildPlan(x, y, rotation, block, config));

// 拆除同理 —— 两参数构造器自动 breaking = true
builder.addBuild(new BuildPlan(x, y));
```

**引擎随后自动完成**：范围筛选 → 单位走过去（`finalPlaceDst`）→ `validPlace` → `hasAll` 资源扣除 → `buildCounter` 速度控制 → `Call.beginPlace` 网络广播 → `ConstructBlock` 进度累积。

**四项对等约束一次满足**（建造位置、建造速度、资源消耗、网络同步），无需自行实现任何一项。

#### 关于「建造位置」的引擎事实
**引擎层面没有建造距离限制**：

```java
// Build.java:173
public static boolean validPlace(Block type, Team team, int x, int y, int rotation,
                                 boolean checkVisible, boolean checkCoreRadius){
    return validPlaceIgnoreUnits(...) && checkNoUnitOverlap(type, x, y);
}
```

`validPlaceIgnoreUnits` 内的检查只有：方块可建性、环境允许、核心保护半径。

```java
// Rules.java:127
/** When placeRangeCheck is enabled, this is the range checked for enemy blocks. */
public boolean placeRangeCheck = false;        // ← 默认关闭
```

`buildRange` 的实际用途仅是**建造计划的渲染指示器**：

```java
// InputHandler.java:1449
if(plan.progress > 0.01f || (current == plan && plan.initialized
   && (u.within(plan.x * tilesize, plan.y * tilesize, u.type.buildRange) || state.isEditor()))) continue;
```

**因此玩家「不能在视野外建造」的真正成因是输入层** —— 鼠标只能点镜头内的格子。

**AI 须显式补上这一环**：

```java
fogControl.isVisibleTile(team, x, y)      // 不含 isDiscovered
```

**为什么用「当前可见」而非「已探索」**：玩家要操作某处，必须把单位开过去（移动镜头 = 移动单位），达到时该处即为「当前可见」。已探索但单位不在的地方，玩家同样点不到。

#### 蓝图必须展开为 `BuildPlan`，不能用 `Schematics.place`

```java
// Schematics.java:520-533 —— 直接改世界，不走网络
public static void place(Schematic schem, int x, int y, Team team, boolean overwrite){
    schem.tiles.each(st -> {
        Tile tile = world.tile(st.x + ox, st.y + oy);
        if(tile == null || (!overwrite && !Build.validPlace(st.block, team, tile.x, tile.y, st.rotation))) return;
        tile.setBlock(st.block, team, st.rotation);        // ← 直接 setBlock
        ...
    });
}
```

**两个问题**：不走 `Call`，多人下必然 desync；`overwrite = true` 时连 `validPlace` 都跳过。

**正确路径**：

```
Schematics.readBase64(...)        ← 纯解析，可用，无副作用
  ↓ 逐格展开
builder.addBuild(new BuildPlan(...))   ← 每格都过完整引擎流水线
```

**好处**：绕过 `Schematics.place` 的同时完整保留对等约束（可见性、资源、速度）。**注意计划队列有上限**（`TypeIO.java:474` 的 `getMaxPlans`），大蓝图需分批。

#### 待建计划管理

```java
// InputHandler.java:536 —— 不需 Player，服务器侧可直接调
public static void removeQueueBlock(int x, int y, boolean breaking)

// TypeIO.java:474 —— 队列上限
public static int getMaxPlans(Queue<BuildPlan> plans)
```

`deletePlans(Player, int[])` 需要 `Player`（经影子 Player 可用），单个取消用 `removeQueueBlock` 更直接。

#### 拆除

```java
// BuilderComp.java:190-191 —— 引擎自动走 beginBreak
}else if(!current.initialized && current.breaking && Build.validBreak(team, current.x, current.y)){
    Call.beginBreak(self(), team, current.x, current.y);
}
```

同样只需两参数构造器入队。

### 4.6 指挥范围

```java
// InputHandler.java:331 —— 只检查队伍，无距离检查
if(unit != null && unit.team == player.team()){
    if(unit.controller() instanceof CommandAI ai){
```

玩家的实际限制是「能点选到」，即**镜头内**。**引擎对指挥没有任何范围检查** —— 这是六项对等约束里唯一必须自己实现的一条：

```
被指挥的单位   必须在【己方当前可见】范围内
指挥的目标位置 必须在【己方当前可见】范围内
```

```java
if(!fogControl.isVisibleTile(team, unit.tileX(), unit.tileY())) return error;
if(!fogControl.isVisibleTile(team, World.toTile(pos.x), World.toTile(pos.y))) return error;
```

### 4.7 `ActionType` 与影子 `Player`

#### 引擎的操作分类全集

`ActionType` 共 16 项，是引擎对「玩家操作」的完整分类：

```
breakBlock      placeBlock      rotate          configure
withdrawItem    depositItem     control         buildSelect
command         removePlanned   commandUnits    commandBuilding
respawn         pickupBlock     dropPayload     pingLocation
```

**设计原则**：AI 的每个写操作端点都映射到其中一个 `ActionType`，校验规则按 `ActionType` 组织。这样与玩家的权限模型一一对应，将来若加入真人玩家，同一套规则可统一适用。

#### 陷阱：`allowAction` 对服务器侧调用无条件放行

```java
// Administration.java:173-175
public boolean allowAction(Player player, ActionType type, Cons<PlayerAction> setter){
    //some actions are done by the server (null player) and thus are always allowed
    if(player == null) return true;          // ← 传 null 直接通过
    ...
}

// Administration.java:168
public boolean allowAction(Player player, ActionType type, Tile tile, Cons<PlayerAction> setter){
    return allowAction(player, type, action -> setter.get(action.set(player, type, tile)));
}
```

**服务器 Mod 若以 `null` 作为 player 调用，全部权限校验被跳过。**

#### 默认 `ActionFilter` 只管速率，不管范围

```java
// Administration.java:73-93 —— 唯一的默认交互 filter
addActionFilter(action -> {
    if(action.type != ActionType.breakBlock &&
        action.type != ActionType.placeBlock &&
        action.type != ActionType.commandUnits &&
        Config.antiSpam.bool() && !action.player.isLocal()){
        Ratekeeper rate = action.player.getInfo().rate;
        if(rate.allow(Config.interactRateWindow.num() * 1000L, Config.interactRateLimit.num())){
            return true;
        }
        return false;
    }
    return true;
});
```

**引擎没有统一的权限模型** —— 范围检查散落在各方法实现里。`ActionType` 只作分类用途。

#### 解法：影子 `Player`

```java
Player shadow = Player.create();       // 存在于服务端，不连接网络
shadow.team(aiTeam);                   // 绑定 AI 的队伍
shadow.set(x, y);                      // 位置可自由设定
```

收益：

- **所有需要 `Player` 参数的 `@Remote` 方法都能用** —— 包括 `commandUnits` / `setUnitCommand` / `setUnitStance` / `commandBuilding` / `requestItem` / `transferInventory`
- **`allowAction` 真正生效** —— 可挂自定义 `ActionFilter` 统一校验，一处实现覆盖全部 16 种操作，而不是在每个端点里重复写
- **引擎自带的距离检查自动生效** —— 如 `player.within(build, itemTransferRange)`（`itemTransferRange = 220f`，即 27.5 格）
- **AI 与真人走同一套校验**，不需要两套逻辑

**必须先验证**（已加入 P0，**实测结果见下**）：

1. 影子 `Player` 会不会出现在 `Groups.player` / 玩家列表
2. 会不会被计入胜负判定（`Logic.java:363` 的 `countAlive` 一类）
3. `player.set(x, y)` 能否自由设定位置（决定 `within(...)` 检查的结果）

#### ✅ P0 实测结果

| 项 | 结果 |
|---|---|
| `Player.create()` + `add()` | **会进入 `Groups.player`**（`size 0→1`），`remove()` 后回 0 |
| `team().data().players.size` | **保持 0** —— **不污染队伍统计**，胜负判定与死队清理不受影响 |
| `player.set(x, y)` | **生效**，设 (1234.5, 678.5) 读回一致 |
| `dead()` | `true`（无单位时，符合预期） |

**结论**：影子 Player 方案成立，但生命周期须明确 —— **按需创建、用后立即 `remove()`**。由于不影响 `players.size`，即使长期持有也不会破坏胜负判定，只是会出现在玩家列表遍历中。

#### 能直接调用的引擎操作

| 操作 | 引擎自带约束 | 服务器侧可直调 |
|---|---|---|
| 建造 / 拆除 | 范围 + 资源 + 速度（`BuilderComp`） | ✅ 经 `addBuild` |
| 建筑配置 `tileConfig` | `ActionType.configure` | ✅ `player` 可为 null |
| 旋转 `rotateBlock` | `ActionType.rotate` | ✅ `player` 可为 null |
| 建筑间转移 `transferItemTo` | 无距离（参数是 `Unit`） | ✅ 不需 `Player` |
| 取物品 `requestItem` | `player.within(build, 220f)` + `interactable` | ✅ 经影子 Player |
| 存物品 `transferInventory` | 同上 | ✅ 经影子 Player |
| 单位指挥 `commandUnits` | 队伍判定 | ✅ 经影子 Player |
| 设置指令 `setUnitCommand` / 姿态 `setUnitStance` | 队伍判定 | ✅ 经影子 Player |
| 指挥建筑 `commandBuilding` | 队伍判定 | ✅ 经影子 Player |
| **指挥范围** | **无** | ❌ **唯一须自行实现** |

### 4.8 逻辑处理器 —— 已核查，无法绕过视野

逻辑处理器（`LogicBuild`）允许在游戏内写代码读取世界状态，理论上可能是绕过迷雾的漏洞。**核查结论：不能绕过。**

```java
// Units.java:318-326 —— 雷达索敌
public static Unit bestEnemy(Team team, float x, float y, float range, Boolf<Unit> predicate, Sortf sort){
    if(team == Team.derelict) return null;
    nearbyEnemies(team, ..., e -> {
        if(e.dead() || !predicate.get(e) || e.team == Team.derelict
           || !e.within(x, y, range + e.hitSize/2f)
           || !e.targetable(team)
           || e.inFogTo(team)) return;          // ★ 视野过滤
        ...
    });
}
```

**逻辑的雷达指令走 `Units.bestEnemy`，它带 `inFogTo` 过滤。**

而 `sensor` 指令需要先有对象引用才能读取其属性，对象只能来自：

- `radar` —— 走 `bestEnemy`，**受过滤**
- `getlink` —— 自己的建筑
- `ucontrol` 相关 —— 自己控制的单位

**因此逻辑处理器拿不到视野外的对象，无法作弊。**

`RadarTarget` 的 8 个枚举只是分类谓词，不是过滤层：

```java
any / enemy / ally / player / attacker / flying / boss / ground
```

#### AI 使用逻辑处理器的方式

```java
// 逻辑代码就是建筑配置，走 tileConfig
Call.tileConfig(player, logicBuild, "代码字符串");
```

与玩家写逻辑处理器完全一致，**且不需要额外的对等约束**（引擎已保证）。

### 对等约束汇总

| 维度 | 玩家 | AI | 状态 |
|---|---|---|---|
| 能看到哪些实体 | `isSyncHidden(team)` | **同一函数** | ✅ 结构一致 |
| 能看到哪些地形 | `FogControl` | **同一函数** | ✅ 结构一致 |
| 能听到什么 | 声学半径 < 视野半径 | 无需处理 | ✅ 已论证无差异 |
| **核心库存** | 无条件全部可见 | **须「确认核心数据」** | ⚠️ 刻意偏离 |
| 建造位置 | 镜头内（= 可见） | 可见性校验 + 引擎流水线 | ✅ 已定方案 |
| 建造速度 | 单位 `buildSpeed` | **引擎自动**（`addBuild`） | ✅ 无需自实现 |
| 建造资源 | 核心库存扣除 | **引擎自动**（`hasAll`） | ✅ 无需自实现 |
| 取放物品范围 | `player.within(build, 220f)` | **引擎自带**（同函数） | ✅ 无需自实现 |
| 操作速率限制 | `ActionFilter` 速率门 | **引擎自带** | ✅ 无需自实现 |
| 逻辑处理器读数 | `Units.bestEnemy` + `inFogTo` | **引擎自带**（同函数） | ✅ 无法绕过视野 |
| **指挥范围** | 可见范围内可点选 | **须显式限制为可见** | ⚠️ 唯一要自实现 |

---

## 5. 关键技术机制

### 5.1 内嵌 HTTP

```java
com.sun.net.httpserver.HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0)
```

**已验证**：`-jar` 模式下 `jdk.httpserver` 直接可用，**不需要 `--add-modules`**（本机实测通过：启动服务、自测请求、正常停止）。

**只绑 `127.0.0.1`**，不接受改为 `0.0.0.0`。

### 5.2 主线程桥 —— 读写分离

**读不能走主线程队列**：`Core.app.post` 在下一帧执行，每个读请求至少延迟 1 帧；Future 等待会阻塞 HTTP 线程，AI 轮询地图时会耗尽线程池。

```
读:  主线程定期生成只读快照 ──→ HTTP 线程直接读（零跨线程，零阻塞）
写:  HTTP 线程投递任务 ──→ 主线程队列执行 ──→ 结果回传
```

快照分层：

| 数据 | 频率 | 理由 |
|---|---|---|
| tick / wave / 暂停 / 单位计数 | 每 tick | 极轻量 |
| 单位、建筑列表 | 10 Hz | AI 不需要 60 Hz |
| 地图 tile | 按需生成 + 分页 | 太大，不能周期刷 |

**写队列必须有每 tick 预算**（参考 `MindustryX` 的 1ms），否则批量铺方块会卡住游戏。

### 5.3 鉴权

```json
// config/ai-arena.json
{
  "port": 7199,
  "bind": "127.0.0.1",
  "rateLimit": { "perSecond": 60, "burst": 200 },
  "agents": [
    { "id": "alpha", "team": "sharded", "token": "<48字节随机>" },
    { "id": "beta",  "team": "blue",    "token": "<48字节随机>" }
  ]
}
```

四层防护：

1. **token → Team 映射** —— AI-1 的 token 只能操作队伍 1，跨队操作 403。这是主要防线，让作弊在协议层不可能。
2. **只绑 `127.0.0.1`** —— 配置里写死，不接受 `0.0.0.0`。
3. **恒定时间比较** —— `MessageDigest.isEqual` 类，避免时序侧信道。
4. **限流 + 审计日志** —— 按 agent 限流，记录每次操作的发起者、时间、目标格，可供回放与仲裁。

**token 不硬编码** —— 配置缺 token 时自动生成并写回，控制台打印一次。

### 5.4 队伍分配

```java
// Team.java:28-30, 43-56
public static final Team[] all = new Team[256];
public static final Team[] baseTeams = new Team[6];
static{
    for(int i = 7; i < all.length; i++){
        new Team(i, "team#" + i, Color.HSVtoRGB(...));    // 预建 250 个
    }
}
public static Team get(int id){ return all[((byte)id) & 0xff]; }
```

**250 个可用队伍**（`team#7` – `team#255`）。构造器是 `protected`，Mod 建不了新队，但现成的足够。

### 5.5 端口发现文件

多实例共存靠发现文件，而不是固定端口：

```
文件名:  bridge-<agentId>.json
内容:    port / pid / startedAt / heartbeat / version
写入:    启动时一次 + 每 5 秒心跳
读取:    先校验 pid 存活，失效则忽略
```

**必须带 pid 与心跳** —— 进程崩溃后遗留的陈旧文件会让 AI 连到死端口。

---

## 6. 契约

### 6.1 HTTP 端点

**共 33 个端点**（早期版本这里只列了 11 个，实现长出去之后没回写）。
逐条的参数与响应见 [`API.md`](API.md)，唯一事实源是 `mod/src/aiarena/HttpApi.java` 的
路由 `switch`。

```
读（GET，Bearer token）
  /v1/{agentId}/state                     局面：tick、队伍、核心、单位、建筑
  /v1/{agentId}/map?x=&y=&w=&h=&cursor=   地形（区域上限 4096 格，全图用 cursor 续传）
  /v1/{agentId}/units                     己方单位
  /v1/{agentId}/buildings                 己方建筑（含未完工）
  /v1/{agentId}/block?x=&y=               单格详情
  /v1/{agentId}/content                   方块 / 物品 / 单位表
  /v1/{agentId}/ore                       矿脉统计
  /v1/{agentId}/rates?window=<秒>         核心与全队产率
  /v1/{agentId}/stalls                    产线异常警报
  /v1/{agentId}/drill                     矿机明细
  /v1/{agentId}/factory                   单位工厂
  /v1/{agentId}/queue                     建造队列
  /v1/{agentId}/intel                     核心数据确认状态
  /v1/{agentId}/events?since=<seq>        事件流（游标轮询）
  /v1/{agentId}/database                  汇总数据库
  /v1/{agentId}/maps                      可用地图

写（POST）
  /v1/{agentId}/place                     下建造计划
  /v1/{agentId}/break                     拆除
  /v1/{agentId}/config                    设置方块配置
  /v1/{agentId}/command                   指挥（8 种 action）
  /v1/{agentId}/control                   直接操纵
                                          op = pos order warp enter release fire stopmove orders
  /v1/{agentId}/spawn                     生成单位
  /v1/{agentId}/mine                      让单位挖指定格
  /v1/{agentId}/chat                      发言

裁判（admin = true）
  /v1/{referee}/diag                      服务端诊断计数器
  /v1/{referee}/observe                   视角切换
  /v1/{referee}/record                    录像开关
  /v1/{referee}/setup?map=                加载地图 + 放核心 + 生成建造单位
  /v1/{referee}/host                      打开游戏端口 6567
  /v1/{referee}/start                     解除暂停
  /v1/{referee}/fog                       迷雾开关
  /v1/{referee}/admin                     在线玩家管理

无鉴权
  /ping                                   健康检查
```

统一响应信封：

```json
{"ok": true,  "data": {...}, "message": "...", "tick": 18432}
{"ok": false, "error": "...", "code": 1003,  "tick": 18432}
```

**失败一律用 `error` + `code`**，与成功响应的 `data` 对称：

```json
{"ok": false, "code": 1003, "error": "out of bounds: (700,700)"}
```

**实现与本节早期版本不一致，以实现为准。** 早期写「命令级失败用 `message`、
只有未捕获异常才用 `error`」—— 那是照搬 `eve-assistant` 的设计意图，而实际代码里
全部错误路径都走 `Json.error(code, msg)`。HTTP 状态码由 `statusFor` 从 `code` 推出来：

| code | HTTP | 含义 |
|---|---|---|
| 1001 / 1003 | 400 | 参数错 / 越界 |
| 1002 | 404 | 找不到 |
| 1004 | 429 | 队列或限流满 |
| 1005 / 1403 | 403 | 只读 / 权限不足 |
| 1006 | 410 | 游标过期 |
| 1007 | 504 | 主线程超时 |
| 1401 | 401 | 鉴权失败 |

**判失败要看 body 里的 `code`，不是 HTTP 状态码** —— 状态码只是给代理和日志看的粗分类。

错误码：

```
1001 bad_request      1002 not_found         1003 out_of_bounds
1004 queue_full       1005 read_only         1006 cursor_expired
1007 op_expired       1008 place_blocked     1009 place_invalid
1401 unauthorized     1403 forbidden         1500 internal_error

1008 -> HTTP 409（footprint 被占，挪一格即可）
1009 -> HTTP 400（引擎拒绝，重试无意义）
```

**分页（实现与早期设计不同）** —— 早期建议「按 1 MiB 阈值切 + `cursor_next`」，
实际是两条互补路径：

- **区域查询有硬上限**：`/map?x=&y=&w=&h=` 单次最多 **4096 格**，超出返回 `400`
- **全图查询用游标**：不传 `x/y/w/h` 时服务端按 `cursor` 分块返回，客户端续传到 `done`

两者都叫 `cursor`，区别是前者「你自己切块」、后者「服务端帮你切块」。

### 6.2 `/intel` —— 确认核心数据

#### 状态机

```
unknown ──[连续可见 10 秒，容错 0.5 秒]──→ confirmed
                                              │
                                              └─ 保存快照 { 库存明细, tick }，永久保留
                                                 再次确认 → 追加新快照（保留历史）
```

**两态，无失效，无保持时长。**

#### 参数

| 参数 | 值 | 理由 |
|---|---|---|
| **确认时长 N** | **10 秒（600 tick）** | 接近「一次成功的穿插」，而非「驻扎」 |
| **抖动容错** | **0.5 秒（30 tick）** | 见下 |
| **加速** | **无** | 多单位不加速 |
| **己方核心** | 全知 | 不走确认 |

#### 抖动容错是必需的

可见性每 tick 重算，视野边缘会出现瞬时丢失：

```
tick 100-339  可见
tick 340      不可见   ← 单位转了 1 度
tick 341-600  可见
```

**一次瞬时丢失就清零，会让机制在实际操作中几乎不可能完成。** 允许单次丢失 ≤ 0.5 秒，窗口内恢复继续累积；超过才清零。

30 tick 的理由：单位在正常速度下 0.5 秒移动不到一个视野半径的变化量，能覆盖绝大多数边界抖动；而真被打断（侦察兵被击杀、被赶走）通常远超此值。

#### 「察觉」不需要额外机制

防守方能看见敌方单位，这就是察觉。**加一个「你正在被侦察」的提示反而是额外免费情报，违背对等原则。** 整个反向提示系统不需要实现。

#### 实现

```java
for(Building core : 所有敌方核心){
    IntelState st = intel.computeIfAbsent(key(agentTeam, core.team));
    if(!core.inFogTo(agentTeam)){                 // ← 复用引擎判定
        st.visibleTicks++;
        st.lastSeenTick = state.tick;
        st.clearTicks = 0;
        if(st.visibleTicks >= 600 && st.state != CONFIRMED){
            st.state = CONFIRMED;
            st.confirmedAt = state.tick;
            Events.fire(new IntelConfirmedEvent(agentTeam, core.team));
        }
    }else{
        st.clearTicks++;
        if(st.clearTicks > 30){                    // ← 容错窗口
            if(st.visibleTicks > 0 && st.state == SCOUTING) st.visibleTicks = 0;
        }
    }
}
```

`inFogTo` 内部已含静态迷雾（`isDiscovered`）与逐格 `isVisibleTile` 两层检查，**一行调用拿到完整语义**。

#### 响应

```json
{
  "tick": 18432,
  "cores": [
    {
      "team": "crux",
      "snapshots": [
        { "tick": 6120,  "items": {"copper": 1000, "lead": 200}, "total": 1200 },
        { "tick": 18432, "items": {"copper": 4210, "lead": 1880, "silicon": 640}, "total": 6730 }
      ]
    },
    { "team": "blue", "scouting": { "progress": 0.62, "visibleTicks": 372 } },
    { "team": "malis", "state": "unknown" }
  ]
}
```

**保留历史快照而非覆盖** —— 两次读数的差额直接给出对方在此期间的经济增长，比单一读数有用得多。

**前提**：`/state` 里必须裁掉 `writeStateSnapshot` 的全量核心库存（只保留自己队）。

#### 边界情况

- **核心被摧毁** → 清空该队的全部 intel 状态
- **核心易主**（`changeTeam`）→ 视为全新核心，从 `unknown` 开始
- **多个 AI 侦察同一核心** → 各自独立计算，互不影响

### 6.3 事件与流

```
StateReader ──变更──→ 事件流 ──┬──→ SSE 推给观察者（实时）
                               └──→ Recorder 写文件（录像）
```

**同一份数据、同一个格式** —— 回放 Mod 不需要单独的解析器，事件标注零额外设计。

事件分级（必须分，否则时间轴会被淹没）：

```
关键事件（时间轴标记）—— 少而醒目
    core_destroyed · team_eliminated · game_over · wave_reached · intel_confirmed

常规事件（供重放）—— 多而低噪
    build · break · unit_spawn · unit_death · config_change · intel_scout_start
```

**不是所有事件都该进时间轴** —— 一小时录像会有几万条建造事件，全标上去等于没有标记。

---

## 7. 客户端观察者

### 三模式合一

三种角色的差别只是「数据源」与「视角权限」，其余完全重复：

| | 观战 | 裁判 | 回放 |
|---|---|---|---|
| 数据源 | HTTP 实时 | HTTP 实时 | **录像文件** |
| 视角 | 队视角 / 可切全图 | 全图 | 队视角 / 全图 |
| 相机 | 自由 | 自由 | 自由 + 跟随 |
| 时间控制 | 无 | 无 | **时间线** |
| 输入 | 禁用 | 禁用 | 禁用 |

**输入拦截、相机控制、渲染、数据解析四块共用。**

### 「只能看不能操作」的三重保障

1. **队伍判定**（引擎）—— 三条接管路径全部要求 `unit.team == player.team()`
2. **`allowAction` 钩子**（服务器）—— 显式拒绝 `ActionType.control`
3. **无单位**（引擎）—— 建造与指挥都要求 `player.unit()` 非空

### 禁用输入的具体手段

**不需要拦截输入事件** —— 「无单位 + 不在战斗队伍」已使建造、指挥、接管全部不可达。

### 回放

```
录制:  全量状态流（快照 + 增量），不按队录制
回放:  读取时按 view 参数过滤（复用服务器同一套 isSyncHidden / isVisibleTile）
seek:  定位到最近快照 → 重放增量到目标 tick
```

**录全量而非按队** —— 录制时不知道将来要看哪个视角。代价是体积（约 45 MB/小时全量），换来任意视角可回放与代码复用。

**实际实现是 JSON Lines**（`{"t":"meta"...}` / `{"t":"snap"...}` / `{"t":"ev"...}` / `{"t":"end"...}`）——
流式追加、崩溃时已写部分仍可解析、客户端用与实时同一套解析器逐行读；
方块只存增量（首次全量 + 后续变化）。

早先这里写「参考 `Ekrulan/replay-mod` 的二进制 + zip」是设计期的备选，实现时改了：
那个库本身 TODO 6 项未完成、无 LICENSE，且二进制格式会让实时与回放维护两套解析器。

**边界说明**：回放以游戏内客户端形式呈现，**不导出视频**。headless 服务器无 GL，无法渲染；若需视频，须额外增加带渲染的录制客户端（不在本设计范围）。

---

## 8. 调研结论：为什么自写

对 GitHub 上的现有方案做了完整调研，结论是**没有可复用的**。

### 观战 / 回放

| 项目 | 状况 |
|---|---|
| `Ekrulan/replay-mod` ★1 | 唯一叫「回放 mod」的。架构方向正确（`ReplaySnapshotter` + 二进制 + zip），但 **TODO 里 6 项未完成**，其中 2 项是核心（地图同步、播放控制）；`ReplaySnapshotter` 里快照间隔判断被注释掉（每 tick 都拍）；**无 LICENSE**。代码不可用，思路可借鉴 |
| `JiroCab/Caster-Ui-Java` ★5 | 解说 UI，**CC0-1.0**（可自由取用）。`CuiWorldRenderer` / `TeamBlackListerDialog` / `CuiTeamMangerDialog` 值得参考 |
| `Ferlern/extended-UI` ★39 | **MIT**，UI 增强，有「最佳 8 支队伍」概念，但是**上帝视角信息面板** |
| `Darkdustry-Coders/MDRCodec` | Rust 回放编解码器，属俄语社区服务器插件体系 |

**按队伍视角过滤：零项目涉及。** 现有观战项目都服务于真人解说员，假设观战者能看到全部，不需要公平性。

### AI 控制接口

| 项目 | 状况 |
|---|---|
| `ZenthXSin/eve-assistant` ★4 | 3 次提交全在一天内（2026-05-21），此后再无更新；1819 行；**无 LICENSE**；release 下载 11 次；构建不可复现（缺 `gradle-wrapper.jar`）。**把四个坑全踩了**：HTTP 线程直读直改世界（全仓 `app.post` 命中 0 处）、绕过引擎网络同步（全仓无 `Call.*`）、零鉴权（且带 `/api/run` + JS 控制台 = RCE）、强依赖 `Vars.player`（headless 下操作类命令全废） |
| `BEK-Group/MindustryX` fork ★2 | AI bridge **不在上游**（`TinyLake/MindustryX` 里 `AIBridge.java` 返回 404）。只存在于这个停更 fork，零 release、零文档、**零使用案例**。技术上更靠谱（有主线程 op 队列 + tick 预算、`place_block` 走 `validPlace` → `beginPlace` → `constructFinish`），但要编译整个游戏（Windows 需 WSL），且零鉴权、零视野过滤、无单位指挥、端口硬编码不支持多实例 |

### 可借鉴清单

- **建造序列**：`Build.validPlace` → `Build.beginPlace` → `ConstructBlock.constructFinish`
- **主线程调度**：op 队列 + 每 tick 预算（1ms 这个数值值得参考）
- **异步写模型**：`accepted + opId` + `await(opId)`，比同步请求-响应更适合游戏 tick 模型
- **事件类型命名**：`tile_changed` / `health_changed` / `world_load` / `reset` / `wave`
- **端点形状**：单一入口 + 动作表 + 统一信封（极省 token）
- **蓝图用引擎原生 base64 格式**（`Vars.schematics.writeBase64` / `Schematics.readBase64`）
- **手写极简 JSON**（`CommandResult` 式，零依赖）—— 但须补 `\r` `\t` 与控制字符转义
- **no-render 宿主**：`Vars.disableRender` + `Renderer.update()` 提前 return

---

## 9. 工程分阶段设计

### 依赖关系

```
P0 技术验证
   │
   ▼
P1 最简闭环
   │
   ▼
P2 对等约束 ────────┐
   │                │
   ▼                ▼
P3 信息 API      P5 观战与裁判
   │                │
   ▼                ▼
P4 操作 API      P6 回放
   │                │
   └────────┬───────┘
            ▼
        P7 编排与场景
```

**P3 / P4 可并行**（都依赖 P2）。P5 依赖 P2 的过滤层，P6 依赖 P5 的流。

---

### P0 · 技术验证（Spike）—— ✅ 已完成

**结论：全部通过。详细报告见 [`P0-VERIFICATION.md`](phases/P0-VERIFICATION.md)。**

| # | 待验证 | 结果 |
|---|---|---|
| 1 | headless 服务器能否加载 Mod | ✅ **PASS** |
| 2 | `Core.app.post` 在 `HeadlessApplication` 下是否执行队列 | ✅ **PASS**（42 ms） |
| 3 | ~~服务器改世界后客户端是否收到~~ | ✅ **已消除**（走 `addBuild → BuilderComp → Call.beginPlace`） |
| 4 | 自定义 `Team.get(id)` 可用 | ✅ **PASS**（256 队全部非空） |
| 5 | 影子 `Player` 是否进 `Groups.player` | ⚠️ **会进入**，`remove()` 可清除 |
| 6 | 影子 `Player` 是否计入胜负判定 | ✅ **PASS**（`players.size = 0`，不污染） |
| 7 | `player.set(x, y)` 能否自由设定 | ✅ **PASS** |

**附加验证**（超出原计划，全部 PASS）：内嵌 HTTP 在 headless 下可用、`Core.app.post` 回主线程处理 HTTP 请求、`state.set(playing)` 后 tick 前进、`pvp=true → isAI()=false`、`FogControl` 服务器侧可用、世界数据可读、`BuildPlan` 构造器可用。

**实测修正的三条实现要求**：

```java
// ① loadMap 不应用自定义规则，必须显式设置 state.rules
Vars.world.loadMap(map, new Rules());
Vars.state.rules.pvp = true;          // 改 state.rules，不是传入的那个对象
Vars.state.rules.fog = true;

// ② tick 只有 playing 状态才前进，Time.run 同理
Vars.state.set(GameState.State.playing);

// ③ 影子 Player 要「按需创建 + 用后 remove」
Player shadow = Player.create();
shadow.team(Team.get(id));
// ... 调用需要 Player 的方法 ...
shadow.remove();                       // 否则会留在 Groups.player
```

**验证产物**：`verify/`（Mod 源码 + jar）、`server-run/`（服务器运行目录）。

**为什么必须先做**：这四项决定了架构能否成立。若在第 3 项失败，P1 的设计就要推翻。

---

### P1 · 最简闭环 —— ✅ 已完成

**结论：链路全部打通。详见 [`P1-IMPLEMENTATION.md`](phases/P1-IMPLEMENTATION.md)。**

**交付**（`mod/src/aiarena/`，约 1,300 行）：

```
AIArenaMod.java    入口：配置 → 快照监听器 → HTTP
AIArena.java       配置解析 + token→Team 鉴权（恒定时间比较）
Json.java          零依赖 JSON（补全控制字符转义）
Snapshot.java      主线程只读快照（volatile 引用整体替换）
Actor.java         写操作（可见性 → builder → addBuild）
HttpApi.java       路由 + 分页 + 统一信封 + setup
```

**端点**：

```
GET  /ping                                      存活探测（无鉴权）
GET  /v1/{agent}/state                          只读快照（读 Snapshot，不回主线程）
GET  /v1/{agent}/map?x=&y=&w=&h=                区域地图（视野过滤，上限 4096 格）
POST /v1/{agent}/place?x=&y=&block=&rot=&config=
POST /v1/{agent}/break?x=&y=
POST /v1/{agent}/config?x=&y=&value=
GET  /v1/{admin}/setup?map=&fog=&units=          初始化对局（仅 admin）
```

**验证结果**（真实 headless 服务器）：

| 项 | 结果 |
|---|---|
| 鉴权：无 token / 错 token / 跨 agent | 401 / 401 / 403 ✅ |
| `/place` 视野外 / 无单位 / 未知方块 / 越界 / 未开局 | 1005 / 1005 / 1002 / 1003 / 1005 ✅ |
| `/place` 正常下单 | `queued conveyor at (96,100) by poly; pending plans=1` ✅ |
| **`/place` → 方块真正落地** | **`(96,100) conveyor team=team#100 build=True` ×3** ✅ |
| `/map` 分页上限 | 100×100 → `400 code:1004` ✅ |
| `/map` 视野过滤 | 视野内给方块+队伍，视野外只给 `discovered` ✅ |
| `/state` 实体列表 | 15 个建筑完整枚举 ✅ |
| `setup` 初始化对局 | 三队 `cores:1`、`alive:true`、各一个建造单位 ✅ |

**完整链路的端到端证据**（referee 的 admin 视角 `/map`）：

```
( 96,100) conveyor     team=team#100  build=True    ← AI 下令建造的方块
(100,100) core-shard   team=team#100  build=True    ← alpha 的核心
(103, 97) core-shard   team=team#101  build=True    ← beta 的核心
(108,106) core-nucleus team=sharded   build=True    ← 地图自带
```

同步定型（后续端点必须遵守）：统一响应信封、错误码分档、分页上限、鉴权中间件、快照分层与刷新频率。

**过程中的九项引擎发现**（已写入报告）：

1. **核心方块的 `buildVisibility = coreZoneOnly`** —— 需要地图上有 `Blocks.coreZone` 地板才能通过 `validPlace`
2. **`Block.isHidden()` 的两个条件** —— `!buildVisibility.visible() && !state.rules.revealedBlocks.contains(this)`，后者是正规出口
3. **`staticFog` 造成放置的鸡生蛋困境** —— `validPlaceIgnoreUnits` 要求目标格 `isDiscovered`，而探索需要视野源，视野源又需要核心
4. **`Rules.isBanned` 的白名单陷阱** —— `blockWhitelist=true` + 空 `bannedBlocks` 会禁掉一切方块
5. **`polygonCoreProtection` 会封锁核心周围 50 格** —— 初始放置前必须关闭
6. **无核心无法建造是引擎自带的对等约束** —— `BuilderComp` 里 `if((core == null && !infinite)) return;`，AI 自动继承
7. **官方 PvP 地图是 `veins` / `glacier` / `passage`** —— `Maps.pvpMaps` 硬编码，且被排除在生存模式之外；`World.java:372` 强制要求 PvP 图 ≥2 个核心
8. **`state.tick` 换图后回退会让快照停止刷新** —— `lastHeavyTick` 保留旧值，`tick - lastHeavyTick` 变负数，条件永不成立
9. **`TeamData` 与 `teams.present` 的换图时序** —— 前者保留旧建筑引用需手动清空，后者要延后一帧才填充

**另两处修正**：
- `Groups.build` 不可用于枚举建筑（给逻辑处理器准备的分组，实测 4 个建筑只返回 1 个），改用 `TeamData.buildings`
- `setup` 改为两阶段跨帧执行（`Core.app.post` + `Time.run(2f)`）

**官方 PvP 地图实测布局**：

| 地图 | 尺寸 | 核心布局 |
|---|---|---|
| `Veins` | 350×200 | `core-nucleus` @ (61,104) `sharded` / (289,104) `crux` |
| `Glacier` | 150×250 | `core-nucleus` @ (81,26) `sharded` / (81,224) `crux`（纵向对称） |
| `Passage` | 500×120 | `core-foundation` ×5：`derelict` 1 + `sharded` 2 + `crux` 2 |

setup 加载地图后自动检测自带核心的队伍（排除 `derelict`），把 agent 绑定过去，
只为它们补建造单位，不再自造核心。

---

### P2 · 对等约束 —— ✅ 已完成

**结论：11 条约束全部落地，其中唯一需自实现的「指挥范围」已实测生效。详见 [`P2-IMPLEMENTATION.md`](phases/P2-IMPLEMENTATION.md)。**

**新增交付**：`Shadow.java`（影子 Player 池）、`Commander.java`（指挥 + 范围约束）、`Intel.java`（核心数据确认状态机）。

**新增端点**：

```
GET  /v1/{agent}/units                        单位列表（视野过滤）
GET  /v1/{agent}/buildings                    建筑列表（视野过滤）
GET  /v1/{agent}/content                      可建方块 / 物品 / 指令 / 姿态
GET  /v1/{agent}/intel                        核心数据情报
POST /v1/{agent}/command?action=...           8 种指挥操作
POST /v1/{agent}/control?op=...               进入/退出单位与直接操纵
```

**11 条约束落地状态**：

| # | 约束 | 实现方式 |
|---|---|---|
| 1-2 | 实体 / 地形可见性 | `FogControl` 复用引擎判定（P1） |
| 3 | 听觉 | 无需处理（声学半径 20.2 格 < 最小视野 25 格） |
| 4 | 核心库存 | `/intel` 确认状态机 |
| 5 | 建造位置与速度 | `BuilderComp` 自动（P1 已验证） |
| **6** | **指挥范围** | **自行实现 —— 实测生效** |
| 7-10 | 建造范围 / 资源 / 移动 / 攻击 | 引擎自动 |
| 11 | 逻辑处理器 | 已核查无法绕过视野 |

**指挥范围实测**：

```
move 到视野内 (+4,+4)  → {"ok":true,"message":"commanded 1 unit(s) to position"}
move 到视野外 (5,5)    → {"ok":false,"code":1005,
                          "error":"target at tile(5,5) is not visible to sharded"}
```

单位确实按指令移动（468,814 → 489,818）。

**过程中发现的两个 API 陷阱**：

1. **`FogControl` 两个重载的坐标单位不同** —— `isVisibleTile(team, int, int)` 收格坐标，`isVisible(team, float, float)` 收世界坐标（像素）。混用导致相邻 8 格的目标被判为不可见。
2. **`UnitCommand` / `UnitStance` 的静态字段由 `init()` 赋值** —— 不能在静态初始化块里缓存，必须运行时读取。

**待实际对局验证**：`/intel` 状态机的完整推进需要真实侦察过程（单位在敌方核心视野内持续 10 秒）。

---

### P3 · 信息 API —— ✅ 已完成

**结论：信息 API 完整，事件流可用且遵守视野约束。详见 [`P3-IMPLEMENTATION.md`](phases/P3-IMPLEMENTATION.md)。**

**字段补全**：

- `/units` 加 `stack`（携带物）、`command`（当前指令）、`controller`
- `/buildings` 加 `items`、`liquids`、`config`、`constructing` + `buildProgress`
- `/content` 加 `units`（56 种，含 `fogRadius` / `buildSpeed` / `flying`）、`liquids`（10 种）

**`/events` 事件流**：

```
GET /v1/{agent}/events?since=<seq>&limit=<n>
→ {"nextSince":5,"count":5,"buffered":5,"events":[...]}
→ 游标被淘汰时 410 code:1006 cursor_expired，调用方重置 since=0
```

来源是**引擎监听 + 差分补齐**双路：

| 来源 | 事件 |
|---|---|
| 引擎监听（9 类） | unitCreate / unitDestroy / blockPlace / blockBreak / blockDestroy / configure / coreChange / wave / gameOver |
| 差分补齐（4 类） | unitAppear / unitGone / buildAppear / buildGone |

**为什么必须有差分补齐**：`UnitCreateEvent` 全代码库只在 5 处触发（`UnitSpawnAbility` / `PayloadSource` / `Reconstructor` / `UnitAssembler` / `UnitFactory`）—— **核心生产单位和直接 spawn 都不触发**。只靠引擎事件，AI 不会知道敌方出现了新单位。

事件按观察方视野过滤：己方事件无条件可见，敌方事件需在视野内，裁判全见。

**`/map` 分页协议**：

```
区域模式   /map?x=&y=&w=&h=        w*h ≤ 4096
全图模式   /map                    → cursor_next="0,1"
           /map?cursor=<token>     → 续传，null 表示扫完
```

**过程中发现的两个 API 陷阱**：

1. **`UnitCreateEvent` 覆盖不全**（见上）
2. **`TileChangeEvent` / `TilePreChangeEvent` / `BuildDamageEvent` 的实例是复用的** —— 监听器里必须立即抄出字段，绝不能缓存事件对象引用

---

### P4 · 操作 API —— ✅ 已完成

**结论：操作 API 完整，批量建造端到端实测通过（40 个方块全部落地）。详见 [`P4-IMPLEMENTATION.md`](phases/P4-IMPLEMENTATION.md)。**

**形状批量**：

```
POST /place?shape=line|area|rect|outline|circle|point&x1=&y1=&x2=&y2=&radius=&block=
POST /break?...                                             参数同上
POST /spawn?type=<unitType>&x=&y=                           生成单位
POST /chat?text=...                                         发送消息
GET  /queue  /  POST /queue?clear=true                      建造队列
```

**批量不是「直接改一片世界」** —— 每一格都走 `Actor.place` 的完整校验链（可见性 → 建造单位 → `addBuild`），由引擎决定哪些真的能建。返回值如实报告跳过原因：

```json
{"message":"batch requested=16 accepted=16 skipped[invisible=0,invalid=0,noUnit=0]"}
```

**两个硬性上限**：单次批量 200 格（超出拒绝而非静默截断）、单单位计划队列 60。

**实测**：

```
line 5 格 → accepted=5      area 3x3 → accepted=9
circle r=2 → accepted=13    outline 5x5 → accepted=16
900 格 → {"code":1004,"error":"batch too large: 900 tiles, max 200"}
spawn mono → {"message":"spawned mono id=235 at tile(61,104) pop=2/24"}
/buildings → conveyor x40   ← 全部落地
```

**过程中的三项引擎发现**：

1. **引擎里从核心生成单位不消耗资源** —— `CoreBlock.requestSpawn` 只检查 `supportsEnv` 与 `allowSpawn`。自行加资源检查会让 AI 弱于玩家，破坏对等。
2. **`UnitType` 没有 `requirements` / `unitCapModifier`** —— 前者只存在于 `UnitFactory`，后者是 `CoreBlock` 的字段。
3. **`Call.sendMessage` 有三个重载**：`(String)` / `(String, String, Player)` / `(NetConnection, String, String, ...)`。

---

### P5 · 观战与裁判 —— ✅ 已完成

**结论：服务器侧视角切换与裁判特权完整实测；客户端观察者 Mod 编译通过。详见 [`P5-IMPLEMENTATION.md`](phases/P5-IMPLEMENTATION.md)。**

**服务器侧**：所有只读端点支持 `view` 参数

```
?view=own        自己的队伍视角（默认）
?view=<teamId>   指定队伍视角
?view=all        上帝视角 —— 仅 admin
```

**非 admin 请求别人的视角会被静默降级为自己的视角，而不是报错** —— AI 无法通过试错探测出自己无权访问哪些视角。

**观战不走引擎实体同步**（规避 `hiddenIds` 闪烁风险），完全走 HTTP。因此观察者**不需要在服务器上有队伍** —— 没有实体就没有身份问题。

**实测**：

```
referee view=all → team=-1，看到两个队的核心
alpha   view=all → team=1，降级为 sharded
referee view=2   → team=2，只看到 crux 的核心（items 为空）
referee view=1   → team=1，只看到 sharded 的核心（2000×10）
```

**客户端 Mod**（`observer/`）：自由相机（WASD / 中键拖拽 / 滚轮）、`Tab` 循环队伍跳转、`F1` 帮助。
只读 —— 无任何写操作。缩放复用引擎的 `Vars.renderer.scaleCamera()`。

**过程中的四个 API 细节**：`Core.camera` 没有 `zoom` 字段（用 `Vars.renderer.scaleCamera()`）；`KeyCode.mouseMiddle`；arc 的鼠标坐标是方法（`mouseX()`）；`arc.util.Scl` 不存在。

---

### P6 · 回放 —— 服务器侧 ✅ / 客户端回放待做

**服务器侧已完整实现并实测。详见 [`P7-IMPLEMENTATION.md`](phases/P7-IMPLEMENTATION.md) 第 7 节。**

```
POST /v1/{admin}/record?action=start&label=veins
GET  /v1/{admin}/record                    状态 + 文件列表
GET  /v1/{admin}/record?action=download&name=<file>
```

**格式**：JSON Lines，`{"t":"meta"}` / `{"t":"snap"}` / `{"t":"ev"}` / `{"t":"end"}`。
方块只存增量（首次全量 + 后续变化）。实测 10 秒产生 18 行。

**为什么用 JSONL**：流式追加写、崩溃时已写部分仍可解析、客户端用与实时同一套解析器逐行读。

**未完成**：客户端图形回放（加载文件 → 时间线拖动 → 历史状态渲染）。这需要替换 `Vars.world` 并按快照重建世界，是独立的渲染层工程。服务器侧的录制、存储、下载均已就绪。

---

### P7 · 编排与场景 —— ✅ 已完成

**结论：验收标准达成 —— `.\start-arena.ps1 -Agents 4 -Map passage` 起一局，四个 AI 各自就位。详见 [`P7-IMPLEMENTATION.md`](phases/P7-IMPLEMENTATION.md)。**

```powershell
.\start-arena.ps1                              默认 2 个 AI，veins 地图
.\start-arena.ps1 -Agents 4 -Map passage       4 个 AI
.\start-arena.ps1 -Record                      开局即开始录像
.\start-arena.ps1 -Fog:$false                  关闭迷雾（调试）
.\start-arena.ps1 -KeepRunning                 前台监控
```

**自动补足 agent**：参战 agent 不足时生成新 agent + 随机 token，重启服务器加载。

**实测**：

```
配置里只有 2 个参战 agent，自动补足到 4
  新增 agent3  team=102  token=6032f96d...
  新增 agent4  team=103  token=ac19a550...

bind[alpha]->sharded@141,63     ← 地图自带核心
bind[beta]->crux@353,63         ← 地图自带核心
core[agent3]@250,60             ← 自建核心
core[agent4]@253,57             ← 自建核心

视角隔离：alpha 看到 1 个（自己）；agent3/agent4 互相看到（核心相距 3 格）；裁判看到 4 个
```

**两个方向相反的编码坑**：

| 对象 | 要求 | 原因 |
|---|---|---|
| `.ps1` 脚本 | **UTF-8 with BOM** | 无 BOM 时 PowerShell 按 ANSI 解码，中文乱码吞掉引号 |
| JSON 配置 | **UTF-8 without BOM** | 有 BOM 时 Java 的 `Jval` 解析失败，所有 token 变空 |

Mod 侧读配置时主动剥离 BOM 作为双保险。

---

### 压力测试发现的并发缺陷（已修）

**`arc.struct.Seq` 的迭代器不是线程安全的。**

```java
// 错误：agents 是 Seq，authenticate 里每个请求都遍历它
public static final Seq<Agent> agents = new Seq<>();
for (Agent a : agents) { ... }        // 并发下抛 NoSuchElementException

// 正确：agents 只在启动时写一次、之后纯读
public static final java.util.List<Agent> agents = new CopyOnWriteArrayList<>();
```

失败率与并发数成正比（12 线程 1.7%、24 线程 2.9%），因为每个请求都要过鉴权。

**排查教训**：`t.printStackTrace()` 走 `System.err` 而 `Log.info` 走 stdout —— 只看 stdout 只能看到 `NoSuchElementException: 5` 这样的消息（数字是索引，无信息量），必须看 stderr 才能拿到调用链。

**附带改进**：HTTP 线程池 4 → 16（可配置）；backlog 0 → 128；视野查询加 `safeVisible` 系列兜底（`FogControl` 同样非线程安全，兜底方向是「宁可少看，不可多看」）。

配置：
```json
{ "http": { "threads": 16, "backlog": 128 } }
```

**压测结果**：62/62 用例通过，24 线程并发 960/960 零失败。详见 `STRESS-TEST.md`。

---
### 全项目状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | 技术验证（7 项） | ✅ |
| P1 | 最简闭环 | ✅ |
| P2 | 对等约束（11 条） | ✅ |
| P3 | 信息 API | ✅ |
| P4 | 操作 API | ✅ |
| P5 | 观战与裁判 | ✅ 服务器侧 + 客户端 Mod 编译通过 |
| P6 | 回放 | ✅ 服务器侧；客户端图形回放待做 |
| P7 | 编排与场景 | ✅ |

**端点总计 18 个**，服务器 Mod 77,785 B，客户端 Mod 5,621 B。

---

### 工作量汇总

| 阶段 | 规模 | 可否单会话完成 |
|---|---|---|
| P0 技术验证 | ~100 行 + 报告 | ✅ |
| P1 最简闭环 | 400–600 | ✅ |
| P2 对等约束 | 250–350 | ✅ |
| P3 信息 API | 500–800 | ✅ |
| P4 操作 API | 500–800 | 偏紧 |
| P5 观战与裁判 | 550–950 | 偏紧 |
| P6 回放 | 850–1400 | ❌ |
| P7 编排 | 200–300 + 配置 | ✅ |
| **合计** | **3350–5300 行** | —— |

**跨会话注意事项**：单次会话超过约 800 次工具调用会触发上下文压缩，早期细节会丢失。**每个阶段结束时必须把状态落成文件**（本设计文档 + 代码），下一阶段靠读文件续接，而非依赖记忆。

---

## 10. 待验证清单

### P0 已完成 ✅

**七项全部有答案，详见 [`P0-VERIFICATION.md`](phases/P0-VERIFICATION.md)。** 唯一需要留意的实测结果是「影子 Player 会进入 `Groups.player`（但 `players.size` 不受影响）」，处理方式为按需创建、用后 `remove()`。

P0 §3 另有三项因测试地图配置未跑通（自定义核心放置、生成单位 + 视野、`addBuild` 端到端），
**已在 P1 §5.2 与 P7 §3 闭环** —— 走官方 PvP 地图 + `findCoreSpot + layCoreZone` 自建核心。

### 后续阶段的风险项

| 项 | 阶段 | 状态 |
|---|---|---|
| PvP 地图需自制 | P5/P7 | **已解决，不必自制** —— 实测直接用引擎硬编码的 `veins` / `glacier` / `passage`，配合 `findCoreSpot + layCoreZone` 自行放核心即可（[P7](phases/P7-IMPLEMENTATION.md) §3 四队就位实测通过）。早期「内置 18 张都是生存地形、须自制」的结论只对「直接用内置图的 spawn」成立 |
| `writeCustomEntitySnapshot` 与 `hiddenIds` 是否打架 | P5 | **已绕开** —— 裁判不走引擎实体同步，改走 HTTP 数据源（[P5](phases/P5-IMPLEMENTATION.md) §3），该风险不再相关 |
| 快照频率与体积的平衡 | P6 | **仍未测** —— 只有 10 秒 / 18 行的短测，「约 45 MB/小时」是按快照间隔估的，长局未验证 |
| 建造流水线的完整链路 | P1 | **已闭环** —— [P1](phases/P1-IMPLEMENTATION.md) §5.1 与 [P4](phases/P4-IMPLEMENTATION.md) 均已实测方块落地（含 40 格批量），此项已从风险降级 |

### 已明确「未找到答案」的项（不推测填充）

- `MindustryX` fork 的 jar 是否有人成功构建：无任何证据

### 验证过程中修正的 API 误用

| 误用 | 正确 |
|---|---|
| `Tile.build()` | `Tile.build`（字段） |
| `Map.name` | `Map.name()`（方法） |
| `Player.isValid()` / `Player.added()` | 均不存在；用 `dead()` |
| `mindustry.maps.Map.teams` 当 `Seq` | 是 `arc.struct.IntSet` |

---

## 附录 A · 源码索引

本文档引用的所有引擎位置（基于 Mindustry v160.5 源码树）。

| 主题 | 位置 |
|---|---|
| `isAI()` 定义（`!pvp` 短路） | `Team.java:112` |
| `FogControl.isVisibleTile`（`isAI()` 短路） | `FogControl.java:117` |
| `FogControl.isDiscovered` | `FogControl.java:104` |
| `fogControl` 全局单例 | `Vars.java:293` |
| `fogRadius` 单位确认（格） | `FogControl.java:258-260` |
| `isSyncHidden`（`!isShooting && inFogTo`） | `UnitComp.java:216` |
| `inFogTo`（单位） | `UnitComp.java:229` |
| `inFogTo`（建筑，含 `isDiscovered`） | `BuildingComp.java:2229` |
| 实体同步循环 | `NetServer.java:1154` |
| 按队同步分支 | `NetServer.java:1287-1298` |
| `writeCustomEntitySnapshot` | `NetServer.java:1192` |
| **核心库存全量广播** | `NetServer.java:1101-1107` |
| `validPlace` 三层 | `Build.java:163-175` |
| `validPlaceIgnoreUnits` | `Build.java:183` |
| `placeRangeCheck` 规则（默认 false） | `Rules.java:127` |
| `buildRange` 的实际用途（仅渲染） | `InputHandler.java:1449` |
| **`BuildPlan` 三种构造器**（放置 / 带配置 / 拆除） | `BuildPlan.java:31-59` |
| **`addBuild` 入队接口** | `BuilderComp.java:272, 277` |
| **`updateBuildLogic` 主循环** | `BuilderComp.java:110-195` |
| `finalPlaceDst` 范围筛选 | `BuilderComp.java:123-126, 155` |
| **`hasAll` 资源检查** | `BuilderComp.java:166-170` |
| `Call.beginPlace` 调用点 | `BuilderComp.java:173` |
| `Call.beginBreak` 调用点 | `BuilderComp.java:191` |
| **`beginPlace` 签名（参数是 `Unit`，非 `Player`）** | `Build.java:70-71` |
| **`beginBreak` 签名** | `Build.java:24-25` |
| `canBuild()` | `BuilderComp.java:40` |
| **`Call` 全集（212 个网络化方法）** | `core/build/generated/source/kapt/main/mindustry/gen/Call.java` |
| **`ActionType` 全集（16 项）** | `mindustry.net.Administration$ActionType`（不在源码树，需从 jar 反查） |
| **`allowAction`（`null` player 无条件放行）** | `Administration.java:168-189`（关键在 `:175`） |
| **默认交互 filter（仅速率限制）** | `Administration.java:73-93` |
| `addActionFilter`（自定义校验入口） | `Administration.java:163-165` |
| `requestItem` 的距离检查 | `InputHandler.java:496-497` |
| `transferInventory` | `InputHandler.java:512-513` |
| `takeItems`（不需 `Player`） | `InputHandler.java:166` |
| `transferItemTo`（不需 `Player`） | `InputHandler.java:247` |
| `commandUnits` / `setUnitCommand` / `setUnitStance` | `InputHandler.java:309 / 410 / 445` |
| `commandBuilding` | `InputHandler.java:469` |
| `tileConfig`（`player` 可为 null） | `InputHandler.java:705` |
| `rotateBlock`（`player` 可为 null） | `InputHandler.java:686` |
| `itemTransferRange = 220f`（27.5 格） | `Vars.java:123` |
| `logicItemTransferRange = 45f` | `Vars.java:125` |
| **`Schematics.place`（直接 `setBlock`，不可用）** | `Schematics.java:520-533` |
| `removeQueueBlock`（不需 `Player`） | `InputHandler.java:536` |
| `deletePlans`（需 `Player`） | `InputHandler.java:261` |
| `getMaxPlans`（待建计划队列上限） | `TypeIO.java:474` |
| **`Units.bestEnemy`（含 `inFogTo` 视野过滤）** | `Units.java:318-337`（过滤在 `:326`） |
| `RadarTarget` 枚举（8 项分类谓词） | `RadarTarget.java` |
| `RadarI` 逻辑雷达指令 | `LExecutor.java:721` |
| 逻辑无独立 fog 过滤（依赖 `bestEnemy`） | `LExecutor.java`（搜索 `fog` 为空） |
| 接管判定（三条路径） | `InputHandler.java:783` / `:1006` / `:2149` |
| `allowAction` 校验点 | `InputHandler.java:775` |
| 指挥逻辑（仅检查队伍） | `InputHandler.java:331` |
| 自动重生（`deathDelay = 60f`） | `PlayerComp.java:233-241` |
| `dead()` 定义 | `PlayerComp.java:322` |
| 玩家位置跟随单位 | `PlayerComp.java:224` |
| 自由相机分支 | `DesktopInput.java:277-295` |
| 相机跟随 `player` | `DesktopInput.java:287-289` |
| `Team` 数组（256 槽） | `Team.java:28-30, 43-56` |
| `tilesize = 8` | `Vars.java:135` |
| 缩放上下限 | `Renderer.java:45, 48` |
| 音频衰减公式 | `arc.audio.Sound.calcFalloff`（字节码还原） |
| `falloff = 16000` | `arc.audio.Audio` 构造器 |
| headless 下不播声音 | `SoundControl.java:368` |
| 规则字段默认值 | `Rules.java:41, 61, 123, 125, 199, 201` |
| PvP 地图需 ≥2 核心 | `World.java:372` |

---

## 附录 B · 术语

| 术语 | 含义 |
|---|---|
| **对等约束** | AI 的可见与可为必须等于同队人类玩家的 11 条限制（逐条见第 4 节） |
| **确认核心数据** | 连续观察敌方核心 10 秒以获得其库存快照的机制 |
| **观察者 Mod** | 客户端 Mod，统一承载观战 / 裁判 / 回放三种模式 |
| **只读快照** | 主线程定期生成、供 HTTP 线程无锁读取的状态副本 |
| **抖动容错** | 可见性判定中允许的瞬时丢失窗口（0.5 秒） |
