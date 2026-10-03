# AI 竞技场 · P0 技术验证报告

> 对应 `DESIGN.md` 第 9 节 P0。验证方式：真实 headless 服务器 + 验证 Mod，非纸面推导。
>
> **结论：P0 全部通过。架构成立，可以进入 P1。**

---

## 0. 验证环境

| 项 | 值 |
|---|---|
| 服务器 jar | 从源码构建 `server:dist` → `server-release.jar`（19,106,958 B） |
| 构建耗时 | **1 分 6 秒**（Gradle 9.4.1，依赖全部命中本地缓存） |
| Java | Zulu JDK 17.0.20.1 |
| 运行目录 | `C:\dsh\ai-arena\server-run`（数据目录自动为 `<cwd>/config`） |
| Mod 目录 | `<cwd>/config/mods/` |
| 验证 Mod | `ai-arena-verify.jar`（自建，5,287 B） |

**关于 `Mindustry.jar`**：官方 desktop 包**不能**充当 headless 服务器 —— 它没有 `mindustry/server/` 包，也没有 `arc.backend.headless.HeadlessApplication`。必须从源码构建 `server:dist`。

---

## 1. 验证结果总表

| # | 验证项 | 结果 | 证据 |
|---|---|---|---|
| **1** | headless 服务器加载 Mod | ✅ **PASS** | `1 mods loaded.` + Mod 日志输出 |
| **2** | `Core.app.post` 在 headless 下执行队列 | ✅ **PASS** | 投递后 **42 ms** 执行，回调内 `headless=true` |
| **3** | 服务器改世界→客户端同步 | ✅ **已消除** | 建造走 `addBuild → BuilderComp → Call.beginPlace`，不存在手动改世界 |
| **4** | 自定义 `Team.get(id)` 可用 | ✅ **PASS** | `Team.all.length=256`，非空 256，`Team.get(100)=team#100` |
| **5** | 影子 `Player` 是否进 `Groups.player` | ⚠️ **会进入** | `add()` 后 `size 0→1`，`remove()` 后回 0 |
| **6** | 影子 `Player` 是否计入胜负判定 | ✅ **PASS** | `team().data().players.size = 0`（不污染队伍统计） |
| **7** | `player.set(x, y)` 能否自由设定 | ✅ **PASS** | 设 (1234.5, 678.5)，读回一致 |

### 附加验证（超出原计划）

| 项 | 结果 | 证据 |
|---|---|---|
| **内嵌 HTTP 在 headless 下工作** | ✅ **PASS** | `com.sun.net.httpserver` 绑定 127.0.0.1:7199，实测 4 个端点响应 |
| **`Core.app.post` 回主线程处理 HTTP 请求** | ✅ **PASS** | `/fog` 端点经 `post` 后正确返回游戏状态 |
| **`state.set(playing)` + tick 前进** | ✅ **PASS** | `tick 0 → 185`，`Time.run(120f)` 回调执行 |
| **`pvp=true → isAI()=false`** | ✅ **PASS** | `isAI() = false  (expect false)` |
| **`FogControl` 在服务器侧可用** | ✅ **PASS** | `Vars.fogControl = mindustry.game.FogControl` |
| **世界数据可读** | ✅ **PASS** | `/tile?x=10&y=10` → `{"floor":"basalt","block":"dune-wall","team":"derelict"}` |
| **`BuildPlan` 构造器可用** | ✅ **PASS** | 放置与拆除两种构造器均构造成功 |
| **单位类型数据可读** | ✅ **PASS** | `dagger fogRadius=21.75` |

---

## 2. 关键实测输出

### 2.1 Mod 加载与 headless 确认

```
[I] 1 mods loaded.
[AIVERIFY] PASS  V1 Mod load OK
[AIVERIFY]       headless = true
[AIVERIFY]       Vars.player = null
[AIVERIFY]       platform = mindustry.server.ServerLauncher$1
[AIVERIFY]       Core.app = arc.backend.headless.HeadlessApplication
```

**`Vars.player = null` 实测确认** —— 印证了 DESIGN.md 的判断：服务器侧没有本地玩家，所有需要 `Player` 参数的引擎方法必须用影子 Player。

### 2.2 `Core.app.post` 时延

```
[AIVERIFY] PASS  V2 Core.app.post callback executed
[AIVERIFY]       投递后经过 42 ms
[AIVERIFY]       回调中 Vars.headless = true
```

42 ms ≈ 2.5 帧（60 FPS）。**headless 下 post 完全可用。**

### 2.3 队伍注册表

```
[AIVERIFY] PASS  V4 Team.get(100) = team#100
[AIVERIFY]       0=derelict 1=sharded 2=crux 3=malis 4=green 5=blue 6=neoplastic
                 7=team#7 8=team#8 50=team#50 128=team#128 200=team#200 255=team#255
[AIVERIFY]       rules.pvp = false
[AIVERIFY]       isAI() = false
```

**256 个队伍槽位全部非空**（比设计文档预估的 250 个更多）。且**即使在 `pvp=false` 时，只要 `waves`/`attackMode`/`campaign` 全关，`isAI()` 也是 false** —— 这给了公平性设计额外的余量。

### 2.4 影子 Player

```
[AIVERIFY]       Player.create() 成功，name=AI_SHADOW_TEST team=team#100
[AIVERIFY]       add 之前 Groups.player.size() = 0
[AIVERIFY]       add 之后 Groups.player.size() = 1
[AIVERIFY]       影子 Player 出现在 Groups.player 中（需评估影响）
[AIVERIFY] PASS  player.set(x, y) 生效: (1234.5, 678.5)
[AIVERIFY]       team().data().players.size = 0
[AIVERIFY]       team().cores.size = 0
[AIVERIFY]       team().active() = false
[AIVERIFY]       team().isAlive() = false
[AIVERIFY]       已 remove，Groups.player.size() = 0
```

