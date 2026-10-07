# 变更记录

面向**使用者**的接口改动摘要 —— 只收录会影响你怎么调接口的那些。
内部重构、脚本文档、验证过程不进这里（那些 `git log` 里能查到）。

格式按「主题」分组而非按 commit，因为一次改动常常跨多个提交。

> **接口版本约定**：目前没有语义化版本号。`docs/API.md` 是唯一权威，
> 改动以本文档记录为准。跨版本的对局成绩不可比 —— 见
> [TODO.md](docs/TODO.md) 里「接口版本号没有约定」一条。


## 自检修正：`/stalls` 的 `stalledCount` 和 `stalls` 可能来自相邻两拍（2026-10-06）

响应形状**没有变化**，变的是它保证的东西：以前这两个字段各自读一次内部快照，
两次读之间主线程完成一次扫描，就会返回「计数来自上一拍、数组来自这一拍」——
例如 `stalledCount: 5` 而 `stalls` 里躺着 6 条。**接口自己和自己矛盾**，
而调用方多半会信那个计数（它更省事）。

裁判视角（`?view=all`）的窗口比队伍视角宽约三个数量级：计数的赋值和 JSON 的拼接
之间隔着一整个字符串构造循环，是微秒级；两个孩子字段之间只是相邻两行。

现在两个字段走同一次读取，必然同源。`/watch`、`/await?until=noStall`
不受影响 —— 它们本来就在主线程求值。

顺带修掉一处换图残留：`StallWatch` 的报警表按 `"x,y"` 索引，换图时没清，
新图上同一格坐标会沿用上一张图的计时（第一拍就报「已堵 300 秒」）。


## 自检修正：`transport` 的 `note` 写错过传送带的收货规则（2026-10-06）

一次文档自检发现：**`/block` 的 `transport` 条目把我自己的误判当规则写给了 AI。**

```
错的（已删）
conveyor          → "沿朝向逐格推进；只从背面收料，侧向不接"
armored-conveyor  → "同传送带，但不接受侧向输入"
conduit           → "沿朝向输送液体；只从背面收，侧向不接"
```

**源码不是这样。** `Conveyor.acceptItem`：

```java
if(len >= capacity) return false;
int direction = Math.abs(facing.relativeTo(tile.x, tile.y) - rotation);
return (((direction == 0) && minitem >= itemSpace)   // 背面来货：>= 0.4
     || ((direction % 2 == 1) && minitem > 0.7f));     // 侧向：**也收**，门槛更严
```

**侧向是收的**，只是门槛更高 —— 所以「拐弯处容易堵」的机理是门槛，不是拒收。
`ArmoredConveyor` 也不是「不收侧向」，而是**侧向只放行其他传送带送来的**。

修正后：

| `how` | 修正后 |
|---|---|
| `conveyor` | 沿朝向逐格推进；背面来货门槛松，侧向也收、但要求带子更空 —— 所以拐弯处特别容易堵 |
| `armored-conveyor` | 同传送带，但侧向输入只接受其他传送带送来的货；建筑从侧面直接送不进来 |
| `conduit` | 沿朝向输送液体（液体管道不按物品过滤） |

`conduit` 那条**去掉了方位断言** —— 它的方位算法与传送带不同（`absoluteRelativeTo`），
而我**没有逐方位实测过液体**，所以只留确凿的部分。

> **这个错误本来可以避免**：[`docs/reviews/REVIEW-ADDENDUM.md`](docs/reviews/REVIEW-ADDENDUM.md) §6.1
> 早就更正过同一句话（「原文的『只从背面』是误归因」），而我没读到就重犯了一遍。
> [`docs/TODO.md`](docs/TODO.md) §五 第 23 条也立了规矩：**方向语义必须单侧隔离实测**。
> 详见 [`docs/ENGINE-NOTES.md`](docs/ENGINE-NOTES.md) §三十六 坑 1。

## 自检修正：多处文档「本图无水 ⇒ speed = 1」是错的（2026-10-06）

同一次自检还发现一个**跨多份文档的系统性错误**：把「图上没有天然液体地块」
当成了「水不可得」。

