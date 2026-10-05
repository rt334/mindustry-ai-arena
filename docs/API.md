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

---

## 三、能获取的信息

### `GET /ping`

无鉴权。返回 `{"ok":true,"data":{"headless":true,"tick":N,"agents":N}}`。

### `GET /state`

| 字段 | 含义 |
|---|---|
| `playing` | 是否在对局中 |
| `tick` | 当前 tick |
| `world.w` / `world.h` | 地图尺寸（格） |

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
| `x` `y` | 锚点坐标 |
| `team` | 队伍 id |
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

### `GET /units`

返回 `data.units` 数组。

| 字段 | 含义 |
|---|---|
| `id` `type` `team` `x` `y` `health` `maxHealth` | 基本属性 |
| `rotation` `canBuild` | 朝向 / 能否建造 |
| `stack` | 携带的物品 |
| `shooting` `targetX` `targetY` `targetId` `targetType` `targetTeam` | 开火与交战目标 |
| `buildingAt` | **这个建造单位当前在建哪一格**，见下 |

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
| `kind` | `beltStall` / `drillBlocked` / `factoryBlocked` / `missingInput` |
| `x` `y` | 出问题的位置 |
| `item` | 相关物品（有则给出） |
| `cause` | **一句话说清该往上游查还是往下游查**，见下 |

#### `cause`：两种停机的区分

| 取值 | 含义 | 往哪查 |
|---|---|---|
| `starved` | 上游没把料送来（缺输入） | **上游** |
| `outputBlocked` | 自己有料且已满仓，出料侧不收 | **下游** |
| `outputRefused` | 出料侧不收，但自己还没满仓（刚堵上） | 下游 |
| `unknown` | 其它情况（电力、配方等），看 `missing` | 两者都不是 |

判据：**`efficiency == 0` 且满仓 ⇒ 输出路径不通；缺料 ⇒ 输入路径不通。**

> 这两者以前要靠 `outputAccepts` 和 `missing` 自己拼。典型误判是「核心满了 →
> 整条上游线回堵 → 上游钻机全部 `eff=0.0` 且满仓」，看着像产线坏了，
> 其实是**下游吃饱了**。

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
| `x` `y` | 目标格（锚点） |
| `block` | 目标方块 |
| `breaking` | `true` = 这是拆除计划 |
| `constructing` / `progress` | **只在该格已在施工时出现**：0 = 刚开工，长时间不涨就是卡住了 |

早期只给一个 `plans` 计数，AI 拿不到坐标 —— 想加速建造就得自己维护一份 pending
清单，而丢单会让清单和服务端实际状态对不上。有了 `planList` 才能精确定位卡住的计划。

`POST /queue?clear=true` 清空全队待办计划，返回清掉了几条。

### `GET /diag`

服务端诊断计数器，含快照路由统计
`teamBatchSends` `fullViewSends` `spectatorRouted`。

**仅 admin。** 非 admin 调用返回 HTTP `403`，body 为 `code 1403`。

### `GET /content`

方块 / 物品 / 单位表。**运行时取用，不要凭记忆。**

### `GET /database`

汇总数据库。

### `GET /events`

事件流。

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
| `POST /control` | `op=` … | 单位操控。`op` 取值：`pos` `order` `warp` `enter` `release` `fire` `stopmove` `orders` |
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

### `/place` 的 `config`：随建造一起设

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
