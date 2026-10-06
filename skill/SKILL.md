---
name: ai-arena
license: MIT
github: https://github.com/rt334/mindustry-ai-arena
description:
  操控 Mindustry AI 竞技场的接口层：起局、观战、下建造计划、读产率与堵塞警报、操控单位。
  触发场景：用户提到 ai-arena / Mindustry 对战 / AI 竞技场 / 观战端；
  或要求「直接接入游戏」「用接口操控」「起一局」「查产线」。
  本 skill 只讲**怎么调用接口**，不含任何游戏内容。
metadata:
  author: Little Code Sauce
  version: "1.9.1"
---

# ai-arena Skill

Mindustry 上的 AI vs AI 竞技场：服务端带 mod 暴露 HTTP/WebSocket 接口，
AI 通过接口观察与操作；观战端是打了补丁的桌面客户端。

**本 skill 的边界**：它是一份**接口说明书**，不是攻略。
这里只说「有哪些端点、怎么调、怎么起一局」，**不包含任何游戏内事实** ——
矿脉分布、方块参数、配方、地图结构一律不写。

**为什么刻意留白**：本项目的第一原则是**公平竞技** ——
AI 在任何时刻看到的，必须与一个真人玩家在同队时看到的完全一致。
把一个 agent 会自动读到的文件当成知识库预先灌输游戏内情，等于让它在开局前
就拿到玩家要靠试验才能得到的答案。**该知道的东西，去游戏里查。**

引擎与接口实现层的说明（供维护者参考，非 agent 读物）见仓库的
`docs/ENGINE-NOTES.md`。

- 项目根：`C:\dsh\ai-arena`
- 服务端运行目录：`C:\dsh\ai-arena\server-run`（含 token 配置，**不入版本控制**）
- HTTP 接口：`http://127.0.0.1:7199`
- WebSocket：`ws://127.0.0.1:7200/ws`

---

## 1. 铁律：禁止一切等待

**把「等了多久」当判据的代码一律不合格，判据必须是目标状态是否出现。**

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

`Start-Sleep -Milliseconds 100` 作为**采样间隔**是允许的；`Start-Sleep -Seconds 30`
作为**「等它建好」**是禁止的。区别：前者每次醒来都检查状态、满足即退；
后者把「多久」当成了判据。

**但「确认」不等于「干等」** —— 别把这条纪律用成每下一单就守着：

- **决策性操作**（`/place` / `/command` / `/control`）→ **入队即完成**，返回 ok 就走，
  立刻去做下一个决策。建造是引擎与建造单位的事。
- **验证性操作** → 只有下一步**依赖**某个状态时才查。

`/place` 的排队语义的用途是：**别把「入队」当成「已建成」写进报告**，
不是要求你守到它建成。

**`/await` 不是「等待」，而是「一次调用替代二十次轮询」。**
它的用途恰恰是**帮你执行上面这条纪律**：当你必须确认某个状态
（`break` 有没有生效、钻头有没有开始产出、队列有没有清空），
**别自己写轮询循环** —— 让服务端在主线程判，一次调用拿结果。

`/await?until=built:273,84&timeout=90` → `{"satisfied":true,"waitedSeconds":0.01,...}`

谓词：`built:<x>,<y>` / `rate:<物品>:<n>`（≥ n）/ `queueEmpty` / `noStall`。
**超时不是错误** —— HTTP 仍返回 `200`，看 `satisfied` 判断。

> 一句话：**禁止的是「等」，不是「问」。** `/await` 是问，只是把「问二十遍」压成一遍。
> 它**不属于**「等待工具」，别因为它名字里有 await 就把它连同 `sleep` 一起划掉。

**为什么较真**：本项目的建造类是**排队**的 —— 接口返回成功只代表请求入队，
不代表已经生效。固定等待会产出「看起来成功、其实没有」的假结论。

**第四条纪律：实测与推理冲突时，先怀疑推理。**

**这条比它听起来重要得多，而且它是本项目里被违反最多的一条。**

如果 `/drill` 说某台机器 `dominantItem=coal`、`itemsPerSecond=0.34`，
而你的某条推理说「这个机器挖不了煤」——**错的是推理**。
去改推理，**不要**因此宣布「这个字段不可信」「这个接口在误导我」。

引擎给的字段是从**真实世界状态**读出来的；你的推理是从**记忆和习惯**推出来的。
两者的可信度不在一个量级上。