**水可以被生产**：`water-extractor` 在**干地上**就能产水
（`SolidPump.baseEfficiency = 1f`，`canPump(tile) = !tile.floor().isLiquid`），实测 `6.6/s`。
而钻机的水加成只认**自己建筑内的液体库存**：

```java
// ConsumeLiquid.efficiency(Building)
return Math.min(build.liquids.get(liquid) / (amount * ed * multiplier.get(build)), 1f);
```

**它不检查环境。** 所以只要有管道把水送进钻机，
`speed = Mathf.lerp(1f, liquidBoostIntensity, 1f) = 1.6` —— **那 1.6 倍是拿得到的。**

**影响**：所有按裸速算的矿机产率表**偏低 1.6 倍**；
`FEASIBILITY.md` §三 把 `multi-press` 标成「✗ 需水」也不成立（水能造）。

**已修正**：`FEASIBILITY.md`（§二加更正块、§三区分两类 ✗）、`TODO.md` 第 14 条、
`reviews/REVIEW-ADDENDUM.md`（加注记，原表不动 —— 那是评审记录）、
`reviews/FEATURE-REQUESTS.md`（A1 标记已实现一半 + 更正措辞）、
`reviews/DEBUG-LOG.md`（2.1 加更正）。

**尚未实测**：按 §五 第 23 条的纪律，水加成这条是**源码推导 + 机制自洽**，
仍需一局对照（「钻机 + 水线」vs「同位置裸钻机」的 `efficiency` 之比应为 1.6）。
**绝对数字暂不改，先补对照。**

> 讽刺的是，这正是 AI 在对局里暴露的同一个思维缺陷
> （「只知道要水，但地图上没有，就不再考虑从其他渠道获取」）——
> **「图上没有」不等于「拿不到」，因为资源可以被生产。**

## `/block` 新增 `area`：范围类参数（2026-10-06）

「它能作用到多远」以前**只在源码里**。`description` 用的是相对说法 ——
`power-node-large` 是「连接范围**更大**的高级电力节点」、`surge-tower` 是
「用于**远距离**连接，但连接数**较少**」—— 而布局需要的恰恰是绝对值。
实测一个 agent 想扩电力网时，`/block?name=power-node` 给不出连接距离，它只能靠试错。

```json
"area": {"connectRange": 6.0, "maxConnections": 10, "unit": "blocks"}
```

| 方块 | `area` |
|---|---|
| `power-node` | 6 格 / 10 个连接 |
| `power-node-large` | 15 / 15 |
| `surge-tower` | 40 / 2 |
| `mender` | 5 格 |
| `mend-projector` | 10.63 格 |
| `overdrive-projector` / `overdrive-dome` | 10 / 25 格 |

没有范围概念的方块（`conveyor` / `battery` / `silicon-smelter` …）给 `{}`。

**单位逐个对齐引擎 tooltip，因为两类不一样**：`PowerNode` 用
`Stat.powerRange, laserRange, StatUnit.blocks`（**本来就是格**），
projector 用 `Stat.range, range / tilesize, StatUnit.blocks`（**像素，要除以 8**）。
当同一种单位读，`mender` 的 5 格会变成 40 格。

尚未覆盖：`force-projector` / `radar`（它们的半径不在已判断的几类里）。

## `/block` 补齐「转运件」语义；`/diag` 暴露加入策略（2026-10-06）

### 转运件以前在 `/block` 里什么都不做

`kind` 是 `transport` 的这批方块（传送带 / 交叉件 / 分流转运 / 溢流门 / 桥 / 卸载器），
`inputs` 与 `outputs` **都是空数组** —— 而「怎么送」是它们唯一的语义。

补上之后 `outputs` 里多一条：

```json
{"kind":"transport","how":"overflow-gate",
 "note":"两个候选出口，按对方当前 acceptItem 实时判断：优先一侧，它不收就溢到另一侧"}
```

覆盖 **39 个**方块（含 `junction` 的「交叉不打结」、`router` 的「轮流发」、
`sorter` 的「按配置物品过滤」、`unloader` 的「核心是终点，得有它才能取货」）。
`how` 用引擎的 `invert` 字段区分成对的那两个（`sorter`/`inverted-sorter`、
`overflow-gate`/`underflow-gate`），否则它们在接口里长得一模一样而方向正好相反。