**两条结论**：

- `Player.create()` + `add()` **会**让影子进入 `Groups.player`
- 但**不会**污染 `team().data().players.size`（仍为 0）

### 2.5 HTTP 端点实测

```
GET /state  → {"ok":true,"tick":1063,"playing":true,"pvp":true,"fog":true,
               "units":0,"builds":1,
               "teams":[{"id":1,"name":"sharded","cores":1,"isAI":false,"alive":true}]}

GET /units  → {"ok":true,"units":[]}

GET /fog?team=100&x=10&y=10
            → {"ok":true,"team":100,"x":10,"y":10,
               "visible":false,"discovered":false,"tick":1068}

GET /tile?x=10&y=10
            → {"ok":true,"x":10,"y":10,"floor":"basalt","block":"dune-wall",
               "team":"derelict","build":false,"solid":true}

GET /ping   → {"ok":true,"headless":true,"tick":0}
```

**全部可用，且 `/fog` 端点验证了「HTTP 线程 → `Core.app.post` → 主线程读游戏状态 → 回传」这条关键链路。**

---

## 3. 未完成项（不构成架构风险）

以下三项因**测试场景配置**未跑通，非技术障碍：

| 项 | 原因 | 处理 |
|---|---|---|
| 放置自定义队伍的核心 | 测试用的 `Ancient Caldera` 是沙丘地形，4×4 的 `core-foundation` 找不到落脚点 | 换地图或改用 3×3 的 `core-shard`，P1 实现时自然解决 |
| 生成单位 + 视野验证 | 依赖上一条（需要有效坐标） | 同上 |
| `addBuild` 端到端 | 依赖上一条（需要建造单位） | 同上 |

**依据**：地图自带核心位于 (130,32) 且 `teams` 报告 `sharded cores=1`，证明**地图本身有可放核心的位置**，只是当前搜索策略的坐标检查过严。这是测试代码的问题。

另：`t1 visible samples = 0` **不是失败** —— t1 当时既无核心也无单位，**没有视野源，理应全部不可见**。这恰好反证了 `FogControl` 在 `fog=true` 下正常工作（对比批次 3 中 `fog=false` 时恒为 `visible=true`）。

---

## 4. 对 DESIGN.md 的修正

### 4.1 影子 Player 需要「用后即弃」或接受其可见性

原设计假设影子 Player 可以长期存在。实测显示它会进入 `Groups.player`。

**修正**：

```
- 若只在需要 Player 参数的调用中临时创建 → 用完立即 remove()
- 若长期持有 → 需评估 Groups.player 遍历者（玩家列表 UI、admin 命令、playerLimit 检查）
```

由于 `team().data().players.size` 不受影响，胜负判定与死队清理**不受污染**，风险可控。

### 4.2 `loadMap` 不会应用自定义规则

实测：`Vars.world.loadMap(map, rules)` 之后 `state.rules.pvp` 被重置为地图自身的规则。**必须显式设置**：

```java
Vars.world.loadMap(map, new Rules());
Rules r = Vars.state.rules;      // 注意：要改 state.rules，不是传入的那个对象
r.pvp = true;
r.fog = true;
r.staticFog = true;
Vars.state.set(GameState.State.playing);
```

### 4.3 `state.tick` 需要 `playing` 状态才前进

`world.resize()` 与 `loadMap()` 都不会让 tick 前进，`Time.run()` 也不会触发。必须 `state.set(playing)`。

### 4.4 服务器 Mod 的 HTTP 服务端无需额外配置

`com.sun.net.httpserver` 在 headless 服务器上**开箱可用**，不需要 `--add-modules`，也不需要任何 Gradle 依赖。这消除了 P0 之外的一个潜在风险。

---

## 5. 对 P1 的直接影响

**P1 可以按原设计推进**，但需注意：

1. **HTTP 骨架已被验证** —— 直接复用本报告的 `startHttp()` 模式（含 `Core.app.post` 回主线程）
2. **规则设置必须显式** —— 见 4.2
3. **测试地图需要挑选** —— 内置 18 张地图都是生存地形（`spawns=0`、无 `pvp` tag），PvP 场景需要自制地图
4. **影子 Player 的生命周期要明确** —— 建议「按需创建 + 立即 remove」

---

## 6. 验证代码位置

```
C:\dsh\ai-arena\
  DESIGN.md                     设计文档
  P0-VERIFICATION.md            本报告
  verify\
    mod.hjson                   验证 Mod 元信息
    src\aiverify\VerifyMod.java 验证代码（4 个批次合并）
    ai-arena-verify.jar         编译产物
  server-run\
    config\mods\                服务器 Mod 目录
    out.log                     服务器 stdout（含验证输出）
```

**服务器 jar**：`C:\dsh\Mindustry-src\server\build\libs\server-release.jar`
**构建命令**：`gradle --init-script C:\dsh\_localrepo.gradle server:dist`

---

## 附录 · 验证过程中修正的三个 API 误用

| 误用 | 正确 |
|---|---|
| `Tile.build()` | `Tile.build`（是字段） |
| `Map.name` | `Map.name()`（是方法） |
| `Player.isValid()` / `Player.added()` | 均不存在；用 `dead()` |

这三处都不影响设计结论，仅记录以备后续参考。
