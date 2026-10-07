# Mindustry AI Arena · 接口手册

服务端是打了补丁的 Mindustry headless 服务端 + `ai-arena` mod，暴露 HTTP 与 WebSocket 接口。
本手册只讲**怎么调用**和**能拿到什么**。

```
HTTP   http://127.0.0.1:7199/v1/<agent>/<action>
WS     ws://127.0.0.1:7200/ws
```

---

## 〇、禁止一切等待

**把「等了多久」当判据的调用一律不合格，判据必须是目标状态是否出现。**

```powershell
# ✗ 错 —— 把 30 秒当判据
Start-Sleep -Seconds 30
$b = 查建筑

# ✓ 对 —— 轮询 + 提前退出
$ok = '--'
for($i=0; $i -lt 120; $i++){
  $b = (& curl.exe -sS --max-time 5 -H "Authorization: Bearer $tok" "$base/buildings" 2>&1) -join '' | ConvertFrom-Json
  if($b.data.buildings | Where-Object { $_.x -eq $X -and $_.y -eq $Y }){ $ok='OK'; break }
  Start-Sleep -Milliseconds 100     # 采样间隔，不是「等待」
}
```

```python
# ✗ 错
time.sleep(30)

# ✓ 对
b = a.poll_until(lambda: a.building_at(x, y), timeout=90)
```

`Start-Sleep -Milliseconds 100` 作为**采样间隔**是允许的；
`Start-Sleep -Seconds 30` 作为**「等它建好」**是禁止的。
区别：前者每次醒来都检查状态、满足即退；后者把时长当判据。

**为什么较真**：`/place` 是**排队**的 —— 接口返回成功只代表请求入队，
不代表已经生效。固定等待会产出「看起来成功、其实没有」的假结论。
凡涉及建造、拆除、配置变更，下完请求必须轮询 `/buildings` 确认。

`arena.py` 里没有任何裸 `time.sleep(N)`，唯一的等待原语是
`poll_until(pred, timeout)` —— 命中立刻返回，超时返回 `None`。

---

## 一、AI 怎么接入

**不需要连游戏协议。** AI 全程只走 HTTP。

Mindustry 正常的多人流程是客户端用 TCP+UDP 连 6567，跑一遍握手再同步实体。
本竞技场**不走这条路**：

1. 启动时，mod 按 `config/ai-arena.json` 给每个 agent 建一个**真实 Player**
   （`HttpApi.spawnAgentPlayer`）。这个 Player 的 `con == null` —— 它**没有网络连接**。
2. 引擎自己的 `PlayerComp.update()` 会给「没有单位的玩家」从核心生成初始单位，
   所以不用手动 spawn，也不该预置任何兵和建筑。
3. 之后 AI 的每一次观察与操作都是一次 HTTP 请求。mod 把请求翻译成游戏动作，
   行为上与真人玩家走同一套规则（权限检查、建造队列、单位移动都一致）。

所以接入只有三件事：

| 步骤 | 做什么 |
|---|---|
| 1 | 在 `server-run/config/ai-arena.json` 里占一个 agent 条目，拿到 `token` 和 `team` |
| 2 | 起服务端与对局（`live-match.ps1`），等 `GET /ping` 返回 ok |
| 3 | 用 `Authorization: Bearer <token>` 调 `/v1/<agent>/...` |

### 不用任何 SDK 也能接入：`GET /v1/bridge/<agentId>`

**第 1 步不必去翻配置文件。** 这个端点无鉴权，一次请求给出接入所需的一切：

```
$ curl -s http://127.0.0.1:7199/v1/bridge/alpha
{"ok":true,"data":{"agent":"alpha","apiVersion":"1.4","httpPort":7199,
 "httpBase":"http://127.0.0.1:7199/v1/alpha","role":"player","token":"72d1…006f"}}
```

本地文件 `server-run/bridge-<agent>.json` 是**同一份内容**，用哪种方式取都行。
这样任何语言、任何运行位置的客户端都能接入，不必知道本项目的目录结构。

**裁判的条目不含 `token`**，只有一句 `tokenHint` —— 它的凭据只从环境变量
`ARENA_ADMIN_TOKEN` 读（fail-closed）。`GET /v1/bridge/<不存在的 agent>` → `code=1002`。

### `role`：三档权限

| `role` | 能做什么 |
|---|---|
| `player` | 参赛 AI：读写自己队伍的；`view` 只能是 own |
| `observer` | **只读观战**：能 `view=all` 看全图，但改状态的端点一律 `403 / 1403` |
| `referee` | 裁判：全部，含 `setup` / `host` / `fog` / `spawn` 带 `team=` |

旧配置里的 `"admin": true` 等价于 `referee`（向后兼容）。查自己的角色用 `/observe` ——
它返回 `role` / `canSeeAll` / `isReferee`。

**AI 与真人玩家的差别只在「怎么发指令」**（HTTP vs 键盘鼠标），
不在「能看到什么、能做什么」。这是本项目的公平竞技约束。

裁判（`role=referee`）额外多一项能力：带 `view=all` 看全图；`observer` 也能看全图，但不能动手。

---

## 二、请求格式

统一前缀 `/v1/<agent>/<action>`。

| 项 | 说明 |
|---|---|
| 鉴权 | 请求头 `Authorization: Bearer <token>` |
| 查询 | `GET`，参数走 query string |
| 操作 | `POST`，参数走 query string |
| 响应 | `{"ok":true,"data":{...}}` 或 `{"ok":false,"code":N,"error":"..."}` |
| 健康检查 | `GET http://127.0.0.1:7199/ping`，**无鉴权** |

**失败响应的 body 与成功一样是这个 JSON**，HTTP 状态码只是给代理和日志看的粗分类。
判失败要看 body 里的 `code`。用 `arena.py` 时 `ArenaError.code` 就是它，
`ArenaError.status` 才是 HTTP 状态码；两者都在，别只看后者。

| `code` | HTTP | 含义 |
|---|---|---|
| `1001` | 400 | 参数错 |
| `1002` | 404 | 找不到（方块 / 建筑 / 端点是哪个就写哪个） |
| `1003` | 400 | 坐标越界 |
| `1004` | 429 | 队列满或批量超限 |
| `1005` | 403 | 只读 / 该队没有建造单位 / 单位生成被禁用 |
| `1006` | 410 | 事件游标过期 |
| `1007` | 504 | 主线程超时 |
| `1008` | **409** | **`/place` 的 footprint 被别的建筑或固体地形占住**（挪一格就行） |
| `1009` | 400 | `/place` 被引擎拒绝，非占用所致（地形 / 规则 / 权限） |
| `1401` | 401 | 鉴权失败 |
| `1403` | 403 | 权限不足（admin 专属端点、token 与 agent 不符） |
| `1429` | 429 | 限流超限（每 agent 一个令牌桶，默认 `60/s`、突发 200，见「限流」一节） |
| `1500` | 500 | 服务端异常 |

**`1008` 与 `1009` 是分开的，别混**：前者挪一格或先 `/break` 就能成，
后者重试多少次都没用。响应里带 `conflictAt` 指向具体是哪一格挡着。

**同一个 `code` 可以配不同的 HTTP 状态**：`1007` 在主线程超时时是 `504`，
SSE 并发流超上限（8 条，见「SSE 事件推送」一节）时是 `503`。
判失败仍然只看 `code`，别拿状态码做唯一判据。

`<agent>` 是配置里分配的 agent 名（如 `alpha`、`referee`）。token 在
`server-run/config/ai-arena.json`：

```json
{"agents":[{"id":"alpha","token":"...","team":100,"admin":false},
           {"id":"referee","token":"...","admin":true}]}
```

`admin=true` 的 agent 可以带 `view=all` 参数看全图；非 admin 只能看自己队伍视野。

**admin 的凭据不从上面这个文件读。** 它的 token 只来自环境变量 `ARENA_ADMIN_TOKEN`
（≥16 字符）；配置文件里 admin 条目写的 token 一律被忽略，读不到环境变量时
**该 admin agent 干脆不注册**（fail-closed），裁判端点全部不可用。
理由见 [`CONDITIONS.md` 事故记录第 6 条](CONDITIONS.md)：这个配置文件与参赛 AI 同机可读，
把裁判权限明文放在里面，等于把 `view=all` 递给参赛者。

裁判脚本的取用顺序：`ARENA_ADMIN_TOKEN` → `server-run/admin-token.txt`（由 `start-arena.ps1` 生成）。
Python 侧用 `arena.load_admin_token()`；参赛客户端用 `arena.load_own_token(agent_id)`。

### 并发与执行顺序

**两条指令同时改同一格，谁生效？**

请求**不会立即作用于世界**。所有需要触及世界的端点都经 `Core.app.post` 投递到
**游戏主线程的队列**，由主线程按**入队顺序**逐个执行。

| 情况 | 结果 |
|---|---|
| 同一 tick 内**串行**发两条冲突指令 | 按你发送的顺序执行，后一条看到前一条的结果 |
| 用多线程/异步**并发**发两条冲突指令 | **入队顺序不确定**，谁先谁后都可能 |
| 两条指令间隔一个以上 tick | 按时间先后，无歧义 |

**冲突的典型表现**：两次 `/place` 抢同一格 —— 后执行的那次拿到 `1008`，
响应里的 `conflictAt` 指向被占的那一格。

**要确定性就串行发。** HTTP 往返天然是一个串行点：等上一条响应回来再发下一条，
顺序就完全确定，代价只是多一个往返。并发省下的那点时间，换的是不可复现的竞态。

**主线程超时**：单个请求在主线程队列里等超过 **3000 ms** 会返回 `504` + `code 1007`
（`op_expired`）。大战场导致主线程卡顿时，请求宁可超时也不无限排队 ——
这是为了保护整个接口不被打满（线程池 16 个，见「限流」一节）。

---

## 三、能获取的信息

> **本节所有字段都受一条契约约束，先读下面这节再看具体端点。**

### 信息可见性契约

