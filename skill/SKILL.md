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
  version: "1.6.1"
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

**真的需要等一个状态时，用 `/await` 让服务端等** —— 别自己写轮询循环：
轮询的每一次都是一趟模型往返。`/await?until=built:273,84&timeout=90` 一次调用就够。

**为什么较真**：本项目的建造类是**排队**的 —— 接口返回成功只代表请求入队，
不代表已经生效。固定等待会产出「看起来成功、其实没有」的假结论。

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
| `/map` | `x y w h` [`view=all`] | 地形与地表信息（受视野过滤） |
| `/buildings` | — | 己方建筑 |
| `/units` | — | 己方单位 |
| `/rates` | `window` | 资源变化速率。**回看**最近 window 秒，立即返回 —— 验刚做的改动用 `3`，看稳定值用 `30` |
| `/stalls` | — | 产线异常警报（堵塞、缺料、满仓） |
| `/watch` | `since` | 「值得注意」的聚合判定：`clear` 为真表示现在没事，可以睡到下一次事件（配合 `/stream` 或 `/events` 的游标） |
| `/await` | `until` `timeout` | **谓词等待**：让服务端替你等一个状态出现 —— `built:<x>,<y>` / `rate:<物品>:<n>` / `queueEmpty` / `noStall`。超时也返回 200，看 `satisfied` |
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
| `/place` | `x y block [rot] [config] [unit]` | 下建造请求（排队，须轮询确认）；批量用 `shape=`：`line` `area` `rect` `outline` `circle` `point` `path` |
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

`/place` 的 `rot` 是方块朝向参数，取值 0–3。
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
| 建造请求成功但建筑不出现 | `/queue` —— 队列数降不下来就是没被处理 |
| 建筑都在但产率是 0 | `/stalls` —— 它会分别报堵塞、缺料、满仓 |
| 矿机不动 / 空转 | `/drill` |
| 工厂不产出 | `/factory` |
| 客户端反复断连 | `/diag` 的快照路由计数器；为 0 说明服务端没在发 |
| 看到的地图只有一小块 | 用了非 admin token；换 admin 加 `view=all` |
| 观战端起不来 | 用了原版 jar |

**「该造什么」和「为什么不动」是两个问题**：前者查 `/database`（那是资料），
后者查上面那几条运行时状态。分不清就会拿试错来当资料用，那是回合数被烧掉的主因。
