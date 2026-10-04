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
  version: "1.1.0"
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

**为什么较真**：本项目的建造类是**排队**的 —— 接口返回成功只代表请求入队，
不代表已经生效。固定等待会产出「看起来成功、其实没有」的假结论。

Python 侧用 `arena.poll_until(pred, timeout)`，库里没有任何裸 `time.sleep(N)`。

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

所有接口需要 `Authorization: Bearer <token>`，token 在
`server-run/config/ai-arena.json` 按 agent 分配。

```powershell
$cfg = Get-Content 'C:\dsh\ai-arena\server-run\config\ai-arena.json' -Raw -Encoding UTF8 | ConvertFrom-Json
$ref = ($cfg.agents | Where-Object { $_.admin }).token      # admin
$aa  = ($cfg.agents | Where-Object { $_.id -eq 'alpha' }).token
```

**admin 与普通 agent 的差别只在「能看多少」**：admin 可以带 `view=all` 看全图，
普通 agent 只能看自己队伍视野。**这不代表 admin 能看到游戏内情** ——
`view=all` 看到的仍然只是当前局面的正常视野范围，不是元数据。

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
| `/rates` | `window` | 资源变化速率 |
| `/stalls` | — | 产线异常警报（堵塞、缺料、满仓） |
| `/drill` | — | 己方矿机状态 |
| `/factory` | — | 己方单位工厂状态 |
| `/ore` | `x y` | 指定格子的地表信息 |
| `/queue` | — | 建造队列 |
| `/diag` | — | 服务端诊断 |
| `/content` | — | 方块 / 物品 / 单位表 |
| `/database` | — | 汇总数据库 |
| `/events` | — | 事件流 |
| `/intel` | — | 情报汇总 |

### 操作

| 接口 | 参数 | 说明 |
|---|---|---|
| `/place` | `x y block [rot]` | 下建造请求 |
| `/break` | `x y` | 拆除 |
| `/config` | `x y ...` | 设置方块配置 |
| `/control` | `op=...` | 单位操控：`pos` `order` `warp` `enter` `release` `fire` |
| `/mine` | `x y [unit]` | 让单位挖指定格 |
| `/record` | `action=start\|stop` | 录像 |
| `/chat` | `text` | 发言 |
| `/admin` | `action=...` | 管理操作（仅 admin） |

### admin 专属

`/referee/setup?map=` `/referee/host` `/referee/start` `/referee/diag`
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
from arena import Arena, load_tokens

toks, admin = load_tokens()
a = Arena("alpha", toks["alpha"])
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
| 建造请求成功但建筑不出现 | `/queue` —— 队列数降不下来就是没被处理 |
| 建筑都在但产率是 0 | `/stalls` —— 它会分别报堵塞、缺料、满仓 |
| 矿机不动 / 空转 | `/drill` |
| 工厂不产出 | `/factory` |
| 客户端反复断连 | `/diag` 的快照路由计数器；为 0 说明服务端没在发 |
| 看到的地图只有一小块 | 用了非 admin token；换 admin 加 `view=all` |
| 观战端起不来 | 用了原版 jar |