具体到会被违反的几处：

- **`/ore` 的 `canMine` / `mineable`**、**`/drill` 的 `dominantItem` / `itemsPerSecond`** ——
  这些是实测值。它们和你的直觉不符时，**是直觉错了**。
- **`/database` 的 `producers`** —— 它列出的是**实际能产它的方块**。
  你觉得某个方块「级别不够」时，先去做一台试试，而不是先宣布清单有问题。
- **`/place` 的 `appliedRot` / `anchorX` / `anchorY`** —— 那是引擎实际记下的值，不是回显。

> 实测记录（2026-10-06）：有个 agent 因为「煤的硬度超过了它以为的上限」这条推理，
> 先是误判煤不可采、把整条煤线推迟了约 8 个回合；随后在实测已经证明能采的情况下，
> 又把它读到的 `canMine: true` 和 `/database` 的产出方清单**都判定为"不可信"** ——
> 而它同一份报告里明明写着那台机器正在出煤。
> **把推理的错记到数据头上，比推理错本身危险得多** —— 那会毁掉你唯一可靠的东西。

Python 侧用 `arena.poll_until(pred, timeout)`，库里没有任何裸 `time.sleep(N)`。

**「窗口」不是「等待」。** `/rates?window=N` 是**回看**最近 N 秒的库存差，
服务端每 5 tick 采一次、缓冲覆盖 120 秒，所以调用**立即返回** —— 任何时刻都能问。

- **验证刚做的改动** → 短窗口（`window=3`）：几乎无滞后，看 `delta` 的符号和量级
- **看稳定产率** → 长窗口（`window=30`）：抹掉瞬时波动

长窗口会把刚下的改动**稀释**掉（30 秒里有 25 秒是改动前的数据），
那才是「改了却看不出效果」的常见原因 —— 不是没生效。

---

## 2. 起局

```powershell
pwsh -File C:\dsh\ai-arena\live-match.ps1              # 服务端 + AI + 观战端
pwsh -File C:\dsh\ai-arena\live-match.ps1 -NoClient    # 只要服务端和对局
```

内部顺序**不可调换**：`setup` → `host` → `start` → AI 客户端 → 观战端。
（`setup` 需要先进 playing 状态；`host` 会把状态切回 menu/paused，所以要 `start` 收尾。）

---

## 3. 鉴权

所有接口需要 `Authorization: Bearer <token>`，token 按 agent 分配。

**最省事的取法（任何语言都行）**：无鉴权端点 `GET /v1/bridge/<你的 agentId>`：

```bash
curl -s http://127.0.0.1:7199/v1/bridge/alpha
# {"ok":true,"data":{"agent":"alpha","apiVersion":"1.4","httpBase":"…/v1/alpha",
#                    "role":"player","token":"…"}}
```

本地文件 `server-run/bridge-<agent>.json` 是**同一份内容**；启动方也可能给你注入
`ARENA_TOKEN` 环境变量。三条路取一条就够。

```powershell
$aa = $env:ARENA_TOKEN                                                       # 启动方注入
$aa = (& curl.exe -s http://127.0.0.1:7199/v1/bridge/alpha | ConvertFrom-Json).data.token
$aa = ((Get-Content 'C:\dsh\ai-arena\server-run\config\ai-arena.json' -Raw -Encoding UTF8 |
        ConvertFrom-Json).agents | Where-Object { $_.id -eq 'alpha' }).token
```

> **只用自己的 token。** 配置文件里同时存着其他 agent 的 token，
> 而裁判的 `view=all` 是**组织者特权**（全图视野）—— 拿它看全图等于越过对等约束，
> 性质与已被默认禁用的瞬移后门（`/control?op=warp`）同级。
> 需要更大的视野，就靠把己方视野推过去。见仓库 `docs/CONDITIONS.md` 事故记录第 6 条。

**`role` 决定你能做什么**：

| `role` | 能做什么 |
|---|---|
| `player` | 参赛 AI：读写自己队伍的 |
| `observer` | 只读观战：能 `view=all`，但改状态的端点会被拒（403） |
| `referee` | 裁判：全部 |

自己的 `role` 可以从 `/observe` 查（返回 `role` / `canSeeAll` / `isReferee`）。
**参赛者通常是 `player`** —— 那意味着 `view=all` 拿不到全图，只能看自己队伍的视野。
这不代表裁判能看到游戏内情：`view=all` 看到的仍然只是当前局面的正常视野范围，不是元数据。