**说话的方式仍是「规则」**：引擎怎么转发、优先级由哪个字段决定 ——
不说「该怎么排」，那是布局设计。

> **一条自我更正**：写这段时我说「这批方块的语义 API 完全没给」。**那是错的。**
> `description` 一直写着规则，`/database?q=` 也连中文描述一起搜 ——
> `underflow-gate` 的描述就是「与溢流门相反，当两侧均堵塞时才向前运输」，
> 而 `water-extractor` 的「适用于附近没有地表水的情况」把「水能虚空获取」也说清了。
> 真正的情况是**规则以散文存在、结构以字段存在**，而 AI 只读字段。
> 所以这个改动的定位是「**把散文翻成机读**」，不是「补上缺失」。

### `/diag` 新增 `joinPolicy`

```json
"joinPolicy": {"autoSpectate": true, "defaultView": -1, "realPlayers": ["jy","alice"]}
```

回答「谁连进来会是玩家、谁会被当成观众」。以前只能读启动参数或猜——
实测有人在服务器已经是观战模式的情况下反复重连客户端，以为是客户端的问题。

### 顺带修掉一个「接口坏了一半」的缺陷

`postToGame` 的每 tick 写预算在**菜单状态**下永不重置：`Vars.state.tick` 恒为 0，
`nowTick != budgetTick` 永远为假，于是预算用尽一次之后，**所有走主线程的端点**
永久返回 `1007`（HTTP 504），而不走主线程的 `/ping`、`/state` 依然正常。

实测：服务器起好但尚未开局时，连打 40 次 `/diag` 会开始回 504，
报的还是「game thread did not respond」这种误导性的说法。修法是没在游戏中就
不做预算限制 —— 预算的目的是「别让写操作拖慢游戏 tick」，没有游戏在跑时它没有对象。
修后同样 40 次全部 200。

## `/stalls` 现在按视角裁剪；人机对局有了 `-Darena.players` 白名单（2026-10-06）

两处改动都由 2026-10-06 的人机对局暴露：前者的默认值在错的一侧，后者是缺一个人机对局的入口。

### `GET /stalls` 只返回你看得见的那部分

新增 `?view=own|<teamId>|all`（默认 `own`）。返回范围改成
**自己队伍 + 当前视野内**，判据与 `/buildings` 逐字一致。

改之前它返回全图所有队伍的表。那一局实测：AI 一次拿到 40 条，
**39 条是对手的**，而它自己唯一的故障（石墨压缺煤，已饿 900 秒）淹没在里面。
它读了 25 次告警，没有一次朝自己那条 15 格的煤线去 —— 缺的那截煤线是整局科技树
唯一断点。详见 [CONDITIONS.md 明细 7](docs/CONDITIONS.md)。

`data.stalledCount` 同步改成同口径；此前它是 `stalledSince.size()`，
一个全局计数被当成「我的堵塞数」返回。

裁判 / 观察者传 `view=all` 拿全图，规则与 `/buildings` 相同。

### 新增 `-Darena.players=<名字,逗号分隔>`

列在里面的玩家**不被** `autospectate` 接管，按正常玩家进场。给真人想同场对局时用：

```
java -Darena.players=rt -jar server-release.jar
```

**为什么不直接把 `autospectate` 默认翻成 `false`**：试过，翻回来过。
`observer/` 那个观战端 mod **不在客户端报名** —— 它靠服务端把连接标成 spectator
才切到全图视角（`ObserverMod` 里只有「检测到自己被标为 spectator」这一条路）。
默认关掉它，观战端连上就不是观察者了。用一个坏默认换另一个坏默认，不划算。

所以 `autospectate` 保持默认 `true`，「谁该当玩家」交给白名单回答。

## 权限分级与桥接端点（2026-10-06）

### agent 有了 `role`，不再只有 admin 一个布尔

配置里 `"admin": true/false` 换成 `role` 字符串，三档：

| `role` | 能做什么 |
|---|---|
| `player` | 参赛 AI：读写自己队伍的；`view` 只能是 own |
| `observer` | **只读观战**：能 `view=all` 看全图，但任何改状态的端点都返回 403 |
| `referee` | 裁判：全部，含 `setup` / `host` / `fog` / `spawn` 带 `team=` |