**判据只有一条：一个真人玩家在同一队伍、同一状态下，用游戏 UI 能不能获取这条信息。**

能获取就给，不能获取就不给。**获取的难易不算数** —— 玩家放下一条带子看它往哪边流，
也算「能获取」，所以 `acceptsFrom` / `sendsTo` 是合规的。
界线落在**「看一眼就知道」**与**「要盯一段时间再算」**之间。

#### 给：屏幕上直接显示的

| 信息 | 对应玩家看到的什么 |
|---|---|
| `buildings[].items` / `liquids` | 选中自己的建筑，物品栏与液体栏直接列出来 |
| `buildings[].efficiency` | 选中建筑时的效率条 |
| `buildings[].powerStatus` / `powerLinks` | 电力条与激光连线 —— 断没断，一眼可见 |
| `buildings[].rotation` | 传送带流向、炮塔朝向、工厂出口，全画在屏幕上 |
| `buildings[].health` / `maxHealth` | 血条 |
| `buildings[].constructing` / `buildProgress` | 施工中的进度圈 |
| `buildings[].acceptsFrom` / `sendsTo` | 接口规则：放一条带子看它往哪流，玩家做一遍就知道 |
| `units[].*` 同理 | 血条、朝向、携带物；开火有枪口火光，弹道方向可见 |
| `stalls[]` 的 `kind` / `cause` | 带子完全不动、钻头不转、电力条空 —— 都是抬眼可见的现象 |
| `queue[].progress` | 建造进度条 |
| `queue[].etaSeconds` | 进度条在涨，盯着就能估出还要多久 |
| `intel` | 「确认核心数据」：连续看见敌方核心 10 秒，才放出库存快照 |
| `map[].visible` | 屏幕上那一块是不是亮的 |

#### 不给：需要观察 + 计算才能得出的

| 想要的东西 | 为什么不给 |
|---|---|
| 某条链的**吞吐上限**（如「1.2/s」） | 游戏从不显示速率数字。玩家要数物品、掐时间、自己除 | <!-- boundary-ok: 反面举例 —— 这一行写的正是「这种信息不给」 -->
| **瓶颈在哪一格** | 那是推导结果，不是显示结果 |
| **「这条链正在减速」** | 带子还在动，肉眼看不出来。`beltStall` 的判据是「完全不动」（`clogHeat` 逼近 1），不是「变慢了」 |
| **外推的产率预测** | `/rates` 给的是两个时间点的库存差 —— 玩家记两个数自己减也能得到，不外推 |
| **敌方建筑的 `items` / `liquids`** | 选中敌方建筑不显示库存。核心库存尤其：原版是无条件广播，本项目刻意改成「需确认」 |
| 敌方单位在雾里的**身份** | 看得到弹道往哪飞，看不到打的是谁（只给方向） |
| **视野内的全图矿脉** | 只能看 `map` 逐格查；不提供「附近有什么矿」的汇总 |

#### 缺省语义

**字段不出现，表示该信息当前不适用，不是「没查到」**：

| 字段 | 不出现的含义 |
|---|---|
| `buildings[].fogRadius` / `units[].fogRadius` | 该实体视野半径 ≤ 0（`gamma` 这类快速飞行单位就是 0，见 ENGINE-NOTES 第二十八节） |
| `units[].buildingAt` | 该单位没有待办计划 |
| `buildings[].acceptsFrom` / `sendsTo` | 该方块没有接货口 / 输出口的概念，或相邻格是空地 |
| `queue[].constructing` / `progress` | 该格还没开工（单位在赶路） |
| `queue[].stuckSeconds` / `hint` | 没有卡住 |
| `queue[].progressRate` / `etaSeconds` | 进度没在涨，推不出剩余时间 |
| `units[].targetX` | 没有交战目标 |
| `buildings[].config` | 该方块无配置 |

**别把「字段缺失」和「值为 0」混起来**：前者是不适用，后者是确确实实的零。
例如 `fogRadius` 不出现 ≠ 视野为 0 格，而是这个实体根本不贡献视野。

### `GET /ping`

无鉴权。返回 `{"ok":true,"data":{"headless":true,"tick":N,"agents":N}}`。

### `GET /state`

| 字段 | 含义 |
|---|---|
| `playing` | 是否在对局中 |
| `tick` | 当前 tick |
| `world.w` / `world.h` | 地图尺寸（格） |
| `self` / `teams` | 本队与各队概况（核心数、存活） |
| `limits` | **各接口的上限**，见下 |
| `vision` | **视野半径与所有视野源**，见下 |

#### `limits`

```json
{"mapWindowTiles":4096,"batchMax":200,"plansPerUnit":60}
```

| 字段 | 含义 |
|---|---|
| `mapWindowTiles` | `/map` 单次区域查询的格数上限；超了返回 `1004` |
| `batchMax` | `/place` 一次批量形状最多几格 |
| `plansPerUnit` | 单个建造单位的待办计划上限 |

**写在响应里就不用靠反复试探边界了。** 超限时的 400 响应体也会写明具体上限。

#### `vision`

```json
{"maxRadius":61,
 "sources":[{"kind":"building","x":289,"y":104,"radius":61}]}
```

每个视野源的位置与半径，`maxRadius` 是其中最大的。

**这条决定「能看多远」，超出的格子 `/place` 会返回 `1005`（HTTP 403）
并带 `target tile is not visible to team X`。**

> **两个易混的概念**：视野半径是 `fogRadius`（核心 61，与实测边界吻合），
> 而 `UnitType.buildRange` 是**建造范围** —— 两回事，别拿后者当视野用。
>
> **单位可能不贡献视野**：`UnitType.fogRadius` 默认 `-1`，由 `init()` 改写成正值；
> headless 服务器下部分单位类型仍是 `-1`，此时该实体不出现在 `sources` 里。
> 实测本图只有核心贡献（61 格）。

### `GET /map?x=&y=&w=&h=[&view=all]`

返回 `data.tiles` 数组，每格：

| 字段 | 含义 |
|---|---|
| `x` `y` | 坐标 |
| `visible` | 该格是否在查询者视野内 |
| `discovered` | 是否曾被探索 |
| `block` | 占据该格的方块名；`"air"` 表示空 |
| `floor` | 地表名 |
| `drop` | 该格矿脉掉落的物品名；空串表示无矿 |
| `dropHardness` | 该矿脉的硬度；`-1` 表示无矿 |

**未被视野覆盖的格子只会返回 `x` `y` `visible` `discovered`**，其余字段缺失。
所以可以先只看 `visible` 判断覆盖范围。

### `GET /buildings`

返回 `data.buildings` 数组：

| 字段 | 含义 |
|---|---|
| `x` `y` | **中心坐标**（多格方块取中心，不是左上角） |
| `team` | 队伍 id |
| `id` | **建筑唯一 id** —— `/command?action=commandBuilding` 要的就是它 |
| `block` | 方块名 |
| `health` / `maxHealth` | 血量 |
| `enabled` | 是否启用 |
| `efficiency` | 工作效率 0~1 |
| `rotation` | 朝向 0~3 |
| `items` | 该建筑库存 `{"物品名":数量}` |
| `itemCapacity` | **每种物品各自**的上限 —— **不是所有物品加起来的总量**。见下 |
| `liquids` | 液体库存 |
| `powered` | 是否有电（有电力接口的方块才有） |
| `acceptsFrom` | **能从哪几个邻格收货**（传送带专用），`[[x,y],...]` |
| `sendsTo` | **把货推到哪几格**，`[[x,y],...]` |
| `fogRadius` | 该建筑的视野半径；**仅在该值 > 0 时出现**（核心是 61） |

#### `itemCapacity` —— 每种物品各自的上限

**它不是一个总量。** 一台 `itemCapacity: 10` 的机器可以**同时**存 10 个沙 + 10 个煤，<!-- boundary-ok: 讲的是字段语义（每种物品各自的上限、不是总量）；10 只是举例，真值 `/buildings` 本来就逐台给 -->
互不挤占；煤不会因为沙多了而进不去。

判据在引擎里写得非常直接：

```java
// BuildingComp.getMaximumAccepted(Item item) —— 根本没用到那个 item 参数
public int getMaximumAccepted(Item item){ return block.itemCapacity; }

// BuildingComp.acceptItem —— 拿它跟**该物品自己**的数量比
return block.consumesItem(item) && items.get(item) < getMaximumAccepted(item);
```

**为什么值得单列一条**：这个误解会让策略整个跑偏。实测有一位 agent 认为
「沙煤比 2.35:1 超过了配方 2:1 ⇒ 沙会挤占煤的空间、必然缓慢塞满」，
于是**重建冶炼厂 4 次**（每次 `break` → 等 → `place`，约 15–25 秒）——
而**沙堆满只会让沙线堵住**（带子每格容量只有 1），**煤线独立、完全不受影响**。

所以看到「某个输入堆着不动」时，先分清楚是**建筑内部满了**还是**线上堵了**：

- 建筑内部：该物品数量 == `itemCapacity` ⇒ 它对这种物品不再收货（**别的物品照收**）
- 线上堵：带子容量只有 1，堆在带子上就是在**等下游**，与建筑内部空间无关

#### `acceptsFrom` / `sendsTo` —— 物流接口

这两个字段回答的是**接口在哪**，不是**这条链会不会堵**。

**`sendsTo`（所有建筑可能都有）**

- 传送带：正面那一格。**即使那是空地也会给** —— 那是它的朝向。
- 钻机：**挨着的所有建筑**。注意钻机输出**不受 `rotation` 控制**，
  它向所有相邻接收方推货，所以这个列表通常有多个。

**`acceptsFrom`（只有传送带有）**

按引擎的接货规则列出**背面 + 两侧**，正面（下游）是拒收的所以不列。
只列**该方位上真有建筑**的格，空地不列。

```
conveyor (282,109) rot=0   acceptsFrom=[[281,109]]         sendsTo=[[283,109]]
conveyor (283,109) rot=0   acceptsFrom=[[282,109]]         sendsTo=[[284,109]]
```

