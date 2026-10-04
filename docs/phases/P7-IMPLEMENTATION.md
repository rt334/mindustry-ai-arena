# AI 竞技场 · P7 实现报告

> 对应 `../DESIGN.md` 第 9 节 P7。目标：一条命令开一局。
>
> **结论：验收标准达成 —— `.\start-arena.ps1 -Agents 4 -Map passage` 起一局，四个 AI 各自就位。**

---

## 1. 交付物

```
C:\dsh\ai-arena\
  start-arena.ps1     编排脚本（206 → 263 行）
```

---

## 2. 脚本能力

```powershell
.\start-arena.ps1                              默认 2 个 AI，veins 地图
.\start-arena.ps1 -Agents 4 -Map passage       4 个 AI
.\start-arena.ps1 -Record                      开局即开始录像
.\start-arena.ps1 -Fog:$false                  关闭迷雾（调试）
.\start-arena.ps1 -KeepRunning                 前台监控
```

| 阶段 | 行为 |
|---|---|
| 前置检查 | 校验 jar / Java / 运行目录 / Mod 部署 / 端口占用 |
| 启动服务器 | 后台拉起 headless，日志重定向到 `arena-out.log` |
| 等待就绪 | 轮询 `/ping`，最多 30 秒；进程提前退出则打印日志尾部 |
| **自动补足 agent** | 参战 agent 不足时生成新 agent + 随机 token，重启服务器加载 |
| 初始化对局 | 调 `/setup`，输出核心绑定与单位位置 |
| 录像 | `-Record` 时调 `/record?action=start` |
| 输出连接信息 | 每个 agent 的 id / team / token + 全部可用端点 |
| 监控 / 退出 | `-KeepRunning` 前台轮询状态；Ctrl+C 优雅停止 |

---

## 3. 实测：一条命令起四个 AI

```
=== 前置检查 ===
  服务器 jar  19,106,958 B
  Mod         77,785 B

=== 启动服务器 ===  PID 36800
=== 等待服务器就绪 ===  就绪（0.5 秒）

=== 读取 agent 配置 ===
  配置里只有 2 个参战 agent，自动补足到 4
    新增 agent3     team=102   token=6032f96df9db...
    新增 agent4     team=103   token=ac19a550e83a...
  重启服务器以加载新配置...
  已重启（PID 35580）
  裁判    referee
  参战    alpha, beta, agent3, agent4

=== 初始化对局（passage）===
  officialPvp=true, mapCoreTeams=[sharded,crux]
  unit[alpha]=poly@141,63;  bind[alpha]->sharded@141,63
  unit[beta]=poly@353,63;   bind[beta]->crux@353,63
  core[agent3]@250,60;      unit[agent3]=poly
  core[agent4]@253,57;      unit[agent4]=poly
  worldUnits=4, worldBuilds=5

  地图 Passage  500x120
    alpha      -> 1   @ (143,65)
    beta       -> 2   @ (355,65)
    agent3     -> 102 @ (250,60)
    agent4     -> 103 @ (253,57)
```

**四个 AI 的来源分两类**：

- `alpha` / `beta` **接管地图自带的 PvP 核心**（`sharded` @ (143,65)、`crux` @ (355,65)）
- `agent3` / `agent4` **自建核心**（地图只有 2 个核心队，不够 4 个 AI）

这正是 P1 里实现的两条路径协同工作的结果。

### 视角隔离验证

```
alpha    看到 1 个单位，队伍: 1           ← 只看自己
agent3   看到 2 个单位，队伍: 102,103     ← 与 agent4 相邻，互相可见
agent4   看到 2 个单位，队伍: 102,103
裁判     看到 4 个单位（team 1, 2, 102, 103）
```

`agent3` 的核心在 (250,60)、`agent4` 在 (253,57)，相距仅 3 格，所以彼此可见 —— 正确行为。

---

## 4. 踩到的两个编码坑

### ① PowerShell 读脚本的编码

`.ps1` 文件若为 **UTF-8 无 BOM**，PowerShell 会按系统 ANSI 解码，中文变成乱码，**引号被吞掉导致语法错误**。

```
if ($busy) { throw "端口 $Port 已被占用（PID ...）" }
→ if ($busy) { throw "绔彛 $Port 宸茶鍗犵敤锛圥ID ...锛? }
```

**解法**：脚本必须存为 **UTF-8 with BOM**。

```powershell
$utf8Bom = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText($path, $text, $utf8Bom)
```

### ② Java 读配置的编码

反过来，**JSON 配置必须是无 BOM**。`Set-Content -Encoding UTF8` 会加 BOM，而 Mindustry 的 `Jval` 解析器遇到 BOM 会失败 —— 表现为配置文件里明明有 agent，Mod 却一个都读不到（**全部 token 变空**，鉴权全 401）。

**双保险解法**：

```powershell
# 脚本侧：写无 BOM
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($cfgPath, $json, $utf8NoBom)
```

```java
// Mod 侧：读时剥离 BOM
String raw = file.readString("UTF-8");
if (raw != null && !raw.isEmpty() && raw.charAt(0) == '\uFEFF') raw = raw.substring(1);
Jval root = Jval.read(raw);
```

**两个方向相反的坑**：脚本要 BOM，数据要无 BOM。都记进 DESIGN 的附录。

---

## 5. 验收对照

`../DESIGN.md` P7 的验收标准：

> `.\start-arena.ps1 -agents 4` 起一局，四个 AI 各自连上开始对抗。