**向后兼容**：旧配置的 `"admin": true` 等价于 `referee`、`false` 等价于 `player`——不改配置也能跑。

**`observer` 不上场**：setup 不会给它分配核心或单位。这不是优化，是必须的——
`DESIGN` 里早写过原因：观战者所属队伍一旦有核心，`bestCore()` 非空，
引擎 1 秒后就塞给它一个单位，它就不再是纯观察者了。**实测确认过这个陷阱真实存在**
（未修时会看到 `core[watch1]@108,21` 加一个 derelict 单位）。

### 新增无鉴权端点 `GET /v1/bridge/<agentId>`

给**不一定是 DSH agent**的参赛客户端用的语言无关接入方式：一次请求拿到

```json
{"agent":"beta","apiVersion":"1.4","httpPort":7199,
 "httpBase":"http://127.0.0.1:7199/v1/beta","role":"player","token":"<48 hex>"}
```

不必知道配置文件在哪，也不必用某个 SDK。本地文件 `bridge-<agent>.json` 是**同一份内容**
（单一来源，`AIArena.bridgeJson`）。

**裁判的条目不含 `token`**，只给一句 `tokenHint` —— 它的凭据只从 `ARENA_ADMIN_TOKEN` 读（fail-closed）。
端点数 36 → **37**。

## 新端点（2026-10-06）

- **`GET /v1/<agent>/watch?since=<事件序号>`** —— 「值得注意」的**聚合判定**。
  把停机（`/stalls`）、队列停滞（`/queue`）、新事件（`/events`）合成**一个判断**，
  返回 `clear` 布尔：`clear=true` 表示**现在没事，可以睡到下一次事件**。

  它是为「有事才醒」这个用法加的 —— 实时游戏里 AI 跟不上 tick，
  但**光知道「有事发生」不够**：还需要一个明确的「现在没事」信号，否则不敢睡、只能一直轮询。

  ```json
  {"clear":false,"reasons":["stalls"],
   "counts":{"stalls":1,"plans":0,"stuckPlans":0,"worstStuckSeconds":0.0,"newEvents":0},
   "sinceSeq":0,"nextSince":4,"hint":"有事要看：停机 → /stalls；…"}
  ```

  **只聚合、不新增信息** —— 每一项都能用既有端点单独查到，它不解释「为什么堵」「该改哪一格」。
  端点数 35 → **36**。

- **`GET /v1/<agent>/await?until=<谓词>&timeout=`** —— **谓词等待原语**：
  让服务端替你等一个状态出现，而不是客户端轮询。

  理由很实际：**轮询的每一次都是一趟模型往返**，等一次建造可能烧掉几十轮。
  让服务端在主线程按 tick 判，把「轮询 30 次」压成「一次调用」。

  支持的谓词：`built:<x>,<y>` / `rate:<物品>:<n>`（≥ n，10 秒窗口）/ `queueEmpty` / `noStall`。
  **超时不是错误**（HTTP 仍 200，用 `satisfied` 区分）；`timeout` 默认 90 秒、范围 0.5–600。

  **语法用冒号不用 `>=`**：`>` 在 URL 里非法，会在到达服务端前就被 HTTP 层拒掉。
  四个谓词的观察对象**一律是调用方自己的队**，没有跨队变体（否则等于用服务端算力换情报）。

  端点数 36 → **38**（含无鉴权的 `/v1/bridge/<agentId>`）。

  **并发上限是 `httpThreads / 4`**（默认 **4 个**），超了回 `503 / 1007`。
  为什么这么小：每个挂起的等待占一个 HTTP 线程，上限若按线程池大小设，
  若干个等待就能把整个接口层堵住。上线时正是这么设的（16），实测 20 个并发
  耗时是 `timeout` 的两倍 —— 限流从未触发，改成 1/4 后复测 16 个立刻 `1007`、
  4 个挂起，期间 `/ping` 33ms 正常。

## 接口修正（2026-10-06）