`rot=0` 面朝东，所以接货口在西侧（背面）—— 和读数一致。

> **为什么只列有建筑的那侧**：`acceptsFrom` 是**结构事实**，不随时间变。
> 别指望它告诉你「现在能不能收」—— 那取决于带子上挤不挤，
> 会来回抖，不适合放进快照。

**传送带的收货门槛不对称**（`Conveyor.java:358`）：背面宽松（`minitem >= 0.4`）、
两侧严格（`minitem > 0.7`）。**拐弯时货只能从侧面进，所以拐弯处特别容易堵** ——
这就是「图纸上对、实际堵死」的常见根因。

### `GET /units`

返回 `data.units` 数组。

| 字段 | 含义 |
|---|---|
| `id` `type` `team` `x` `y` `health` `maxHealth` | 基本属性 |
| `rotation` `canBuild` | 朝向 / 能否建造 |
| `stack` | 携带的物品 |
| `shooting` `targetX` `targetY` `targetId` `targetType` `targetTeam` | 开火与交战目标 |
| `buildingAt` | **这个建造单位当前在建哪一格**，见下 |
| `fogRadius` | 视野半径；**仅在该值 > 0 时出现**（headless 下单位常为 -1，见 `/state` 的 `vision`） |

#### `buildingAt`

```json
{"x":311,"y":130,"progress":0.0,"block":"conveyor"}
```

建造队列的**队首**就是它下一步要建的格子。`progress` 是施工进度 0~1：

- **轮询它就等于知道「还要多久」** —— 不必按自维护的清单盲撞（那份清单会因为
  丢单和服务端状态对不上）；
- **长时间不涨就是卡住了**，可以据此决定要不要用移动命令把它送走；
- 队列空时该字段**不出现**。

### `GET /rates?window=<秒>`

返回 `data.rates`：

| 字段 | 含义 |
|---|---|
| `team` | 队伍名 |
| `windowSeconds` / `fromTick` / `toTick` / `sampleCount` | 采样窗口信息 |
| `core` | 核心库存的 `{"物品":{start,end,delta,perSecond}}` |
| `stored` | 全队建筑库存合计的同结构数据 |

**`window` 是回看窗口，不是等待时长 —— 调用立即返回。**
服务端每 **5 tick**（≈12 次/秒）采一次样，环形缓冲覆盖最近 **120 秒**，
所以任何时刻都能问「最近 N 秒的变化」。

注意三个容易误解的字段（2026-10-06 实测确认）：

- **`window` 会被钳制**：小于 `0.5` 按 `0.5`、大于 `110` 按 `110`。
- **`windowSeconds` 是实际取到的跨度**，不一定等于你请求的值。数据不够时它就是
  「缓冲里最早的样本到现在」—— 实测请求 `200` 只得到 `28.6`（那一局才跑了 28 秒），
  请求 `0.5` 得到 `0.42`。
- **`sampleCount` 是缓冲区里现有的采样总数**（上限 1440），**不是窗口内的采样数** ——
  实测 `window=0.5` 与 `window=30` 的 `sampleCount` 几乎相同。

**`core` 只列 `delta != 0` 的物品；`stored` 还会列出「曾经或现在非零」的物品**，
所以看到一堆 `delta=0` 的条目是正常的。

**按目的选窗口**：

| 目的 | 用 | 理由 |
|---|---|---|
| 验证刚做的改动生效了没 | `1~3` | 几乎无滞后 |
| 看稳定产率 | `30~60` | 抹掉瞬时波动 |

**长窗口会把新改动稀释掉** —— `window=30` 里有 25 秒是改动前的数据，
刚下的机器只贡献最后几秒。「改了却看不出效果」多半是这个原因，不是没生效。
窗口内不足两个采样点时会返回 `window too short, only one sample`。

### `GET /stalls`

产线异常警报。支持 `?view=own|<teamId>|all`（默认 `own`），返回 `data.stalls` 数组：

| 字段 | 含义 |
|---|---|
| `kind` | `beltStall` / `drillBlocked` / `factoryBlocked` / `missingInput` / `powerUnconnected` / `powerStarved` |
| `x` `y` | 出问题的位置 |
| `item` | 相关物品（有则给出） |
| `cause` | **一句话说清该往上游查还是往下游查**，见下 |

#### `cause`：停机该往哪查

| 取值 | 含义 | 往哪查 |
|---|---|---|
| `starved` | 上游没把料送来（缺输入） | **上游** |
| `outputBlocked` | 自己有料且已满仓，出料侧不收 | **下游** |
| `outputRefused` | 出料侧不收，但自己还没满仓（刚堵上） | 下游 |
| `unpowered` | 需要电，但**一根线都没接** | **查电网** |
| `underpowered` | 接了线，但电力不够（发电机不足 / 链路断） | **查电网** |
| `unknown` | 其它情况，看 `missing` | 都不像 |

判据：**`efficiency == 0` 且满仓 ⇒ 输出路径不通；缺料 ⇒ 输入路径不通。**

> 这些以前要靠 `outputAccepts` 和 `missing` 自己拼。典型误判是「核心满了 →
> 整条上游线回堵 → 上游钻机全部 `eff=0.0` 且满仓」，看着像产线坏了，
> 其实是**下游吃饱了**。

#### 返回范围：按视角裁剪

**只返回你自己队伍、且当前视野内的方块**，判据与 `/buildings` 完全一致。

这条不是可选的严格性，是可用性问题。2026-10-06 的人机对局里，`/stalls`
返回的是**全图所有队伍**的表：一次拿到 40 条，其中 **39 条是对手的**
（`team: sharded`），自己那条唯一的故障（石墨压缺煤）淹没在里面。
AI 那个位置看不出「哪几条是我该管的」——它读了 25 次告警，没有一次是朝
自己那条煤线去的。

裁判 / 观察者传 `view=all` 拿全图；普通 agent 传别人的队伍会被静默降级成自己的视角
（和 `/buildings` 同一套规则，见 [DESIGN.md](DESIGN.md) 的 P5）。

#### 覆盖范围：只报「看一眼就知道」的

判据和**人类肉眼能看到的**对齐：

| 报 | 为什么 |
|---|---|
| `beltStall` | 带子**完全不动** —— 堵死了，一眼可见 |
| `drillBlocked` | 矿机**不出货**（钻头满仓转不动） |
| `powerUnconnected` / `powerStarved` | 电力条空 / 连线断，屏幕上直接显示 |
| `missingInput` | 方块停着；配方要什么、库里有不有，选中就能看 |

**不报**「这条链在减速」「吞吐上限只有 1.2/s」这类 —— 那是**观察 + 推导**得出的，<!-- boundary-ok: 反面举例 —— 这句正是在说明它不报 -->
游戏界面从不显示，得自己盯一段时间算出来。接口直接给就等于送答案。

同理 `beltStall` 的阈值是引擎的 `clogHeat` 逼近 1（约堵了一秒），
对应的是「肉眼确认它卡住了」，而不是「它比刚才慢了」。

### `GET /watch?since=<事件序号>`

**把「有没有值得注意的事」合成一个判断** —— 用来决定「现在能不能睡」。

```json
{"tick":18432,"clear":false,"reasons":["stalls","newEvents"],
 "counts":{"stalls":3,"plans":42,"stuckPlans":1,"worstStuckSeconds":31.2,"newEvents":7},
 "sinceSeq":1234,"nextSince":1241,
 "hint":"有事要看：停机 → /stalls；队列 → /queue；新事件 → /events?since=1234"}
```

| 字段 | 含义 |
|---|---|
| `clear` | **没有待处理的事** —— 可以安心睡到下一次事件 |
| `reasons` | 当前不 `clear` 的原因（`stalls` / `queueStuck` / `newEvents`） |
| `counts.stalls` | 己方处于异常状态的方块数（**只算自己队**） |
| `counts.stuckPlans` | 停滞超过 10 秒的建造计划数 |
| `counts.worstStuckSeconds` | 最久的那个停滞了多久 |
| `counts.newEvents` | 自 `since` 以来新增的事件数 |
| `nextSince` | 下次调用时该传的 `since` |

**为什么有这个端点**：实时游戏里 AI 跟不上 tick（引擎 60 tick/s，一次决策是秒级），
所以正确形态是「**有事才醒**」。但光知道「有事发生」不够 —— 你还得有一个明确的
「**现在没事**」信号，否则不敢睡，只能一直轮询。

**它只做聚合，不新增信息**：每一项都能用 `/stalls`、`/queue`、`/events` 单独查到，
这里的价值是**一次请求给出单一判断**。它不告诉你「为什么会堵」或「该改哪一格」——
那要自己看。

### `GET /await?until=<谓词>&timeout=<秒>`

**谓词等待原语** —— 让**服务端**替你等一个状态出现，而不是客户端轮询。
理由很实际：轮询的**每一次都是一趟模型往返**，等一次建造可能烧掉几十轮；
让服务端在主线程按 tick 判，把「轮询 30 次」压成「一次调用」。

| 谓词 | 含义 |
|---|---|
| `built:<x>,<y>` | 该格已建成**己方**建筑 |
| `rate:<物品>:<n>` | 己方核心该物品净产率 **≥ n**（10 秒窗口） |
| `queueEmpty` | 己方建造队列为空 |
| `noStall` | 己方没有处于异常状态的方块 |

```json
{"satisfied":true,"until":"built:289,104","waitedSeconds":0.01,"tick":412,
 "hint":"条件已满足 —— 可以继续下一步"}
```

**超时不是错误**：HTTP 仍返回 `200`，用 `satisfied` 区分 —— 据此决定重试还是改计划。
`timeout` 默认 90、范围 0.5–600 秒。

**同时挂起的等待数上限是 `httpThreads / 4`**（线程池默认 16 → **4 个**），超了回 `503 / 1007`。
这个数为什么这么小：**每个挂起的等待占一个 HTTP 线程**（服务端每请求一线程），
若把上限设成线程池大小，若干个等待就能把整个接口层堵住 —— 连 `/ping` 都排不上队。