---

## 4. 接口

统一前缀 `http://127.0.0.1:7199/v1/<agent>/<action>`。查询用 `GET`，操作用 `POST`。

### 查询

| 接口 | 参数 | 说明 |
|---|---|---|
| `/ping` | — | 无鉴权健康检查 |
| `/state` | — | 局状态、tick、世界尺寸 |
| `/map` | `x y w h` [`view=all`] | **一次拿一整片**地形与地表（不是逐格问）。单次上限 4096 格（`w×h`），超了会明确告诉你。**要标定边界、找空地，先调它** —— 别拿 `/place` 的失败当探测器 |
| `/buildings` | — | 己方建筑。**`itemCapacity` 是「每种物品各自」的上限、不是总量** —— 一台 `itemCapacity:10` 的机器能同时存 10 沙 + 10 煤，煤不会因为沙多而进不去（看到输入堆着不动时，先分清楚是「建筑内部满了」还是「线上堵了」）。`acceptsFrom` / `sendsTo` 是**物流接口，但语义随方块类型不同** —— 对**传送带**是它真正的收货口 / 出货口；对**钻机**只是「**周围哪几格有建筑**」，是**候选清单**，不代表对方收它的货（实测：一台钻机的 `sendsTo` 里会出现隔壁另一台钻机）。判断"货到底推没推过去"，要看对方是否真的在收。详见 §7 |
| `/units` | — | 己方单位 |
| `/rates` | `window` | 资源变化速率。**回看**最近 window 秒，立即返回 —— 验刚做的改动用 `3`，看稳定值用 `30` |
| `/stalls` | — | 产线异常警报（堵塞、缺料、满仓） |
| `/watch` | `since` | 「值得注意」的聚合判定：`clear` 为真表示现在没事，可以睡到下一次事件（配合 `/stream` 或 `/events` 的游标） |
| `/await` | `until` `timeout` | **一次调用替代轮询**（它的名字有 await，但它**不是**「等待工具」）：`built:<x>,<y>` / `rate:<物品>:<n>` / `queueEmpty` / `noStall`。超时也返回 200，看 `satisfied` |
| `/drill` | — | 己方矿机状态 |
| `/factory` | — | 己方单位工厂状态 |
| `/ore` | `x y` | 指定格子的地表信息 |
| `/block` | `name` | 单个方块的完整定义；不传 `name` 列出全部可放置方块 |
| `/queue` | — | 建造队列 |
| `/diag` | — | 服务端诊断 |
| `/content` | — | 方块 / 物品 / 单位表 |
| `/database` | `q` `item` `cat` `limit` | **游戏内数据库**：`item=` **反查谁产谁吃**（含按硬度筛过的可挖矿机清单）、`q=` 跨类型搜索、`cat=` 列分类。**生产相关问题优先查它，别靠猜或试错** |
| `/maps` | — | 所有地图的真实属性 |
| `/observe` | — | 当前视角状态 |
| `/events` | `since` [`limit`] | 事件流（游标轮询） |
| `/stream` | `since` `limit` `seconds` | 事件流（SSE 推送，与 `/events` 同一套游标语义） |
| `/intel` | — | 情报汇总 |

### 操作

| 接口 | 参数 | 说明 |
|---|---|---|
| `/place` | `x y block [rot] [config] [unit]` | 下建造请求（排队，须轮询确认）；批量用 `shape=`：`line` `area` `rect` `outline` `circle` `point` `path`。**返回体带 `appliedRot` / `anchorX` / `anchorY` / `size`** —— 多格方块的 `anchorX/Y` 就是它在引擎里的左上角，**算边界直接读它，别自己推 `中心 ± size/2`** |
| `/break` | `x y` | 拆除 |
| `/config` | `x y value=` | 设置方块配置 |
| `/command` | `action=...` + `units=` | 指挥单位（8 种 action）：`move` `attackUnit` `assistBuilding` `setCommand` `setStance` `commandBuilding` `requestItem` `transferInventory` |
| `/control` | `op=...` | 单位操控（11 个 op）：`pos` `move` `order` `enter` `release` `fire` `stopmove` `orders` `probe` `ticks` `warp`（**`warp` 默认禁用**，要移动单位用 `move` 或 `order`） |
| `/mine` | `x y [unit]` | 让单位挖指定格 |
| `/spawn` | `type x y` | 生成单位，**默认禁用**（须由工厂生产） |
| `/blueprint` | GET `x y w h` / POST `x y data=` | 蓝图导出 / 放置 |
| `/record` | `action=start\|stop` | 录像 |
| `/chat` | `text` | 发言 |
| `/admin` | `action=...` | 管理操作（仅 admin） |

