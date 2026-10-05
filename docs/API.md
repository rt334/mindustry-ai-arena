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

```python
from arena import Arena, load_tokens
toks, admin = load_tokens()
a = Arena("alpha", toks["alpha"])
a.wait_online(timeout=120)      # 轮询到服务端可响应
print(a.state())                # 已经在局里了，不需要额外的加入步骤
```

**AI 与真人玩家的差别只在「怎么发指令」**（HTTP vs 键盘鼠标），
不在「能看到什么、能做什么」。这是本项目的公平竞技约束。

裁判（`admin=true`）额外多一项能力：带 `view=all` 看全图。

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
| `1500` | 500 | 服务端异常 |

**`1008` 与 `1009` 是分开的，别混**：前者挪一格或先 `/break` 就能成，
后者重试多少次都没用。响应里带 `conflictAt` 指向具体是哪一格挡着。

`<agent>` 是配置里分配的 agent 名（如 `alpha`、`referee`）。token 在
`server-run/config/ai-arena.json`：

```json
{"agents":[{"id":"alpha","token":"...","team":100,"admin":false},
           {"id":"referee","token":"...","admin":true}]}
```

`admin=true` 的 agent 可以带 `view=all` 参数看全图；非 admin 只能看自己队伍视野。

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
| 某条链的**吞吐上限**（如「1.2/s」） | 游戏从不显示速率数字。玩家要数物品、掐时间、自己除 |
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
| `liquids` | 液体库存 |
| `powered` | 是否有电（有电力接口的方块才有） |
| `acceptsFrom` | **能从哪几个邻格收货**（传送带专用），`[[x,y],...]` |
| `sendsTo` | **把货推到哪几格**，`[[x,y],...]` |
| `fogRadius` | 该建筑的视野半径；**仅在该值 > 0 时出现**（核心是 61） |

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

### `GET /stalls`

产线异常警报，返回 `data.stalls` 数组：

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

#### 覆盖范围：只报「看一眼就知道」的

判据和**人类肉眼能看到的**对齐：

| 报 | 为什么 |
|---|---|
| `beltStall` | 带子**完全不动** —— 堵死了，一眼可见 |
| `drillBlocked` | 矿机**不出货**（钻头满仓转不动） |
| `powerUnconnected` / `powerStarved` | 电力条空 / 连线断，屏幕上直接显示 |
| `missingInput` | 方块停着；配方要什么、库里有不有，选中就能看 |

**不报**「这条链在减速」「吞吐上限只有 1.2/s」这类 —— 那是**观察 + 推导**得出的，
游戏界面从不显示，得自己盯一段时间算出来。接口直接给就等于送答案。

同理 `beltStall` 的阈值是引擎的 `clogHeat` 逼近 1（约堵了一秒），
对应的是「肉眼确认它卡住了」，而不是「它比刚才慢了」。

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
`teamBatchSends` `fullViewSends` `spectatorRouted`。

**仅 admin。** 非 admin 调用返回 HTTP `403`，body 为 `code 1403`。

### `GET /content`

方块 / 物品 / 单位表。**运行时取用，不要凭记忆。**

### `GET /database`

汇总数据库。

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
| `POST /break` | `x` `y` | 拆除 |
| `POST /config` | `x` `y` … | 设置方块配置 |
| `POST /command` | `action=` `units=` … | 指挥单位（8 种 action，见下） |
| `POST /control` | `op=` … | 单位操控。`op` 取值：`pos` `order` `enter` `release` `fire` `stopmove` `orders`；**`warp` 默认禁用**（见下） |
| `POST /spawn` | `type` `x` `y` [`team`] | **默认禁用**，见下 |
| `POST /mine` | `x` `y` [`unit`] | 让单位挖指定格 |
| `POST /record` | `action=start\|stop` | 录像开关 |
| `POST /chat` | `text` | 发言 |
| `POST /admin` | `action=` … | 管理操作（仅 admin） |

`rot` 取值 0~3（`0=东 1=南 2=西 3=北`）。各 `block` 的参数（尺寸、配方）由 `/content` 在运行时提供。

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
from arena import Arena, load_tokens

toks, admin = load_tokens()                 # 读 ai-arena.json
a = Arena("alpha", toks["alpha"])

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

> **验证状态**：实现已编译进 mod，但**尚未在实机上跑过**。
> 按当前轮次的要求没有启动游戏，所以表格里的行为是按代码写的，
> 不是实测的。第一次实机验证前请把它当「待验」看。