> 实测（2026-10-06）：上线时上限误设为 16（**恰好等于线程池默认大小**），
> 20 个并发请求的耗时正好是 `timeout` 的两倍（分两批串行）——**限流根本没触发过**。
> 改成 `httpThreads / 4` 后复测：20 个并发 → 16 个立刻 `1007`、4 个正常挂起，
> 总耗时 5.1 秒，且期间 `/ping` 在 **33ms** 内响应。

谓词不合法或物品名不存在 → `400 / 1001`，响应里列出支持的形式。

#### 语法为什么用冒号，不用 `>=`

`>` 在 URL 里是**非法字符**：`?until=rate:copper>=5` 会在**到达服务端之前**
就被 HTTP 层拒掉（`400 Bad request URI`）——看起来像端点坏了，实际是调用方没编码。
所以写成 `rate:copper:5`（意为 ≥ 5），全用冒号，**不需要任何 URL 编码**。

#### 只等你自己队的状态

四个谓词的观察对象**一律是调用方自己的队**，没有「指定其它队」的变体 ——
那等于用服务端算力换情报，越过对等约束。

#### 一个实测到的坑

`setup` 之后头 10 秒里 `rate:` 会**虚高** —— 初始资源是瞬间灌进核心的，
被 10 秒窗口当成「产出」算了进去（实测刚开局问 `rate:copper:5` 就 `satisfied`）。
要对产率下判断，等开局过去十几秒。

### `GET /drill`

返回 `data.drills` 数组，每台矿机：

| 字段 | 含义 |
|---|---|
| `x` `y` `block` | 位置与方块 |
| `items` | 当前库存 |
| `dominantItem` | 当前正在挖的物品 |
| `ore` | 脚下各矿格明细 `[{x,y,item,hardness}]` |

### `GET /factory`

单位工厂：`x` `y` `block` `efficiency` `enabled` `powered`
`plan` `progress` `planIndex` `payload`。

### `GET /ore?x=&y=`

指定格的地表与矿脉明细。

### `GET /queue`

建造队列：每个建造单位在排队的计划，**逐条带坐标**。

```json
{"builders":[{"unit":219,"type":"gamma","plans":49,"planList":[
  {"x":241,"y":66,"breaking":false,"block":"conveyor"},
  {"x":251,"y":152,"breaking":false,"block":"conveyor"}
]}]}
```

| `planList[]` 字段 | 含义 |
|---|---|
| `x` `y` | 目标格（**多格方块传中心**） |
| `block` | 目标方块 |
| `breaking` | `true` = 这是拆除计划 |
| `constructing` / `progress` | **只在该格已在施工时出现**：施工进度 0~1 |
| `progressRate` / `etaSeconds` | 实测进度变化率（进度/秒）与据此外推的剩余秒数 |
| `stuckSeconds` / `stuckReason` / `hint` | **只在真的卡住时出现**，见下 |

#### `stuckSeconds`：卡住的计划

```json
{"x":314,"y":79,"block":"conveyor","stuckSeconds":12,
 "hint":"move the builder to the site to break it loose: /control?op=order&unit=219&x=314&y=79"}
```

判据是**进度连续不变、且建造单位自己也不动**，持续超过 3 秒。

`stuckReason` 说明**为什么卡** —— 四种取值，前三种都对应玩家能直接看到的现象：

| 取值 | 含义 | 你该做什么 |
|---|---|---|
| `missingMaterials` | 核心里的料不够了（`/place` 时够，后来被别的建造消耗掉） | 补产该物品，或 `POST /queue?clear=true` 清掉这条 |
| `tileOccupied` | 那格上已经站着别的建筑 | `/break` 拆掉，或对同格再 `/place` 一次改目标 |
| `builderTooFar` | 单位离工地比 `buildRange` 还远 | 用 `/control?op=order` 把它送过去 |
| `unknown` | 单位自己的状态机卡死 —— **从外部判定不了，如实报 unknown** | 试 `op=order` 推一把 |

`hint` 按 `stuckReason` 给对应的解法。**注意它只有在 `builderTooFar` 时才建议移动命令** ——
被墙挡住的话推过去还会卡回来，那不是解法。

> `missingMaterials` 是那种「`/place` 时说够、之后悄悄变不够」的情况：
> 材料被别的建造消耗了，队列里的计划就一直卡着。以前只报「卡了 12 秒」，
> 看不出是这个原因。

#### `progressRate` / `etaSeconds`：还要多久

`progressRate` 是**实测**的进度涨速（两次采样之差 ÷ 时间），`etaSeconds` 由它外推：
`(1 - progress) / progressRate`。

**和 `buildTime.seconds` 是两个口径**：前者是理论施工时长、不含走路；
后者是从实际进度推出来的**剩余**时间，含已经被走掉的部分。
进度没在涨时 `etaSeconds` 不出现 —— 那时该看 `stuckSeconds`，而不是瞎估一个数。

实测 `scatter`（理论 1.23s）：

```
progress=0.24  rate=0.86  eta=1
progress=0.55  rate=0.95  eta=0
progress=0.99  rate=0.70  eta=0
⇒ 由速率反推的总时长 = [1.16, 1.23, 1.05, 1.25, 1.25, 1.43]
```

**这是「盯着进度条看它涨多快」**，真人抬眼就能做的事；接口只是把它自动化了。

> **为什么还要看单位动没动**：`BuilderComp` 只在目标格变成施工中之后才把施工进度
> 写回计划 —— 单位还在赶路的这段时间里进度恒为 0，**不变，但不是卡住**。
> 只看进度会把「离得远、还在走过去」误报成停滞。真人判断卡住看的也正是这两件事：
> 方块不出现、单位也站着不动。

`hint` 直接给出验证过的解法：**队列卡死时用移动命令把它推开**
（`/control?op=order` 收格坐标），实测 `plans` 一次从 56 降到 1，沿线方块真的建成。
`/break` 对排队中的计划**无效**，反而会追加拆除计划。

早期只给一个 `plans` 计数，AI 拿不到坐标 —— 想加速建造就得自己维护一份 pending
清单，而丢单会让清单和服务端实际状态对不上。有了 `planList` 才能精确定位卡住的计划。

`POST /queue?clear=true` 清空全队待办计划：

```json
{"cleared": 60, "message": "cleared 60 pending plan(s)"}
```

`cleared` 是结构化字段，直接读它 —— 别去解析 message。

### 批量下单的返回：`tiles` 是请求数，`accepted` 才是排上的

`/place` 与 `/break` 走 `shape=` 时是批量。返回里两套数字**含义不同**：

| 字段 | 含义 |
|---|---|
| `tiles` | 你**请求**了多少格 |
| `requested` | 同上（显式字段） |
| `accepted` | 真正排上队的条数 |
| `skipped` | `{invalid, invisible, noUnit}` 的分项 |
| `limitReached` | 是否撞到了 `plansPerUnit`（默认 60） |

**超过 `plansPerUnit` 的部分是被静默丢弃的**：实测请求 70 格、队列上限 60，
返回 `ok: true` 而 `accepted` 只有 60。只读 `tiles` 会以为 70 条都排上了。

```json
{"requested":70, "accepted":60, "skipped":{"invalid":10,"invisible":0,"noUnit":0},
 "limitReached":true, "plansPerUnit":60, "tiles":70, "shape":"line", "message":"..."}
```

想确认到底排上了多少，**读 `accepted`，或者直接看 `/queue` 的 `plans`**。

### `GET /diag`

服务端诊断计数器，含快照路由统计
`teamBatchSends` `fullViewSends` `spectatorRouted`，以及 **`endpointCalls`**。

**仅 admin。** 非 admin 调用返回 HTTP `403`，body 为 `code 1403`。

#### `endpointCalls` —— 谁调了哪些端点、各多少次

```json
{"<agent>:rates": 41, "<agent>:stalls": 3, "<agent>:buildings": 12, "<agent>:place": 6}
```

键是 `agentId:action`，按次数从多到少。**默认只给调用方自己的那一份**
（`agentId:` 前缀匹配）；`canReferee` 的 agent 能看到全部。

**为什么要有它**：审计日志只记**改状态**的操作，于是「AI 到底有没有读 `/stalls`」
这类问题**从外部无法回答** —— 曾经连续两轮改提示词要求 AI「每轮读 `/stalls`」，
却始终不知道它是没读、还是读了没照做，只能从结果反推，那就是猜。

有了这个计数，那类问题变成可观测的。几个直接可读的信号：

| 现象 | 说明 |
|---|---|
| `stalls` 计数很低而 `place` 很高 | 它只顾着铺新的，**没有巡检** |
| `queue` 计数远高于其它 | 它在**轮询等建造**，而不是用 `/await` |
| `await` 计数为 0 | 一次都没用谓词等待原语 |
| `rates` 计数很低 | 它没在跟踪产率变化 |

> 实测：观察到某一局里 `queue` 的调用次数是 `place` 的**数倍** ——
> 也就是大部分模型往返花在「问好了没」上。**这个结论在加 `endpointCalls` 之前拿不到。**

#### `endpointLastCall` —— 每个端点最后一次是什么时候调的

```json
{"<agent>:stalls": {"lastMs": 1791382585197, "agoSec": 42.5},
 "<agent>:place":  {"lastMs": 1791382582911, "agoSec": 44.8}}
```

键与可见性口径跟 `endpointCalls` **完全一样**（`agentId:action`、默认只看自己的、
`canReferee` 能看全部），只是换成时刻。按**最近调过的排前面**。

**为什么计数之外还要这个**：计数答得了「它读了多少次 `/stalls`」，
**答不了「它读完告警之后紧接着做了什么」** —— 而分清「没读」和「读了没照做」
恰恰需要后者。审计日志补不了这一半：它只记**改状态**的操作，读接口一条不留。