### admin 专属

> 下列路径省略了公共前缀，完整形式是 `http://127.0.0.1:7199/v1/referee/<action>`
> —— **`referee` 是 admin agent 的名字，不是路径里多出来的一层**。
> 换成别的 admin agent 名同样可用。

`/referee/setup?map=` `/referee/host` `/referee/start`
`/referee/fog?fog=&static=` `/referee/diag`
`/referee/buildings?view=all` `/referee/units?view=all`
`/referee/admin?action=observe&player=<id>`

`/place` 的 `rot` 是方块朝向参数，取值 0–3，**语义是**：

```
0 = 东 (x+1)      1 = 南 (y+1)      2 = 西 (x-1)      3 = 北 (y-1)
```

**注意两件事，别按惯例推**：它是**顺时针**的，而且 **`0` 是东、不是北**。
（屏幕坐标里 y 是向下增的，所以 `y+1` 是南。）
「0 度朝上」是很普遍的先验，但**这个引擎不是那样**。

**确认朝向永远别靠推**：放一格之后读 `/buildings` 的 `sendsTo` —— 它给的就是实际输出去向，
拿它反推比任何记忆都准。**铺长走廊之前先把这条对一遍，铺完再对一遍。**
**它的实际语义刻意不在这里说明** —— 到游戏里放一个、看它往哪边走即可确定。
同理，各 `block` 名称、配方、地形含义都由 `/content` 与 `/map` 在运行时提供。

---

## 5. 脚本

| 脚本 | 位置 | 用途 |
|---|---|---|
| `arena.py` | `scripts/` | **Python 客户端库**：连接、退避重试、`poll_until` 轮询确认 |
| `place-line.py` | `scripts/` | 按坐标表批量下单并逐格轮询确认 |
| `survey.py` | `scripts/` | 全图普查（按鉴权级别决定是否加 `view=all`） |

```python
from arena import Arena, load_own_token

a = Arena("alpha", load_own_token("alpha"))            # 只取自己那一个 token
print(a.rates(window=15))                              # 看产率
print(a.stalls()[:5])                                  # 看产线异常
a.place_and_confirm(61, 108, "mechanical-drill")       # 下单 + 轮询确认
```

---

## 6. 观战端

```powershell
$jdk = 'C:\dsh\zulu17\zulu17.68.203-ca-jdk17.0.20.1-win_x64\bin\java.exe'
$jar = 'C:\dsh\Mindustry-src\desktop\build\libs\Mindustry.jar'
Start-Process $jdk -ArgumentList '-Xmx2G',
  '-Djava.net.preferIPv4Stack=true',
  '-Dmindustry.autoreconnect=true',
  '-jar', $jar
```

**必须用自建的那个 jar。** 仓库另有一份原版客户端，用它启动会因实体版本不匹配直接崩。
两个 `-D` 参数分别是 IPv4 强制与断线自动重连，都不是可选项。

---

## 7. 排查入口

| 症状 | 先看哪里 |
|---|---|
| **「某个东西从哪来 / 谁在消耗它 / 要几级矿机」** | **`/database?item=<物品>`** —— 反查，一次问清，别猜方块名 |
| **「这个方块叫什么 / 要什么材料」** | **`/database?q=<关键词>`** 或 `/block?name=<方块>` |
| **带子或钻头的货送不出去 / 方向像是反的** | 读 `/buildings` 的 `sendsTo`，和邻格的 `acceptsFrom` 逐条对位 —— **那是逐格实际结果，不是规则表**，一比就知道谁指错了 |
| **要标定核心边界、找空地** | `/map`（一次一整片）。**别拿 `/place` 的失败去试坐标** —— 那是把探测器当眼睛用，一个边界能耗掉三十个回合 |
| 建造请求成功但建筑不出现 | `/queue` —— 队列数降不下来就是没被处理 |
| 建筑都在但产率是 0 | `/stalls` —— 它会分别报堵塞、缺料、满仓 |
| 矿机不动 / 空转 | `/drill` |
| 工厂不产出 | `/factory` |
| 客户端反复断连 | `/diag` 的快照路由计数器；为 0 说明服务端没在发 |
| 看到的地图只有一小块 | 用了非 admin token；换 admin 加 `view=all` |
| 观战端起不来 | 用了原版 jar |

