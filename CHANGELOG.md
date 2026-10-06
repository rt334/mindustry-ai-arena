# 变更记录

面向**使用者**的接口改动摘要 —— 只收录会影响你怎么调接口的那些。
内部重构、脚本文档、验证过程不进这里（那些 `git log` 里能查到）。

格式按「主题」分组而非按 commit，因为一次改动常常跨多个提交。

> **接口版本约定**：目前没有语义化版本号。`docs/API.md` 是唯一权威，
> 改动以本文档记录为准。跨版本的对局成绩不可比 —— 见
> [TODO.md](docs/TODO.md) 里「接口版本号没有约定」一条。


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

## 接口修正（2026-10-06）

- **`/place` 的 `appliedRot` 现在真的反映实际生效值。** 它此前**原样回显传入的 `rot`** ——
  传 `9`（越界）返回 `9`，而 `/buildings` 回读的实际 `rotation` 是 `1`。
  于是「拿 `appliedRot` 与自己传的 `rot` 比对来发现越界」这个用途**根本失效**（两者永远相同）。
  已在 `Actor.place` 里归一化（`((rot % 4) + 4) % 4`），实测六组
  `3→3`、`9→1`、`-1→3`、`4→0`、`100→0`、`0→0`，与 `/buildings` 回读**逐条一致**。
  **若客户端曾依赖「`appliedRot == 传入的 rot`」，现在会看到差异 —— 那正是它该反映的东西。**
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