`agoSec` 由服务端算好，省得你拿本地时钟去对（两边本来就在同一台机器上）。
把它和上面的计数并排看，能直接读出一类信号：

| 现象 | 说明 |
|---|---|
| `stalls` 的 `agoSec` 很小，但之后没有任何 `place` / `batch` | **读了，但没照着改** |
| `stalls` 的 `agoSec` 一直很大 | **压根没巡检** |

> **纯粹是遥测**：只记「什么时候调的」，不记请求内容、不给任何建议 ——
> 它不会告诉你该建什么、该改哪一格。

### `GET /content`

方块 / 物品 / 单位表。**运行时取用，不要凭记忆。**

### `GET /database`

**对应游戏里的「数据库」界面**，而且多做了一件游戏内做不到的事：**反查**。
四个分支按参数优先级：

| 参数 | 做什么 |
|---|---|
| `item=<物品名或液体名>` | **反查**：谁产它、谁吃它、哪些矿机能挖它 |
| `q=<关键词>` | 跨 方块 / 物品 / 单位 / 液体 搜名字与介绍 |
| `cat=<分类名>` | 列出该分类下的方块（带 `requirements`） |
| （无参数） | 索引：分类清单 + 物品清单 |

`limit` 默认 60、范围 1–400。名字不存在时返回 `404 / 1002`。

**`item=` 接受液体**（2026-10-06 补）。传液体时返回体带 `kind:"liquid"`，
字段换成液体的那组（`flammability` / `explosiveness` / `heatCapacity` / `viscosity` / `temperature`），
`producers[]` 的 `how` 会区分 `crafter` / `solid-pump(+ baseEfficiency N，attribute X)` /
`pump(地表，视建址而定)`；`consumers[]` 的 `how` 形如 `booster <N>/s` 或 `consumes <N>/s`
（`amount` 在引擎里是**每 tick**，这里已乘 60 换成每秒，与游戏 tooltip 的显示口径一致）。

> 为什么这条重要：**固体矿能靠 `/ore` 找到，液体不能** —— `/ore` 只列矿脉。
> 于是「这个资源在图上找不到产地」和「这个资源根本不存在」在接口上长得一模一样，
> 而复盘发现 AI 正是卡在这里：它查到钻机 `inputs` 里有可选的 `water`，想加水加成，
> `/map` 上找不到水源，于是去问「谁能产水」—— 而 `/database?item=water` 当时返回 404。
> **它的推理没错，是接口答了「不存在」。**

#### `?item=` 是它最有用的一支

```json
{"item":"silicon","localizedName":"硅","hardness":0,
 "producerCount":9,"producers":[{"name":"silicon-smelter","how":"crafter","size":2}, …],
 "consumerCount":18,"consumers":[{"name":"surge-smelter","how":"items x3"}, …],
 "drills":[{"name":"laser-drill","tier":4,"size":3}, …]}
```

「缺硅怎么办」这类问题不必靠试错：`producers[]` 直接给出能产它的方块与**方式**
（`crafter` = 加工、`drill(tier N)` = 挖），`drills[]` 是**按 `tier >= 该物品的 hardness` 过滤过**的
可挖矿机清单。「谁在吃铜」同理。

`how` 是**分类标签**、不是配方数字（`items x3` 表示吃三种物品）；配方本身在 `/block?name=<方块>`。

**方块详情不在这个端点里，用 `/block?name=`** —— 那边给得更全（成本 / 输入 / 输出 / 尺寸）。
（2026-10-06：`/database` 此前还有一对「读进来但从未使用」的 `block=` / `type=` 参数，
传了会静默落到索引分支，而 `usage` 文案却宣称支持 `block=` —— 已删掉并改正文案。）

### `GET /events`

事件流，**游标增量**：`?since=<seq>` 只返回该游标之后的事件，响应里带 `nextSince`。

| 字段 | 含义 |
|---|---|
| `since` / `nextSince` | 本次起点 / 下次该传的值 |
| `count` / `buffered` | 本次条数 / 缓冲区里还有多少 |
| `events[]` | `{seq, tick, type, team, x, y, detail}` |

#### 用它替代全量拉 `/buildings`

**想知道「自上次以来产线变了什么」，不用重拉 250+ 条建筑再自己 diff。**
`/events` 的差分补齐覆盖了这几类：

| 事件 | 触发 |
|---|---|
| `buildAppear` / `buildGone` | 方块建好 / 被拆 |
| `unitAppear` / `unitGone` | 单位出现 / 消失 |
| `configure` | 方块配置改变 |
| `blockPlace` | 下单成功 |

实测建 5 个 conveyor，增量只拿到 5 条 `buildAppear`（各带 `detail.{x,y,block}`），
而不是全量那份建筑表：

```
{"seq":8,"tick":373,"type":"buildAppear","team":2,"x":2184.0,"y":632.0,
 "detail":{"x":273,"y":79,"block":"conveyor"}}
```

**推荐用法**：开局拉一次 `/buildings` 建基线，之后用 `/events?since=<nextSince>`
维护增量。方块只存增量这一条对客户端同样适用 —— 多数方块长期不变。

### `GET /intel`

情报汇总。

### `GET /block`

方块详情。传 `name=<方块名>` 取单个方块的完整定义（含 `details` 说明文案）；
不传 `name` 则列出**全部可放置且未隐藏**的方块。

**几个容易看漏、但决定布局成败的字段**：

| 字段 | 含义 | 为什么重要 |
|---|---|---|
| `drillSpeed` | 钻机在**满矿**（footprint 全是矿）时的理论速率，单位 **items/s** | 四台钻机的其余顶层字段**完全一样**，唯一区别是 `outputs[].tier` —— 而 **tier 只表示「能挖多硬的矿」，不表示快慢**。想横向比速度只有看这一栏。实际速率还要乘矿种硬度带来的折扣，具体能挖多少看 `/ore` 与 `/drill` |
| `powerUse` | 耗电（顶层） | `powerProduction` **只覆盖发电方块**；耗电方块以前顶层什么都不给，会让人把要 0.5 电的硅冶炼厂读成「不用电」 |
| `inputs[].optional` | `true` = **有它更快、没它也能干** | 引擎自己就把「可选加成」和「必需输入」分开了（`ConsumeLiquidBase.booster`）。四台钻机全都列着 `water` 且**看着像非接不可**，而实测不接水也 `eff=1.0` —— 看 `optional` 就不会误判 |
| `outputs[]` 的 `kind` | `item` / `liquid` / `power` / `ore` / `unit` / `transport` | **产出不来自配方的方块也在里面**：泵类（`water-extractor` 等）给 `kind=liquid` + `perSecond` + `baseEfficiency` + `attribute`，钻机给 `kind=ore` + `tier`，**转运件给 `kind=transport` + `how` + `note`**。这三类别以前都是空数组 |
| `area` | **它能作用到多远**，单位一律 `blocks`（格） | `description` 只用相对说法——「连接范围**更大**的高级电力节点」「用于**远距离**连接，但连接数**较少**」——而布局需要的恰恰是**绝对值**。实测：`power-node` = 6 格 / 10 个连接，`power-node-large` = 15 / 15，`surge-tower` = 40 / 2，`mend-projector` = 10.63 格。没有范围概念的方块给 `{}` |

> **`area` 的单位是逐个对齐引擎 tooltip 的，因为两类不一样**——这正是那种「看着对其实差 8 倍」的坑：
> `PowerNode` 用 `Stat.powerRange, laserRange, StatUnit.blocks`（**本来就是格**），
> 而 projector 用 `Stat.range, range / tilesize, StatUnit.blocks`（**像素，要除以 8**）。
> 把它们当同一种单位读，`mender` 的「5 格」就会变成「40 格」。

**转运件的 `transport` 条目说的是「它怎么送」** —— 这是它们唯一的语义，而配方视角下它们一片空白：

| `how` | 规则 |
|---|---|
| `conveyor` | 沿朝向逐格推进；**背面来货门槛松、侧向也收但门槛更严** —— 拐弯处因此特别容易堵 |
| `armored-conveyor` | 同传送带，但**侧向输入只接受其他传送带送来的货**；建筑从侧面直接送不进来（必须对准背面） |
| `duct` | 沿朝向单格输送 |
| `conduit` | 沿朝向输送液体（液体管道不按物品过滤） |
| `armored-conduit` | 同液体管道，但侧向输入只接受其他管道、液体桥或液体交叉送来的 |
| `stack-conveyor` | 沿朝向推进，一次搬运一整叠 |
| `junction` / `duct-junction` / `liquid-junction` | **交叉不打结**：各方向的货各自直行穿过、互不混流 |
| `router` / `duct-router` / `liquid-router` | **在所有可收的邻格之间轮流发** —— 这就是「一路分多路」 |
| `sorter` / `inverted-sorter` | 按**配置的那个物品**过滤：匹配的走朝向，不匹配的走背面 |
| `overflow-gate` / `underflow-gate` / `overflow-duct` | 两个候选出口，按对方当前 `acceptItem` **实时**判断：优先一侧，它不收就溢到另一侧 |
| `bridge` / `buffered-bridge` / `duct-bridge` / `direction-bridge` / `liquid-bridge` | 跨格送到配对的另一端 |
| `mass-driver` | 把货物抛射到配对的接收端 |
| `unloader` / `directional-unloader` | 从相邻容器或核心取货送出 —— **核心是终点，得有它才能把库存取出来** |

> **为什么补这一段，以及一个我先前的误判。** 这批方块的 `inputs` 与 `outputs` 确实**是空数组**，
> 我当时据此写下「接口告诉 AI 这一类什么都不做」。**这是错的** —— 同一个响应里的
> `description` 一直写着规则，而且 `/database?q=` 连中文描述一起搜：
>
> ```
> block.underflow-gate.description = 与溢流门相反，当两侧均堵塞时才向前运输。
> block.overflow-gate.description  = 当前方被阻塞时才会向两侧输出，用于处理多余的物品。
> /database?q=溢流  → overflow-gate, underflow-gate, overflow-duct, underflow-duct
> ```
>
> 所以缺的**不是信息，是形式**：规则以**散文**存在（`description`），结构以**字段**存在
> （`inputs` / `outputs`），而字段那一半是空的 —— AI 读字段、不读散文。
> `transport` 条目的价值因此要说准：**不是补上缺失，是把已经写着的规则翻成可机读的形式。**