- **`/place` 的 `appliedRot` 现在真的反映实际生效值。** 它此前**原样回显传入的 `rot`** ——
  传 `9`（越界）返回 `9`，而 `/buildings` 回读的实际 `rotation` 是 `1`。
  于是「拿 `appliedRot` 与自己传的 `rot` 比对来发现越界」这个用途**根本失效**（两者永远相同）。
  已在 `Actor.place` 里归一化（`((rot % 4) + 4) % 4`），实测六组
  `3→3`、`9→1`、`-1→3`、`4→0`、`100→0`、`0→0`，与 `/buildings` 回读**逐条一致**。
  **若客户端曾依赖「`appliedRot == 传入的 rot`」，现在会看到差异 —— 那正是它该反映的东西。**
- **补充（同日）**：对 `Block.rotate = false` 的方块（如 `sorter`、`router` 这类），
  `appliedRot` 一律给 **`0`** —— 这类方块在引擎里**根本没有朝向**（`/buildings` 回读永远是 0），
  回显传入值等于承诺一个不存在的朝向。判据与实测见 `ENGINE-NOTES.md` §三十三。
- **`/block?name=` 的 `requirements` 是好的。** 早先笔记记的「序列化坏了、每项都是 `x`」不成立：
  实测 `/block?name=sorter` 返回 `{"copper":2,"lead":2}`，物品名与数量都对。**查配方可以用它了。**
- **`API.md` 补上 `/place` 的 `appliedRot` / `anchorX` / `anchorY` / `size`** ——
  这四个字段存在已久，却从未写进接口手册。

## 安全与凭据（2026-10-06）

**这一批改变了现有部署的行为**：配置文件里的 admin token 会立即失效，见文末「影响」。

- **admin 凭据不再从配置文件读（fail-closed）**：`config/ai-arena.json` 里 admin 条目的 token
  一律被忽略；服务器只认环境变量 `ARENA_ADMIN_TOKEN`（≥16 字符）。读不到就**不注册该 admin agent**，
  裁判端点全部不可用 —— 宁可没有裁判功能，也不把裁判权限留在参赛 AI 可读的文件里。
  首次生成的默认配置里，`referee` 的 token 字段留空。
- **审计日志开始记特权读**：带 `view=` 的请求会留痕并标 `"privileged":true`。
  此前读接口完全不记，于是「谁用了全图视野」事后无法回答 —— 越界不可检测。
  普通读（不带 `view=`）仍然不记，日志不会被 `/map` 刷爆。
- **审计补记三个漏掉的动作**：`host`（打开游戏端口）、`start`（解除暂停）、`fog`（改迷雾规则）——
  这三个确实会改变游戏状态，此前不在记录范围内。
- **启动与裁判脚本改用新来源**：`start-arena.ps1` 生成并复用 `server-run/admin-token.txt`
  并把它设进环境变量；`live-match.ps1` / `diagnose.ps1` / `stress-test.ps1` 从环境变量读，
  读不到再兜底该文件，都没有就明确报错。
- **客户端库分入口**：新增 `load_admin_token()`（裁判用）与 `load_own_token(agent_id)`（参赛用）；
  `load_tokens()` 保持签名不变，但其返回的 admin token 已失效（docstring 已注明）。

**影响**：旧部署若一直从配置文件取 admin token，这些脚本会报「没有裁判凭据」。
处置：跑一次 `start-arena.ps1`（它会生成 `server-run/admin-token.txt`），
或自行设 `ARENA_ADMIN_TOKEN` 后重启服务器。

<!-- 凭据边界这件事的完整记录（发现经过、为什么算越界、仍不适用的场景）见 docs/CONDITIONS.md 事故记录第 6 条。 -->

## 接口正确性（2026-10-05 · 第二批）

又一轮实测（`drive/verify-commands.py`、`compare-move-order.py`）：

- **`/command?action=move` 回成功但单位纹丝不动。** 同一单位、同一目标：
  `move` 位移 **0.00 格**，`/control?op=order` 位移 **23.14 格**。原因是
  `command()` 走 `Call.commandUnits`（喂给 `CommandAI` 的引擎 RPC），而本竞技场
  每个单位都被影子 Player 持有，玩家持有的单位不理会 AI 指挥。
  已改为位置类指令额外挂 `moveOrders`（每帧直接写速度，绕过控制器）——
  复测位移 **22.99 格**。