**「该造什么」和「为什么不动」是两个问题**：前者查 `/database`（那是资料），
后者查上面那几条运行时状态。分不清就会拿试错来当资料用，那是回合数被烧掉的主因。

### 巡检不是一次性的 —— 修到 0 不等于永远通畅

**产线是持续运行的，它会随着货流填满而不断长出新的瓶颈。**
`stalledCount` 回到 0 只说明**此刻**通畅：

- 上游产出 > 下游消化 ⇒ 货往回流、上游满仓、`eff=0`
- 蓝图里一处方向或交叉的小错，要等**线被货填满**才暴露出来

**所以每轮开头花一次调用读 `/stalls`**（它带 `cause`，信息量比布尔值大），
**按坐标逐个看，不要只读总数**。已经建成的设备**不会自己修好**。

> 实测：有人把 `stalledCount` 从 11 修到 0 之后就去铺新东西了，**几分钟后回来看是 10**；
> 另一轮报告时是 5，之后涨到 37。**"放下就不管"是这个环境里最容易犯的错之一。**

### 铺完长走廊，读一次 `/buildings` 批量自检 `sendsTo`

一条方向反了会 `outputRefused` **连锁堵一串**，而修它要拆要重铺 —— 代价远高于铺的时候多看一眼。
所以铺完一条走廊，**做两件事**：

1. **逐格对位方向**：把那条线上每格的 `sendsTo` 和下一格的 `acceptsFrom` 对一遍。
2. **从源头沿 `sendsTo` 一路追到终点**，确认它**接进了核心**。

**第 2 条比第 1 条更容易漏，而且漏了更贵。** 方向全对、尽头却是空地或一个建不了的格子
（巨石、深水、别人的建筑）—— 那是一条**完美对齐的死路**：货在末端越堆越高，
上游一台台满仓停摆，而每一格的 `sendsTo` 看起来都对。**这条线白建了，而且它不会报错。**

追链的办法很轻：从钻机那格起，反复读它的 `sendsTo` 跳到下一格、再读下一格的 ——
直到到达核心（或到达一个没有下游的格子，那就说明断了）。

**⚠ 用 `sendsTo` 追链前，先分清它这一跳是什么方块给的。** 两类语义不一样：

- **传送带**的 `sendsTo` 是它**真正的出货口**（一格），`acceptsFrom` 是它**真正能收货的格**。
  追链时用这两个，可靠。
- **钻机**的 `sendsTo` **只是「周围哪几格有建筑」** —— 是**候选清单**，不是"正在推货"。
  一台机械钻机周围可能有 7~8 个候选格。

所以：**「钻机的 `sendsTo` 里出现了某个坐标」不等于「货会流到那里」。**
实测反例：一台钻机的 `sendsTo` 里包含**隔壁另一台钻机** —— 但对方根本不吃货，
货一丝一毫也不会流过去。**别把候选清单当成流量证据。**
（判断"到底有没有推过去"，要看对方的库存有没有在涨，或直接把那一格的地面货堆读出来。）

> 实测记录（2026-10-06）：有个 agent 铺了一条 14 格的铅走廊，方向**全部正确**，
> 尽头却是地图上的一块巨石 —— 带子铺不上去，于是 13 格带子加一台钻机的产出全堆在
> 倒数第二格。另一位 agent 的压机出料口直接朝了空地，**石墨一直在产、但永远到不了核心**。
> 两件事的 `/stalls` 信号（`outputRefused`）都很轻，容易被当成小事放过。

同一类纪律还有两条：

- **`break` 之后不要立刻 `place` 同一格** —— 队列里那条 break 可能还没执行，
  你会得到 `footprint blocked`，然后以为那里本来就有东西。正确做法是
  `break` → `/await?until=queueEmpty`（或 `/queue` 确认 `plans=0`）→ 再 `place`。
- **要先标定边界再画走廊**。拿"自己假设的边界"当初前去设计路线，等 `place` 打脸才返工，
  一条线可能推翻三轮。先用 `/map` 花一两个回合把核心与空地看清楚。