**泵类的 `baseEfficiency` / `attribute` 是回答「它非要建在水源上吗」的两个字段**：产能 = `baseEfficiency + 脚下的 attribute 值`，而 `attribute` 只是**加成**项。只看 `attribute=water` 会得出「没水就不能用」——那是错的。

> 这段话来自一次实测：AI 查到钻机 `inputs` 里有 `water (optional)`，想找水，`/map` 上没有，于是查「哪个方块产水」，而 `water-extractor` 的 `outputs` 当时是 `[]` —— 它的每一步推理都成立，结论却是「这张图的水拿不到」。
>
> **措辞要准**：不是「接口告诉它没有水」—— `water-extractor` 的描述里一直写着「从地下提取水，**适用于附近没有地表水的情况**」，信息从来没缺。准确的说法是：**它读的那一半（结构字段）是空的，而规则写在另一半（散文）里。** 见上面那段自我更正。

`outputs[].tier` 是**采矿等级**：钻机只能采 `hardness ≤ tier` 的矿（`/ore` 的 `canMine` 就是这个判定的结果）。

### `GET /maps`

列出引擎里所有地图的**真实属性**，含 `teams` 数量与 PvP 可用性。选图前用它核对，别猜。

> PvP 的判定标准是 `map.teams.size > 1`（`Gamemode.pvp` 的地图判定条件）
> 与 `Maps.pvp()` 的 tag；**`spawns` 是「玩家出生点」，与核心无关** ——
> 早期按 `spawns` 判断走过弯路。

### `GET /observe`

当前视角状态：`currentView`、`canSeeAll`，以及**本 agent 能观察哪些队**（每队带 `viewable`）。
非 admin 只有自己队 `viewable=true`；请求别人的视角会被**静默降级**为自己的，不报错。

---

## 四、可执行的操作

| 接口 | 参数 | 说明 |
|---|---|---|
| `POST /place` | `x` `y` `block` [`rot`] [`unit`] [`config`] | 下建造请求（见下方说明） |
| `POST /batch` | `ops=` | **一批操作** —— 一次请求做多个 place/break/config，省模型往返（见下） |
| `POST /break` | `x` `y` | 拆除 |
| `POST /config` | `x` `y` … | 设置方块配置 |
| `POST /command` | `action=` `units=` … | 指挥单位（8 种 action，见下） |
| `POST /control` | `op=` … | 单位操控。`op` 取值（11 个）：`pos` `move` `order` `enter` `release` `fire` `stopmove` `orders` `probe` `ticks` `warp`；**`warp` 默认禁用**（见下）；要移动单位用 `move` 或 `order` |
| `POST /spawn` | `type` `x` `y` [`team`] | **默认禁用**，见下 |
| `POST /mine` | `x` `y` [`unit`] | 让单位挖指定格 |
| `POST /record` | `action=start\|stop` | 录像开关 |
| `POST /chat` | `text` | 发言 |
| `POST /admin` | `action=` … | 管理操作（仅 admin） |

`rot` 取值 0~3（`0=东 1=南 2=西 3=北`）。各 `block` 的参数（尺寸、配方）由 `/content` 在运行时提供。

### `/batch` —— 一次请求做一批操作

**为什么要有它**：参赛 AI 的一次「思考」是一个**模型往返**（秒级到几十秒），而一局只有
15~30 分钟。如果每次往返只下一个命令，**能做的操作数会被往返延迟硬性卡死** ——
实测有一局 30 分钟内改了 **181 次**状态（`place` 163 + `break` 18）；
若一命令一往返、每往返 10 秒，光往返就吃掉了整局。

`shape=` 解决了「同一种方块的一条连续线」，但装不下**一批互不相干的动作**
（不同方块、不连续的位置、`place` 与 `break` 混在一起）。这个端点补的就是那一段。

```
POST /v1/{agent}/batch?ops=<动作;动作;...>
```

每项用 `,` 分隔：

| 动作 | 格式 | 例 |
|---|---|---|
| 放置 | `p,x,y,block[,rot]` | `p,285,107,conveyor,0` |
| 拆除 | `b,x,y` | `b,290,110` |
| 配置 | `c,x,y,config` | `c,288,109,coal` |

```json
POST /v1/beta/batch?ops=p,285,107,conveyor,0;p,286,107,conveyor,0;b,290,110

{"ok":true,"data":{
  "requested":3, "applied":2,
  "failed":[{"i":2,"op":"b","x":290,"y":110,"code":1002,"error":"no block at (290,110)"}],
  "message":"batch requested=3 applied=2 failed=1"
}}
```

**语义**：

- 整批在**同一次**主线程投递里执行 —— 这才是省往返的关键，不是把 N 个请求并发发出去。
- **逐条独立**：一条失败不影响其余，**整批仍返回 `200`**，看 `applied` 与 `failed[]`。
- `failed[]` 带**原始下标 + op + 坐标 + 错误码**，不用去猜是哪条没成。
- 条数上限 `Operations.MAX_BATCH`（在 `/state` 的 `limits.batchMax`），超了整批拒绝。
- 格式错就**整批拒绝**（不执行一半）—— 免得留下半截状态。

### `/place` 响应：材料清单

**每次 `/place` 都会返回 `materials`：这个方块要什么、你现在有多少、还缺多少。**
不必再靠「反复重试然后猜为什么建不出来」。

```json
{"ok":true,"data":{
  "mode":"new",
  "builder":{"id":219,"type":"gamma"},
  "pendingPlans":1,
  "materials":{
    "adequate":false,
    "requirements":{
      "0":{"item":"copper",  "need":35,"have":499,"ok":true, "short":0},
      "1":{"item":"graphite","need":30,"have":0,  "ok":false,"short":30},
      "2":{"item":"titanium","need":20,"have":0,  "ok":false,"short":20},
      "3":{"item":"silicon", "need":30,"have":0,  "ok":false,"short":30}
    }
  },
  "message":"queued laser-drill at (283,110) by gamma; pending plans=1"
}}
```

| 字段 | 含义 |
|---|---|
| `materials.adequate` | **材料是否全够**。`false` ⇒ 这计划会一直卡着不动，别等它 |
| `requirements[].need` | 需要多少 |
| `requirements[].have` | **核心现有多少** |
| `requirements[].ok` | 该项是否够 |
| `requirements[].short` | **还差多少**（够则为 0） |

**`adequate=false` 时不要重试** —— 重试不会让材料变多。去看哪些 `ok=false`，先补那些物品的生产。

**另注**：`ok:true` 只代表**请求已入队**，不代表建造完成；材料够 + 建造单位走到位置之后才会真正开工。

### `/place` 的 `buildTime`：施工要多久

```json
{"buildTime":{"seconds":1.23,"buildCost":74.0,"builderSpeed":1.0}}
```

| 字段 | 含义 |
|---|---|
| `seconds` | **施工时长**（不含单位走过去的时间） |
| `buildCost` | 引擎的 `ConstructBuild.buildCost` |
| `builderSpeed` | 该建造单位的建造速度倍率 |

公式照抄引擎（`BuilderComp.java:246` + `ConstructBlock.java:451`）：

```
每帧增量 = type.buildSpeed × buildSpeedMultiplier × rules.buildSpeed(team) / buildCost
buildCost = block.buildTime × rules.buildCostMultiplier
seconds   = buildCost / (speed × 60)
```

**这是「规则」** —— 方块属性 + 单位速度，玩家看着进度条的涨速也能感知快慢。
**但它不含走路时间**：单位得先走到工地。真实耗时看 `/queue` 的 `etaSeconds`。

实测（gamma，speed=1）：`conveyor` 0.01s、`router` 0.1s、`silicon-smelter` 0.54s、
`scatter` 1.23s —— 和「由实测速率反推的总时长」吻合到 1%。

### `/place` 的 `mode`：转移建造目标

**对同一格重复 `/place` 换一种方块，会「转移」该格的建造目标** —— 旧计划被替换；
若那格**已在施工中**，新计划**继承已有进度**。等价于玩家对建造中的方块改目标。

```json
{"mode":"transfer","previousBlock":"conveyor","inheritedProgress":0.0}
```

| `mode` | 含义 |
|---|---|
| `new` | 该格原本无计划/建筑，属新建 |
| `transfer` | 该格原本有计划或半成品，**已被替换**；`previousBlock` 是原目标 |

**铺错不用先 `/break`**，对同格再 `/place` 一次即可，进度不浪费。
`/buildings` 里名字以 `build` 开头的（`build1`/`build2`）就是**施工中的格子**，
对这些格子重新 `/place` 即为转移目标。

### `/place` 返回的 `appliedRot` / `anchorX` / `anchorY` / `size`

每次 `/place` 都带回**实际生效**的朝向与引擎内部的锚点坐标 ——
不用让每个 AI 自己推坐标系转换：

| 字段 | 含义 |
|---|---|
| `appliedRot` | **归一化之后**的实际朝向（`0`=东 `1`=南 `2`=西 `3`=北）。**不可旋转的方块恒为 `0`** —— 见下 |
| `anchorX` / `anchorY` | 该方块在**引擎内部**的锚点（= 左上角）坐标 |
| `size` | 方块边长（格） |

**`appliedRot` 用来发现「我把 `rot` 写错了」**：引擎对越界的 `rot` 是**静默环绕**的，
全都返回成功。比对传入值与返回值即可看出：

```
rot=9   -> appliedRot=1      ← 写错了，被环绕
rot=-1  -> appliedRot=3
rot=4   -> appliedRot=0      ← 常见于把它当成 1-based
rot=3   -> appliedRot=3      ← 正常，两者一致
```