- **新增建筑 `id` 字段。** `/command?action=commandBuilding` 要求传 `buildings=`
  建筑 id，但 `/buildings` 以前根本不暴露 id —— **这个 action 对任何客户端都是死路**。
- **`/command` 漏传 `units=` 时不再报误导性错误。** 以前回
  `1002 no valid units for crux`，读起来像「你给的 id 不属于这队」，
  真实原因往往是参数名写成了单数 `unit=`。现在报
  `1001 required: units=<id>[,<id>...]`。

顺带验证：
- **`cursor_expired` 契约**（此前从未跑通）：`since=1` → `410 + code 1006`，
  消息指明 `resync with since=0`，而 `since=0` 永远可用。
  为此把 `EventLog.CAPACITY` 做成可用 `-Darena.eventlog.capacity=N` 覆盖 ——
  攒满 4096 条事件要十几分钟正常游玩，与契约本身无关。
- **8 种 `/command` action 全部可达**，参数校验齐全（未知 cmd/stance、
  缺 units、缺 buildings 都给出结构化错误），无 5xx、无空 body。

## 接口正确性（2026-10-05 · 第一批）

四个缺陷由一轮实测查出（`drive/verify-debt-1.py` / `verify-debt-2.py` 可复现）：

- **修：成功响应被回成 HTTP 400。** `/place` 在材料不足时，成功排上计划却返回
  `400` 配 body `{"ok":true,...}`。原因是判定「这是不是错误响应」用了全文子串
  匹配 `contains("\"ok\":false")`，而成功响应里 `materials.requirements`
  每项都带 `{"ok":false,"short":N}`。客户端按状态码分流就会把成功当失败。
  改成只看开头（错误响应必然以 `{"ok":false` 开头）。**这一条最要命**：
  它只在材料不足时触发，正是 AI 最需要看清 `materials` 的时刻。
- **`/place`、`/break` 的批量响应新增 `requested` / `accepted` / `skipped` /
  `limitReached`。** 以前接受数只藏在 `message` 的散文里，而 `tiles` 是
  **请求数** —— 请求 70 格、上限 60 时返回 `ok:true` 且 `tiles:70`，
  实际只排上 60。
- **`/queue?clear` 新增 `cleared` 字段。** 以前条数只在 `message` 文本里。
- **客户端库把持续 429 如实报成 `1429`。** 以前退避重试耗尽后统一抛
  `-1 unreachable`，调用方会去查网络，而真正该做的是降频。

## 回放（2026-10-05）

- **录像格式补齐四样**（`c51ecb5`）：`meta` 加 `mapData`（整张地图，三段 RLE）、
  `snap.builds` 加 `rot`、`snap` 新增 `removed`（本帧消失的方块）、`version` 升到 2。
  改动前录像画不出来 —— 没有地图、没有朝向、拆掉的方块不记录。
- **新增回放播放器**（`0674bb2`）：`replay/index.html`，单文件零依赖，
  浏览器打开后拖入 `.jsonl` 即播。

## 接口安全与对等（2026-10-05）

- **`/control?op=warp` 默认禁用**（`8cbc024`）：它直接改单位坐标，是唯一的瞬移后门。
  禁用后返回 `403` + `code 1005`。服务器侧可用 `-Darena.allowwarp=true` 打开。
  **要移动单位请用 `/command?action=move` 或 `/control?op=order`。**
- **限流真的生效了**（`8cbc024`）：以前 `rateLimit` 配置解析了但没有任何逻辑。
  现在每 agent 一个令牌桶（默认 60/s、突发 200），超限返回 `429` + `code 1429`。
- **敌方建筑不再暴露库存**（`459550e`）：非己方建筑的 `items`/`liquids` 一律清空。
  以前可见的敌方核心会连库存一起给，绕过了 `Intel` 的确认机制。
- **`setup` 不再泄漏规则改动**（`459550e`）：`enemyCoreBuildRadius` 等三项
  以前改了不还原。当前地图看不出差异（原值即目标值），换图才会显形。

## 建造体验（2026-10-05）

- **`/place` 返回材料预检**（`d2a2132`）：每次下单都回 `materials`，
  逐项给「要多少 / 有多少 / 缺多少」。`adequate=false` 说明这计划会一直卡着。
