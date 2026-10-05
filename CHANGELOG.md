# 变更记录

面向**使用者**的接口改动摘要 —— 只收录会影响你怎么调接口的那些。
内部重构、脚本文档、验证过程不进这里（那些 `git log` 里能查到）。

格式按「主题」分组而非按 commit，因为一次改动常常跨多个提交。

> **接口版本约定**：目前没有语义化版本号。`docs/API.md` 是唯一权威，
> 改动以本文档记录为准。跨版本的对局成绩不可比 —— 见
> [TODO.md](docs/TODO.md) 里「接口版本号没有约定」一条。


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