（2026-10-06 实测六组，与 `/buildings` 回读的实际 `rotation` 逐条一致。）

**注意：不可旋转的方块，`appliedRot` 恒为 `0`。** 引擎的 `Block.rotate` 默认 `false`，
`conveyor` / 炮塔 / 钻机这类是 `true`，而 `sorter` 这类是 `false` —— 后者在引擎里
**根本没有朝向**（`/buildings` 回读永远是 0）。所以对它传 `rot=2` 也不会得到 2，
这是如实反映，不是越界环绕。判据见 `ENGINE-NOTES` §三十三。

**`anchorX` / `anchorY` 用来解释 footprint 落点**：接口一律给**中心**坐标，
而引擎内部按**左上角**定位，两者差一个随尺寸变的偏移量。
与其让每个 AI 自己推这个偏移，不如把换回来的结果直接给出 ——
**所以算边界直接读 `anchorX`/`anchorY`，不要按「中心 ± size/2」推（那是错的）。**

### `/place` 的 `unit` 参数

默认由**当前接管的单位**执行（`/control?op=enter&unit=<id>` 之后就是它），没有则任选一个可建造单位。
传 `unit=<id>` 可显式指定。响应里的 `builder` 字段回显实际用了谁。

### `/control?op=warp` 默认被禁用

`warp` **直接改单位坐标**，是 P0 技术验证留下的调试探针。它也是唯一的瞬移后门：

```json
{"ok":false,"code":1005,"error":"direct position setting is disabled: unit movement must go through the engine (use /command?action=move). Server-side override: -Darena.allowwarp=true"}
```

**为什么禁**：对等约束里「移动速度 = 引擎行为」——人类玩家只能 WASD，
而 `warp` 让 AI 一步跨到任意坐标，走位、赶路、规避全都不再成立。

**要移动就用 `/command?action=move`**（或 `/control?op=order`），走引擎的
`CommandAI`，速度和人类同源。

### 限流

**每个 agent 一个令牌桶**，默认 `60/s`、突发 `200`（`ai-arena.json` 的 `rateLimit`）。
超限返回 `429` + `code 1429`，响应里写明当前配置：

```json
{"ok":false,"code":1429,"error":"rate limit exceeded: 60/s (burst 200)"}
```

限流在**鉴权之后**执行 —— 过不了鉴权的请求不该消耗配额。
实测连打 900 次：放行 591 次，与「桶 200 + 耗时 6.5s × 60/s ≈ 590」吻合。

> 这条以前是**死配置**：`perSecond`/`burst` 解析了，`1429` 也写在错误码表里，
> 但没有任何限流逻辑 —— 一个 agent 放开打就能占满 HTTP 线程池。
> 客户端轮询建议留出余量（比如 5–10 次/秒就够用了）。

### 多个建造单位

**引擎里每个单位有各自的建造队列**，而 `/place` 默认只把计划交给其中一个
（被接管的那个，否则第一个可建造的）。要驱动多个单位并行干活，自己分派：

1. `GET /units` 取所有 `canBuild=true` 的单位
2. 按距离或负载自行分配，逐个 `POST /place?unit=<id>&...`

**这和真人的操作一一对应** —— 玩家也是框选一部分单位、让它们建各自就近的房子，
而不是把所有单位都指向同一个工地。所以这里**没有**「自动均衡分派」的接口：
真人也做不到，那是特供。

**怎么让单位变多**：单位必须由工厂生产，`/spawn` 默认被禁用（见上文）：

```
建 ground-factory（或 air-factory / naval-factory）
  → 供电（发电机 + power-node 连线，相邻不会自动并网）
  → POST /config?x=<工厂x>&y=<工厂y>&value=<单位名>     选生产计划
  → 等它产出（轮询 /factory 的 currentPlan 与进度）
  → POST /command?action=move&units=<新单位id>&x=&y=     指挥它去工地
```

工厂只吃它的产线需要的材料，产线选错会一直停着 ——
`/factory` 会给出 `requirements` 和当前进度，不必猜。

**`config` 会跟着建造计划走**，方块一建好就是配好的，不用再发一次 `/config`。

```json
{"config":"item=coal","message":"queued sorter at (281,78) by gamma; pending plans=1"}
```

`config` 的值按**方块声明的配置类型**解析：物品名 → `Item`、单位名 → `UnitType`、
方块名 → `Block`、纯数字 → `Integer`。

> **传字符串不会自动生效，必须能被解析出来。** 引擎按值的 `getClass()` 查方块的
> `configurations` 表，匹配不上就**静默失效** —— 方块建出来了，但配置是空的。
> 所以响应里会回显解析结果（`item=coal` 这种）。**解析不出来时会额外给
> `configWarning`**，明确告诉你这个配置不会生效，而不是等建完了才发现。

### `/place` 的 `shape=path`：折线布线

真实布线必然拐弯，而拐弯处每格朝向不同 —— 其它形状「所有格同一 `rot`」的设计
正好卡在最需要的地方。`shape=path` 收折线点列，**每一格的朝向由服务端按走向算**：

```
POST /place?shape=path&path=273,78;278,78;278,82&block=conveyor
```

```json
{"shape":"path","tiles":10,
 "rotations":[[273,78,0],[274,78,0],...,[278,78,1],[278,79,1],...]}
```

`rotations` 是 `[x, y, rot]` 三元组，逐格给出算好的朝向。上面的路径：
横段一路朝东（`rot=0`），**到拐点 `(278,78)` 自己转成朝南（`rot=1`）**，竖段继续朝南。

两个保证：

- **四邻连续** —— 斜线不会产生对角相接的两格（那在物理上接不上，传送带只认四邻）。
  45° 斜线会自动补成正交阶梯，宁可多几格也不断链。
- **拐点即转向** —— 拐点属于两段共用的那一格，它的朝向指向下一段。

**`path` 这个参数名和客户端库的 `post(path, ...)` 首参重名**，用 `arena.py` 时
走封装好的 `place_path()`，别直接 `post("place", path=...)`。

### `/command` 的 8 种 action

**`units=` 是复数、逗号分隔**（`units=219,220`），不是 `unit=`。漏传或写错名字
会返回 `1001 required: units=<id>[,<id>...]`。

`move` / `attackUnit` / `assistBuilding` / `setCommand` / `setStance` 需要 `units=`；
`commandBuilding` 需要 `buildings=`（建筑 id 见 `/buildings` 的 `id` 字段）。

> **`move` 的行为说明**：引擎的 `Call.commandUnits` 是喂给 `CommandAI` 的，
> 而本竞技场里**每个单位都被影子 Player 持有**（`controller=Player#NNN`），
> 玩家持有的单位不理会 AI 指挥。所以 `move` 现在会额外走 `moveOrders`
> （每帧直接写速度与朝向，绕过控制器），**它是真的会动的**。
> `attackUnit` / `assistBuilding` 仍只走引擎 RPC —— 指挥会被记录，
> 但玩家持有的单位是否执行取决于引擎行为。要移动单位优先用 `move` 或
> `/control?op=order`。



| action | 参数 | 作用 |
|---|---|---|
| `move` | `units` `x` `y` [`queue`] | 移动到格坐标 |
| `attackUnit` | `units` `target` | 攻击指定单位 id |
| `assistBuilding` | `units` `x` `y` | 协助建造该格 |
| `setCommand` | `units` `cmd=` | 设置逻辑指令 |
| `setStance` | `units` `stance=` [`enable`] | 设置姿态 |
| `commandBuilding` | `buildings` `x` `y` | 指挥建筑（如给工厂设集结点） |
| `requestItem` | `x` `y` `item=` [`amount`] | 从该格取物品 |
| `transferInventory` | `x` `y` | 向该格交付库存 |

`units` / `buildings` 是 **id 数组**（逗号分隔），`x` `y` 是**格坐标**。

**队列卡死时值得试**：`/command?action=move&units=<id>&x=&y=` 或
`/control?op=order&unit=<id>&x=&y=` 能把卡住的建造单位送去工地，
实测 `plans` 一次从 56 降到 1，沿线方块真的建成 —— 比 `/break` 干净。

### `/spawn` 默认被禁用

服务端**默认拒绝**直接生成单位：

```json
{"ok":false,"code":1005,"error":"direct unit spawning is disabled: units must be produced by a factory. …"}
```

理由：直接 spawn 绕过整套产能 —— 没有建造时间、不需要电力、不需要工厂，
「谁先攒出产能」这个维度直接消失，对局退化成两个脚本对撞。

调试时用 `-Darena.allowspawn=true` 打开。正常对局**用工厂**：
建 `air-factory` / `ground-factory` / `naval-factory` → 供电 →
`/config?x=&y=&value=<单位名>` 选生产计划。

裁判（admin）可带 `team=<id>` **替别队**生成，用于组织比赛。


### admin 专属

| 接口 | 说明 |
|---|---|
| `POST /referee/setup?map=` | 加载地图、放核心、生成建造单位 |
| `POST /referee/host` | 打开游戏端口 6567 |
| `POST /referee/start` | 解除暂停 |
| `GET /referee/fog` | 读取当前迷雾设置（`fog` / `staticFog` / `pvp`） |
| `POST /referee/fog?fog=false` | 关掉迷雾（`fog=true&static=true` 打开并同步静态位图） |
| `POST /referee/observe` | 视角切换，同 `GET /observe` |
| `POST /referee/record?action=start&label=` | 开始录像（`action=stop` 结束） |
| `GET /referee/diag` | 同 `/diag` |
| `GET /referee/buildings?view=all` | 全图建筑 |
| `GET /referee/units?view=all` | 全图单位 |
| `POST /referee/admin?action=observe&player=<id>` | 把某玩家设为观战 |

裁判**不能替别队建造** —— 越权请求会返回该格对其队伍不可见。

---

## 五、WebSocket

`ws://127.0.0.1:7200/ws`

连接后发送订阅消息，之后服务端持续推送事件。
参考实现见仓库的 `ws-client.py`（含自动重连与重订阅）。