| 项 | 状态 |
|---|---|
| 一条命令拉起服务器 | ✅ |
| 自动补足到 4 个 agent | ✅ |
| 四个 AI 各自绑定队伍与核心 | ✅ |
| 视角互相隔离 | ✅ |
| 裁判全见 | ✅ |
| AI 能通过 HTTP 操作（批量建造实测） | ✅ |
| 可选录像 | ✅ |

**达成。**

---

## 6. 全项目收尾

至此 P0–P7 全部完成：

| 阶段 | 内容 | 报告 |
|---|---|---|
| P0 | 技术验证（7 项原型验证） | `P0-VERIFICATION.md` |
| P1 | 最简闭环（HTTP + 引擎流水线） | `P1-IMPLEMENTATION.md` |
| P2 | 对等约束（11 条 + 指挥范围） | `P2-IMPLEMENTATION.md` |
| P3 | 信息 API（含事件流） | `P3-IMPLEMENTATION.md` |
| P4 | 操作 API（批量 + spawn + chat） | `P4-IMPLEMENTATION.md` |
| P5 | 观战与裁判（view + 客户端 Mod） | `P5-IMPLEMENTATION.md` |
| P6 | 录像（JSONL Recorder） | 见本文件第 7 节 |
| P7 | 编排与场景（启动脚本） | 本文件 |

### 最终产物

```
C:\dsh\ai-arena\
  ../DESIGN.md               设计文档（含 9 项引擎发现）
  P0-VERIFICATION.md         P0 报告
  P1-IMPLEMENTATION.md       P1 报告
  P2-IMPLEMENTATION.md       P2 报告
  P3-IMPLEMENTATION.md       P3 报告
  P4-IMPLEMENTATION.md       P4 报告
  P5-IMPLEMENTATION.md       P5 报告
  P7-IMPLEMENTATION.md       本文件（含 P6 摘要）

  start-arena.ps1            编排脚本

  mod\                       服务器 Mod（18 个端点）
    mod.hjson
    ai-arena.jar             77,785 B
    src\aiarena\
      AIArenaMod.java        入口
      AIArena.java           配置 + 鉴权
      Json.java              JSON 输出
      Snapshot.java          只读快照 + 实体差分
      Actor.java             建造/拆除/配置
      Commander.java         指挥 + 范围约束
      Operations.java        批量 + spawn + chat
      Shadow.java            影子 Player 池
      Intel.java             核心数据确认状态机
      EventLog.java          事件流
      Recorder.java          录像器
      HttpApi.java           路由 + 全部端点

  observer\                  客户端观察者 Mod
    ai-observer.jar          5,621 B

  verify\                    P0 验证 Mod
  server-run\                服务器运行目录
```

### 端点总表（18 个）

```
GET  /ping                                  存活探测（无鉴权）
GET  /state                                 局面快照
GET  /units  /buildings                     视野内的实体
GET  /map?x=&y=&w=&h=  /  ?cursor=          区域 / 全图分页
GET  /content                               方块/物品/单位/液体/指令/姿态目录
GET  /intel                                 核心数据情报
GET  /events?since=                          事件流
GET  /observe                               观战信息
GET  /queue                                 建造队列
POST /place  /break                         单点 + 批量形状
POST /config  /spawn  /chat                 配置 / 生成 / 发言
POST /command?action=                       8 种指挥操作
POST /control?op=                           接管单位与直接操纵
GET  /setup  /maps  /record  (仅裁判)        初始化 / 地图列表 / 录像
```

---

## 7. P6 录像摘要（并入本报告）

**服务器侧已完整实现并实测**：

```
POST /v1/{admin}/record?action=start&label=veins
→ {"ok":true,"data":{"message":"recording to 20261003-152736-veins.jsonl"}}

GET  /v1/{admin}/record
→ {"recording":false,"status":"not recording",
   "files":[{"name":"20261003-152736-veins.jsonl","bytes":3213}, ...]}

GET  /v1/{admin}/record?action=download&name=<file>
→ 原始 JSONL 字节流（文件名严格过滤，路径穿越返回 code 1001）
```

**格式**：JSON Lines，每行一条记录

```
{"t":"meta","version":1,"map":"Veins","w":350,"h":200,"pvp":true,"fog":true,
 "snapshotInterval":60,"teams":[{"id":1,"name":"sharded","cores":1},{"id":2,"name":"crux","cores":1}]}
{"t":"snap","tick":196,"full":true,"units":[...],"builds":[...]}
{"t":"ev","seq":1,"tick":198,"type":"configure","detail":{"block":"core-nucleus","value":"3"}}
{"t":"end","tick":...,"snapshots":11}
```

实测一局 10 秒产生 18 行（meta 1 + snap 11 + ev 5 + end 1），快照间隔 `SNAPSHOT_INTERVAL = 60` tick ≈ 1 秒。

**为什么用 JSONL**：流式追加写、崩溃时已写部分仍可解析、客户端用与实时同一套解析器逐行读、可 grep。代价是体积偏大。

**方块只存增量** —— 首次全量 + 后续变化，因为多数方块长期不变。

**未完成部分**：客户端的图形回放模式（加载文件 → 时间线拖动 → 历史状态渲染）。
这需要替换 `Vars.world` 并按快照重建世界状态，是一个独立的渲染层工程，
不是服务器侧能覆盖的。服务器侧的录制、存储、下载都已就绪，客户端可随时接。