- **`/place` 返回施工时长**（`d2a2132`）：`buildTime.seconds`，
  按引擎公式 `buildCost / builderSpeed` 算，不含走路时间。
- **`/place` 支持 `shape=path`**（`d5ea328`）：折线布线，朝向由服务端算。
- **`/place` 的 `mode: transfer`**（`d5ea328`）：对同格重复下单即转移建造目标，
  返回 `previousBlock` 与 `inheritedProgress` —— 对应游戏里双击方块改目标。
- **`/queue` 报「为什么卡」**（`76760b1`）：新增 `stuckReason`，四种取值 ——
  `missingMaterials` / `tileOccupied` / `builderTooFar` / `unknown`。
  `hint` 改为按原因分情况给；以前一律建议移动命令，在被墙挡住时是误导。
- **`/queue` 给进度与预计**（`d5ea328`）：`progressRate` / `etaSeconds`（实测外推）、
  `stuckSeconds`（进度不动且单位也不动超过 3 秒）。

## 物流与停机诊断（2026-10-05）

- **建筑暴露接货口与输出格**（`d5ea328`）：`acceptsFrom` / `sendsTo`。
  不用再试探「这条带子接哪个方向」。
- **`/stalls` 新增电力类别**（`145043b`）：`powerUnconnected` / `powerStarved`，
  对应「电力断开」与「电力不足」两种肉眼可见的现象。
- **`/state` 新增 `limits` 与 `vision`**（`d5ea328`）：不用试探就知道批量上限、
  地图窗口上限、自己的视野半径。

## 接口文档（2026-10-05）

- **新增「信息可见性契约」**（`e944c5e`）：逐字段标注「对应人类能直接看到的什么」，
  并写死缺省语义 —— 字段不出现表示**不适用**，不是「没查到」。
- **新增「并发与执行顺序」**（`e944c5e`）：请求经 `Core.app.post` 进主线程队列
  按入队顺序执行。串行发顺序确定，并发发谁先谁后都可能。
- **新增 [docs/CONDITIONS.md](docs/CONDITIONS.md)**（`e944c5e`）：能力边界、
  对等约束定义、发现过的越界路径与处理。
- **新增 [docs/TODO.md](docs/TODO.md)**（`8aefbd5`）：未完成事项盘点。

## 多格方块坐标（2026-10-05）

- **修正坐标语义**（`0222d49`）：`/buildings`、`/place`、`/map` 的坐标是
  **中心**（多格方块），不是左上角。引擎内部（`Edges`、`getLinkedTiles`）才用左上角，
  换算是 `block.sizeOffset`。
  同时修掉 `drillOutputs` 的 footprint 计算 —— 它以前对 3x3 及以上会偏一格，
  导致 `laser-drill` 的 `sendsTo` 指向错误的邻居。

- **`/block` 补 `drillSpeed` 与 `inputs[].optional`（顶层 `powerUse` 见上一条）。**
  `drillSpeed` 是满矿理论速率（items/s，取法与引擎 tooltip 的 `Stat.drillSpeed` 同源）——
  在此之前四台钻机的顶层字段完全一样、**无法横向比快慢**，只能各建一台去读 `/drill`。
  `optional: true` 标出「有它更快、没它也能干」的输入：四台钻机全都列着 `water`
  且看着像必需，而实测不接水也 `eff=1.0`。

- **`POST /v1/<agent>/batch?ops=`** —— **一批操作**：一次请求做多个 `place`/`break`/`config`。
  格式 `p,x,y,block[,rot]` / `b,x,y` / `c,x,y,config`，用 `;` 分隔。

  理由：一次模型往返秒级到几十秒，而一局只有 15~30 分钟 —— 每个往返只下一个命令，
  **操作数会被往返延迟硬性卡死**。实测一次 batch 放 20 条带子 **24 ms**，
  逐个发 20 次 place **327 ms**：差的不只是 14 倍时间，是 **1 个回合和 20 个回合**。

  逐条独立（一条失败不影响其余，整批仍 200），`failed[]` 带下标+坐标+错误码；
  格式错或超 `batchMax`(200) 则整批拒绝，不执行一半。端点数 36 → **37**。