---

## 六、客户端库

`skill/scripts/arena.py`

```python
from arena import Arena, load_own_token

a = Arena("alpha", load_own_token("alpha"))  # 只取自己那一个 agent 的 token

a.ping()                                    # True/False
a.wait_online(timeout=120)                  # 轮询到在线为止
a.state()                                   # -> dict
a.buildings()                               # -> list
a.building_at(x, y)                         # -> dict | None
a.units()                                   # -> list
a.map(x, y, w, h)                           # -> list
a.rates(window=15)                          # -> dict
a.stalls()                                  # -> list
a.diag()                                    # -> dict

a.place(x, y, "conveyor", rot=0)            # 下请求
a.break_block(x, y)
a.control("pos", unit=<id>)

a.poll_until(lambda: a.building_at(x, y), timeout=90)   # 轮询到条件成立
a.place_and_confirm(x, y, "mechanical-drill")           # 下请求 + 轮询确认
```

内置退避重试（传输错误与 5xx 重试，4xx 立刻返回）。
`poll_until(pred, timeout)` 是库里唯一的等待原语：命中立刻返回，超时返回 `None`。

### 命令行自检

```powershell
python skill/scripts/arena.py --agent alpha --token <TOKEN>
```

打印 ping、state、建筑数、单位数、核心产率、警报条数。

---

## 七、启动与端口

```powershell
pwsh -File live-match.ps1              # 服务端 + AI + 观战端
pwsh -File live-match.ps1 -NoClient    # 只要服务端和对局
```

内部顺序：`setup` → `host` → `start` → AI 客户端 → 观战端。

| 端口 | 用途 |
|---|---|
| 7199 | HTTP 接口 |
| 7200 | WebSocket |
| 6567 | Mindustry 游戏协议（TCP + UDP） |

---

## SSE 事件推送

`GET /v1/{agent}/stream?since=<seq>&limit=<n>&seconds=<s>` → `text/event-stream`

DESIGN.md 三处承诺的东西。**与 `/events` 轮询共用同一套游标语义** ——
`since` / `nextSince` / `cursor_expired`（1006）完全一致，所以客户端从轮询
切过来不必改状态机。

为什么值得用：轮询要你自己定频率 —— 定高了烧限流配额（实测 700 次裸请求就
触发 1429，而且与写请求抢同一个令牌桶），定低了漏事件。SSE 让服务端按事件
发生推送。

事件类型：

| `event:` | 何时来 | `data:` |
|---|---|---|
| `hello` | 连上立刻 | `{"since":N,"agent":"beta"}` |
| `ev` | 每个新事件一条 | 与 `/events` 里 `events[]` 的元素**逐字节相同**（同一个 `toJson()`） |
| `cursor` | 每批之后 | `{"nextSince":N,"buffered":N}` |
| `error` | 游标过期 | `{"code":1006,"error":"cursor expired…resync with since=0"}` |
| `end` | 生存期到 | `{"reason":"lifetime reached","nextSince":N}` |
| `:hb` | 10 秒无事件 | ——（SSE 注释行，保活，不占序号） |

**约束**：

- `seconds` 有上限（600）且**到点主动收尾**——否则客户端不辞而别时线程会被永久占住
- 同时在流的连接数上限 **8**，超了回 `503 / 1007`。每个 SSE handler 占一个
  HTTP 线程，不设限等于给自己开了个拒绝服务的口子
- 游标过期时**不中断流**，只发一条 `error` 事件并把 `since` 重置为 0 继续

> **验证状态**：**已实机验证**（`drive/verify-all.py`，结账见
> [`TODO.md`](TODO.md) §八）—— `hello` / `ev` / `cursor` / `end` 四种事件
> 实测全部收到（468 字节），游标语义与 `/events` 一致。

---

## 蓝图导入 / 导出

```
GET  /v1/{agent}/blueprint?x=&y=&w=&h=          导出该矩形区域
POST /v1/{agent}/blueprint?x=&y=&data=<base64>  把蓝图放在 (x,y)
```

**为什么有用**：这张图**每局重新随机**（矿脉位置全变），所以布局本来没法跨局
复用。有了它，一局调好的产线可以存下来、下一局搬到新地形上。

### 格式

**我们自己的显式 JSON，不是 Mindustry 的 `.msch` 二进制。**

DESIGN.md 402–426 给的是 `readBase64` → 逐格 `BuildPlan` 那条路。没走它的原因：
`.msch` 是 base64 包着一段自定义二进制（format 字节 + version + tags + tiles），
在没有参考实现的情况下照猜写解析器，产出的是「看着像对、其实错位」的东西。
显式 JSON 可读、可手改、可离线校验，先要可靠再说兼容。

```json
{"v":1,"w":24,"h":12,"count":37,
 "blocks":[{"dx":0,"dy":0,"block":"conveyor","rot":0},
           {"dx":2,"dy":0,"block":"mechanical-drill","rot":0}]}
```

base64 编码后放进 `data=`。导出返回里带 `format: "ai-arena-blueprint-json/1"`。

### 导出

```json
{"x":265,"y":118,"w":24,"h":12,"count":37,
 "data":"eyJ2IjoxLCJ3IjoyNC...",
 "format":"ai-arena-blueprint-json/1",
 "message":"exported 37 block(s)"}
```

多格方块**只在锚点记一次**（否则导入时会重复放）。

### 导入

坐标按 `(dx,dy)` 相对 `x,y` 平移。响应：

```json
{"placed":35, "skipped":2, "total":37,
 "firstFailureTile":<编码后的格坐标>,
 "failureCodes":"(293,120)=1008 (294,120)=1008 ",
 "message":"blueprint: placed 35/37, skipped 2 (see failureCodes)"}
```

`skipped` **不是静默丢弃**：每条失败都带错误码与具体格，`failureCodes` 还做了
长度截断（最多 240 字符）免得响应被刷爆。全部失败时返回 `1005`。

> **验证状态**：**已实机验证**（`drive/verify-blueprint-roundtrip.py`，结账见
> [`TODO.md`](TODO.md) §八）—— 先在已知空地建 3 条带子 + 1 个 router，导出后
> 导到另一片空地，`placed 4/4`，并按位置与方块名**逐个核对**通过。
> 「多格方块只记锚点」这条随之落地。

---

## 接口版本号

`GET /ping` 的响应里带 `apiVersion`（无鉴权，最容易探测到的地方）：

```json
{"ok":true,"data":{"headless":true,"tick":12345,"agents":5,"apiVersion":"1.4"}}
```

端口发现文件（`bridge-<agent>.json`）里也带一份。

**跨版本的对局成绩不可比。** 成绩记录必须带上这个号 —— 这个接口改过不少次
（`stuckReason`、批量的 `requested`/`accepted`、`/queue` 的 `cleared`、
`/drill` 的 `itemsPerSecond`、SSE、蓝图……），而 `reviews/` 里几批数据是
不同时期跑的。没有版本号，「这局 AI 是 N/s、那局是 M/s」根本说不清
是不是同一个接口测出来的。

### 什么时候加号

| 变更 | 动作 | 例 |
|---|---|---|
| **破坏性**：删字段、改字段语义、改默认行为 | `major` +1 | 把 `tiles` 的含义从「请求数」改成「接受数」 |
| **增量**：只加字段、只加端点 | `minor` +1 | 加 `itemsPerSecond`、加 `/stream` |

「加了字段」也算变更、也要 +1 —— 老客户端虽然还能跑，但它记录的成绩
少了新字段的信息，与新版本的成绩仍然不是同一批可比数据。

---

## 建造是**单位**的属性，不是队伍的属性

`/place` 的响应里带 `"builder": {"id": 219, "type": "gamma"}` ——
**计划是分配给某一个单位的，不是分配给队伍的**。

这解释了几件事：

- **多几个建造单位不等于并行建造。** 建造进度挂在具体单位的 `BuilderComp` 上，
  一个单位一次只推进一个方块。想让 N 个单位同时建，得让计划**分派到不同单位**
  （`/place?unit=<id>` 可以指定）—— 而当前默认的分派策略会把它们都塞给同一个。
- **`builderTooFar` 是对「那个」单位算的。** 报错里的 `buildRange 220` 是像素，
  = **27.5 格**。距离是「被分派的那台」到工地的距离，不是「最近的一台」。
  所以把第二个单位派过去并不能解开这条 —— 要解就得让计划改派给近的那个。
- **建造单位的射程没有被放大。** 27.5 格是引擎常规值。

> 上面这几条合起来意味着：**优化建造吞吐的正确方向是「分派策略」，
> 而不是「造更多单位」**。造更多单位但不改分派，只是多几台闲着的机器。

## 增量查询：不要重拉全量建筑

**`/buildings` 没有 `since=` 参数，也不需要。** 要「我上次看过之后变了什么」，
用事件流：

```
GET /v1/{agent}/events?since=<上次的 nextSince>&limit=256
```

只看建筑相关的事件类型：

| `type` | 含义 |
|---|---|
| `blockPlace` | 有方块建成 |
| `blockBreak` | 有方块开始被拆 |
| `blockDestroy` | 有方块真的没了 |
| `buildingSpotted` / `buildingLost` | 视野进入 / 离开（**那不是建筑变了，是你看见了**） |

`nextSince` 拿回来存着，下次接着用。这就是增量 —— 不需要为它单开一个端点。

**为什么刻意不另开 `/buildings?since=`**：那会多出一个要维护的契约，
而且它和事件流回答的必须是同一件事。两份「谁变了」的表达迟早会漂移
（同一理由见「SSE 事件推送」那节：直接复用 `Ev.toJson()`，不另写序列化）。

**注意区分两类事件**：`blockPlace` 是**世界变了**，
`buildingSpotted` 是**你看得见了**（比如你推进视野、或对方在雾里建的东西
终于进视野）。只有前者能用来重建自己的建筑台账。

> 首次调用传 `since=0`；游标过期会回 `1006`，此时重置 `since=0` 重新同步。
