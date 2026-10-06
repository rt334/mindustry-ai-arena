# Mindustry AI Arena

让多个 AI 在 Mindustry 里打 PvP 的服务器 Mod 与配套工具。

**核心原则：公平竞技 —— AI 在任何时刻看到的，必须与一个真人玩家在同队时看到的完全一致。**

---

## 这是什么

一套给 [Mindustry](https://github.com/Anukre/Mindustry) 的 dedicated server 用的 Mod，把游戏变成 AI 可以接入的竞技场：

- AI 通过 **HTTP** 读取局面、下达指令
- 所有操作走**引擎自己的流水线**（`addBuild` → `BuilderComp` → `Call.beginPlace`），不是模拟
- 视野、指挥范围、建造范围、资源、人口全部与玩家同规则，**没有旁路**
- 裁判可切换任意队伍视角观战，支持录像

```
AI ──HTTP──→ Mod（服务器内）──引擎 API──→ 世界
                 │
                 └── 视野过滤 / 范围校验 / 权限校验
```

---

## 快速开始

```powershell
# 2 个 AI，veins 地图（官方 PvP 图）
.\start-arena.ps1

# 4 个 AI，passage 地图（自带 4 个核心），开局录像
.\start-arena.ps1 -Agents 4 -Map passage -Record

# 前台监控
.\start-arena.ps1 -Agents 2 -KeepRunning
```

脚本会拉起服务器、等它就绪、初始化对局、输出每个 AI 的 token 与端点。参战 agent 不足时自动生成并重启加载。

**前置**：
- Mindustry 服务器 jar（从源码 `gradle server:dist` 构建 —— 官方 desktop 包**不含** headless 入口）
- JDK 17
- 本仓库的 `mod/ai-arena.jar` 已放到服务器运行目录的 `config/mods/`

**想自己写 AI**：先看 `ai-client.py` —— 示例客户端，用四阶段状态机（建设 / 造兵 /
推进 / 攻击）完整打完一局，也是 P4「API 够不够让 AI 打完一局」的验收证据。
接口说明书在 `skill/`（会被拷到 `~/.dsh/skills/ai-arena/`），逐条细节以
[`docs/API.md`](docs/API.md) 为准。

---

## API

统一响应信封：

```json
{"ok": true,  "data": {...}}
{"ok": false, "code": 1005, "error": "target tile is not visible to sharded"}
```

鉴权：`Authorization: Bearer <token>`（token 在 `config/ai-arena.json` 里，首次启动自动生成）

### 读

| 端点 | 说明 |
|---|---|
| `GET /ping` | 存活探测（无需鉴权） |
| `GET /state` | 局面快照：tick / 规则 / 队伍 / 视野内实体 |
| `GET /units` | 视野内单位（含携带物、当前指令） |
| `GET /buildings` | 视野内建筑（含库存、液体、配置、施工进度） |
| `GET /map?x=&y=&w=&h=` | 区域地图（≤4096 格） |
| `GET /map` | 全图扫描，按 `cursor_next` 分页 |
| `GET /content` | 方块 / 物品 / 单位 / 液体 / 指令 / 姿态目录 |
| `GET /intel` | 敌方核心数据情报（需连续可见 10 秒确认） |
| `GET /events?since=` | 事件流（游标轮询） |
| `GET /observe` | 观战信息与可视角队伍 |
| `GET /block?name=` | 方块定义（成本 / 输入 / 输出 / 尺寸）；不传 `name` 列出全部可放置方块 |
| `GET /ore?x=&y=` | 指定格的矿脉明细 |
| `GET /rates?window=` | 资源变化速率（两个时间点的库存差） |
| `GET /stalls` | 产线异常警报（堵塞 / 缺料 / 满仓 / 电力） |
| `GET /watch?since=` | **「值得注意」的聚合判定** —— `clear=true` 表示现在没事，可以安心睡到下一次事件 |
| `GET /drill` | 矿机明细（读 `itemsPerSecond`，别读两位小数的 `lastDrillSpeed`） |
| `GET /factory` | 单位工厂状态 |
| `GET /queue` | 建造队列（逐条坐标 / 进度 / `stuckReason`） |
| `GET /stream?since=&seconds=` | 事件流（SSE 推送，与 `/events` 同一套游标语义） |
| `GET /maps` | 地图列表与属性 |
| `GET /database` | 汇总数据库 |
| `GET /diag` | 服务端诊断计数器（admin） |

### 写

| 端点 | 说明 |
|---|---|
| `POST /place?x=&y=&block=` | 单点建造 |
| `POST /place?shape=line&x1=&y1=&x2=&y2=&block=` | 批量：`line` / `area` / `rect` / `outline` / `circle` / `point` / `path` |
| `POST /break?...` | 拆除（参数同上） |
| `POST /config?x=&y=&value=` | 修改建筑配置 |
| `POST /spawn?type=&x=&y=` | 生成单位（**默认禁用**，须由工厂生产） |
| `POST /mine?x=&y=[&unit=]` | 让单位挖指定格 |
| `POST /blueprint?x=&y=&w=&h=` | 蓝图导出；`POST /blueprint?x=&y=&data=` 放置 |
| `POST /chat?text=` | 发言 |
| `POST /command?action=move&units=1,2&x=&y=` | 指挥：`move` / `attackUnit` / `assistBuilding` / `setCommand` / `setStance` / `commandBuilding` / `requestItem` / `transferInventory` |
| `POST /control?op=enter&unit=` | 接管单位：`pos` / `move` / `order` / `enter` / `release` / `fire` / `stopmove` / `orders` / `probe` / `ticks`（`warp` 默认禁用） |
| `POST /queue?clear=true` | 清空全队待办计划 |

### 裁判（admin token）

| 端点 | 说明 |
|---|---|
| `POST /setup?map=&fog=` | 初始化对局（加载地图 + 放核心 + 生成建造单位） |
| `POST /start` | 解除暂停 |
| `POST /host` | 打开游戏端口 6567 |
| `POST /fog?fog=&static=` | 迷雾开关；**不带 `fog` 参数时返回当前** `fog` / `staticFog` / `pvp` |
| `POST /admin?action=observe&player=` | 在线玩家管理与观战设置 |
| `POST /record` · `?action=start\|stop\|download` | 录像控制；不带 `action` 返回状态与文件列表，`download` 需 `name=<file>.jsonl` |
| `GET /diag` | 服务端诊断计数器 |
| 任意读端点 `&view=all` | 上帝视角 |
| 任意读端点 `&view=<teamId>` | 指定队伍视角 |

### 错误码

```
1001 bad_request      1002 not_found       1003 out_of_bounds
1004 queue_full       1005 read_only       1006 cursor_expired
1007 op_expired       1008 place_blocked   1009 place_invalid
1401 unauthorized     1403 forbidden       1429 rate_limited
1500 internal_error

1008 -> HTTP 409（footprint 被占，挪一格即可）
1009 -> HTTP 400（引擎拒绝，重试无意义）
```

---

## 对等约束

**11 条，逐条落地。** 只有「指挥范围」必须自己实现 —— 引擎对指挥没有任何距离检查。

| # | 约束 | 实现方式 |
|---|---|---|
| 1-2 | 实体 / 地形可见性 | `FogControl` 复用引擎判定 |
| 3 | 听觉 | 无需处理（声学半径 20.2 格 < 最小视野 25 格） |
| 4 | 核心库存 | `/intel` 确认状态机（连续可见 600 tick，容错 30 tick） |
| 5 | 建造位置与速度 | `BuilderComp` 自动 |
| **6** | **指挥范围** | **自行实现** —— 单位与目标都须对己方可见 |
| 7-10 | 建造范围 / 资源 / 移动 / 攻击 | 引擎自动 |
| 11 | 逻辑处理器 | 已核查无法绕过视野（`Units.bestEnemy` 含 `inFogTo`） |

**引擎自带的对等约束比自实现的更可靠** —— 「无核心不能建造」（`BuilderComp`）、人口上限（`TeamData.unitCap`）、环境检查（`requestSpawn`），AI 全都自动继承，一行代码都不用写。

---

## 观战

观战**完全走 HTTP**，不占引擎实体同步通道 —— 规避了 `writeCustomEntitySnapshot` 与 `hiddenIds` 打架导致的闪烁。

因此观察者**不需要在服务器上有队伍**：没有实体，就没有身份问题。

客户端 Mod（`observer/`）提供自由相机：

| 按键 | 功能 |
|---|---|
| `WASD` / 方向键 | 平移 |
| 中键拖拽 | 平移 |
| 滚轮 | 缩放 |
| `Tab` | 在存活队伍间循环跳转 |
| `F1` | 帮助 |

非 admin 请求别人的视角会被**静默降级**为自己的视角，而不是报错 —— AI 无法通过试错探测出自己无权访问哪些视角。

---

## 录像

```jsonl
{"t":"meta","version":1,"map":"Veins","w":350,"h":200,"pvp":true,"fog":true,"snapshotInterval":60,"teams":[...]}
{"t":"snap","tick":196,"full":true,"units":[...],"builds":[...]}
{"t":"ev","seq":1,"tick":198,"type":"configure","detail":{"block":"core-nucleus","value":"3"}}
{"t":"end","tick":1050,"snapshots":11}
```

JSON Lines —— 流式追加、崩溃时已写部分仍可解析、客户端用与实时同一套解析器逐行读。

方块只存增量（首次全量 + 后续变化），因为多数方块长期不变。

---

## 压力测试

```powershell
.\stress-test.ps1                                # 默认 12 线程 / 45 秒稳定性
.\stress-test.ps1 -Threads 24 -Seconds 60        # 更高并发
.\stress-test.ps1 -SkipStability                 # 快速回归
```

五个阶段共 62 个用例：功能覆盖（18 个端点）、并发读、高频写、边界与错误路径、稳定性。
脚本自行拉起服务器、初始化对局、跑完、汇总、保存报告、关闭服务器。任一用例失败时退出码为 1。

**当前结果：62/62 通过，24 线程并发 960/960 零失败。**

详见 [`STRESS-TEST.md`](docs/STRESS-TEST.md) —— 其中记录了一个压测发现的真实并发缺陷：
`arc.struct.Seq` 的迭代器不是线程安全的，而鉴权路径每个请求都要遍历它。

---

## 引擎发现的坑

这些都是在真实服务器上撞出来的，都写进了 `DESIGN.md`。

**核心方块的 `buildVisibility = coreZoneOnly`**

```java
// Blocks.java:3128
requirements(Category.effect, BuildVisibility.coreZoneOnly, with(Items.copper, 1000, Items.lead, 800));
```

判定依据是「地图上是否存在 `core-zone` 地板」。没有该地板时 `Block.isHidden()` 返回 true，`validPlace` 从第一个检查就失败。

**`staticFog` 造成放置的鸡生蛋困境**

```java
// Build.java:252 —— validPlaceIgnoreUnits 的逐格检查
(state.rules.staticFog && state.rules.fog && !fogControl.isDiscovered(team, wx, wy)) ||
```

放核心需要「该格已被探索」，探索需要视野源，视野源又需要核心。新队伍从未探索过任何格子，这一条拒绝全图。

**`UnitCreateEvent` 覆盖不全**

全代码库只在 5 处触发：`UnitSpawnAbility` / `PayloadSource` / `Reconstructor` / `UnitAssembler` / `UnitFactory`。**核心生产单位和直接 spawn 都不触发它。** 只靠引擎事件，AI 永远不会知道敌方出现了新单位 —— 必须用快照差分补齐。

**`FogControl` 两个重载的坐标单位不同**

```java
isVisibleTile(Team team, int x, int y)        // 格坐标
isVisible(Team team, float x, float y)        // 世界坐标（像素）
```

混用会导致相邻 8 格的目标被判为不可见。

**`Rules.isBanned` 的白名单陷阱**

```java
// Rules.java:330
return blockWhitelist != bannedBlocks.contains(block);
```

地图 tags 若带进 `blockWhitelist=true` 而 `bannedBlocks` 为空，**每个方块都被判为 banned**。

**官方 PvP 地图是 `veins` / `glacier` / `passage`**

```java
// Maps.java:41-42
private static String[] pvpMaps = {"veins", "glacier", "passage"};
```

硬编码在引擎里，且被排除在生存模式之外。`World.java:372` 强制要求 PvP 图 ≥2 个核心。

**`state.tick` 换图后回退会让快照停止刷新**

`loadMap` 把 `state.tick` 重置为 0，而 `lastHeavyTick` 还留着上一局的值。`tick - lastHeavyTick` 变负数，条件永不成立。

**两个方向相反的编码坑**

| 对象 | 要求 | 后果 |
|---|---|---|
| `.ps1` 脚本 | UTF-8 **with** BOM | 无 BOM → PowerShell 按 ANSI 解码 → 中文乱码吞掉引号 |
| JSON 配置 | UTF-8 **without** BOM | 有 BOM → Java 的 `Jval` 解析失败 → 所有 token 变空 |

---

## 目录结构

```
docs/                    文档（索引见 docs/README.md）
  DESIGN.md              设计文档：架构、对等约束、引擎发现、P0~P7、待验证清单
  API.md                 接口手册（接口的唯一权威）
  CONDITIONS.md          条件与事故：能力边界、对等约束定义、越界记录
  DEVELOPING.md          改接口层的上手文档（编译部署、加端点）
  ENGINE-NOTES.md        引擎层事实（维护者文档）
  LESSONS.md             经验教训：判定与核实的陷阱
  TODO.md                未完成事项与验证债务
  FEASIBILITY.md         目标可行性评估
  PRODUCTION.md          产线实况（实测速率与布局）
  STRESS-TEST.md         压力测试报告
  PROMPTS.md             提示词与工作流约定
  place-failure-stats.md /place 失败码实测统计
  phases/                P0~P7 分阶段实现报告
    P0-VERIFICATION.md   技术验证（7 项原型验证）
    P1-IMPLEMENTATION.md 最简闭环
    P2-IMPLEMENTATION.md 对等约束
    P3-IMPLEMENTATION.md 信息 API
    P4-IMPLEMENTATION.md 操作 API
    P5-IMPLEMENTATION.md 观战与裁判
    P7-IMPLEMENTATION.md 编排（含 P6 录像摘要）
  reviews/               产线攻坚复盘与接口提案
    REPORT.md            产线攻坚报告
    DEBUG-LOG.md         实战调试复盘
    FEATURE-REQUESTS.md  接口层改进提案
    REVIEW-ADDENDUM.md   对提案的核对与增补

ai-client.py             示例 AI 客户端：读局面 → 决策 → 下指令，完整打完一局
start.py                 菜单 + 子命令（check / status / play / watch / replay / stop）
start-arena.ps1          一局启动脚本
live-match.ps1           服务端 + AI + 观战端
stress-test.ps1          62 用例压力测试
watch.py / ws-client.py  接口客户端（轮询 / WebSocket）
replay/index.html        回放播放器（单文件零依赖，拖入 .jsonl 即播）

mod/                     服务器 Mod
  src/aiarena/
    AIArenaMod.java      入口：配置、事件监听、主线程快照刷新、起 HTTP
    AIArena.java         配置 + 鉴权 + 限流
    HttpApi.java         路由与全部端点
    WsServer.java        WebSocket
    Actor.java           建造 / 拆除 / 配置
    Commander.java       指挥 + 范围约束
    Operations.java      批量形状 / spawn / chat
    Snapshot.java        只读快照 + 实体差分
    StallWatch.java      停机判定与计划进度
    EventLog.java        事件流
    Recorder.java        录像器
    Intel.java           核心数据确认状态机
    VisionTracker.java   视野跟踪
    RateTracker.java     产率采样
    Audit.java           审计日志（只记会改变世界的动作）
    Diag.java            运行时诊断
    Shadow.java          影子 Player 池
    Json.java            零依赖 JSON 输出

observer/                客户端观察者 Mod（图形回放，未完成）
  src/aiobserver/ObserverMod.java
skill/                   接口说明书 + Python 客户端库（拷到 ~/.dsh/skills/ai-arena/）
drive/                   开发期脚本与验证脚本（不是产品的一部分）
server-run/              服务器运行目录（含 token 配置，不入版本控制）
```

---

## 构建

```bash
# 服务器 Mod
javac -encoding UTF-8 -cp server-release.jar -d classes mod/src/aiarena/*.java
jar cf ai-arena.jar -C classes . && jar uf ai-arena.jar mod/mod.hjson

# 客户端 Mod（需要完整的 Mindustry.jar，不是 server-release.jar）
javac -encoding UTF-8 -cp Mindustry.jar -d classes observer/src/aiobserver/*.java
jar cf ai-observer.jar -C classes . && jar uf ai-observer.jar observer/mod.hjson
```

**注意**：官方 `Mindustry.jar`（desktop 包）**不能**当 headless 服务器用 —— 它没有 `mindustry/server/` 包，也没有 `arc.backend.headless.HeadlessApplication`。必须从源码构建 `server:dist`。

---

## 状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | 技术验证 | ✅ |
| P1 | 最简闭环 | ✅ |
| P2 | 对等约束（11 条） | ✅ |
| P3 | 信息 API | ✅ |
| P4 | 操作 API | ✅ |
| P5 | 观战与裁判 | ✅ 服务器侧实测；客户端 Mod 编译通过 |
| P6 | 录像 | ✅ 服务器侧；客户端图形回放待做 |
| P7 | 编排 | ✅ |

**未完成**：客户端图形回放（加载录像 → 时间线拖动 → 重建世界状态）。需要替换 `Vars.world`，是独立的渲染层工程；服务器侧的录制、存储、下载均已就绪。

**已实测（2026-10-06）**：客户端观察者 Mod 在图形界面里跑通过 ——
`Loading mod: ai-observer` → `Connecting to server: /127.0.0.1:6567` → `Received world data`，
服务端 `/diag` 显示 `fullViewSends=334 / spectatorRouted=334`（正在给观察者发全景快照）。
截图核对：左上角「观战端 / 视角: derelict (全图)」面板、三个按钮、快捷键帮助与小地图都正常，
中文完整，并明确标注「只读观战：服务端不会给你任何单位」。
（**图形回放仍未做** —— 见上一条。）

---

## 许可

MIT


---

## 接口文档与 Skill

- **[`API.md`](docs/API.md)** —— 接口手册：起局、鉴权、接口表、观战端、故障速查。
- **[`ENGINE-NOTES.md`](docs/ENGINE-NOTES.md)** —— 引擎层说明（维护者文档）：坐标系与朝向、
  邻近判定、三个已修复的引擎缺陷。
- **[`skill/`](skill/)** —— 可安装的 Skill（`SKILL.md` + `scripts/`）。
  装法：把 `skill/` 内容放到 `%USERPROFILE%\.dsh\skills\ai-arena\`。

**`docs/API.md` 与 `skill/` 刻意不含任何游戏内事实** —— 不写矿脉分布、方块参数、配方、
地图结构。理由见下。

### 公平竞技

**AI 在任何时刻看到的，必须与一个真人玩家在同队时看到的完全一致。**

这条不只是运行期约束，也约束文档：`SKILL.md` 是 agent 启动时就会读到的文件，
往里塞游戏内情等于让它在开局前就拿到玩家要靠试验才能得到的答案。
所以接口文档只说「怎么调」，不说「会看到什么」。

引擎实现层的知识归 `docs/ENGINE-NOTES.md`，那是维护者文档，不是 agent 读物。

### 禁止一切等待

**把「等了多久」当判据的代码一律不合格，判据必须是目标状态是否出现。**

```python
# ✗ 错
time.sleep(30)

# ✓ 对 —— 轮询 + 提前退出
b = arena.poll_until(lambda: arena.building_at(x, y), timeout=90)
```

`Start-Sleep -Milliseconds 100` 作为**采样间隔**是允许的；
`Start-Sleep -Seconds 30` 作为**「等它建好」**是禁止的。
区别：前者每次醒来都检查状态、满足即退；后者把时长当判据。

**为什么较真**：本项目的建造类是**排队**的，接口返回成功只代表请求入队。
固定等待会产出「看起来成功、其实没有」的假结论。

### 快速上手

```powershell
pwsh -File live-match.ps1                 # 起一局
python skill/scripts/arena.py --agent alpha --token <TOKEN>
```

---

## 目标可行性

**[`FEASIBILITY.md`](docs/FEASIBILITY.md)** —— 动手铺产线**之前**先做的比大小：

1. 从引擎源码取配方，算每个目标的原料需求
2. 从全图普查取原料的地质上限
3. 两者相减，有缺口就停下报告

实测教训：`veins` 图上「铜铅硅钛石墨各 +5/s」**不可能同时达成** ——
硅和石墨都要煤，合计需煤 15/s，而全图煤矿机上限只有 9.79/s。
这个比大小只需要一行算术，却在铺了十几轮带子之后才做。

## 上手

```
python start.py          # 菜单
python start.py check    # 前置检查（缺什么直说）
python start.py play     # 起局
python start.py watch    # 起局 + 观战端
python start.py replay   # 看回放（单文件，零依赖）
```
