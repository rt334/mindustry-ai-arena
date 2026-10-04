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

### `GET /units`

返回 `data.units` 数组：`id` `type` `team` `x` `y` `health`。

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

建造队列：每个建造单位正在排队的计划数
`{"builders":[{"unit":N,"plans":N}]}`。

### `GET /diag`

服务端诊断计数器，含快照路由统计
`teamBatchSends` `fullViewSends` `spectatorRouted`。

### `GET /content`

方块 / 物品 / 单位表。**运行时取用，不要凭记忆。**

### `GET /database`

汇总数据库。

### `GET /events`

事件流。

### `GET /intel`

情报汇总。

---

## 四、可执行的操作

| 接口 | 参数 | 说明 |
|---|---|---|
| `POST /place` | `x` `y` `block` [`rot`] | 下建造请求 |
| `POST /break` | `x` `y` | 拆除 |
| `POST /config` | `x` `y` … | 设置方块配置 |
| `POST /control` | `op=` … | 单位操控。`op` 取值：`pos` `order` `warp` `enter` `release` `fire` `stopmove` `orders` |
| `POST /mine` | `x` `y` [`unit`] | 让单位挖指定格 |
| `POST /record` | `action=start\|stop` | 录像开关 |
| `POST /chat` | `text` | 发言 |
| `POST /admin` | `action=` … | 管理操作（仅 admin） |

`rot` 取值 0~3。各 `block` 的参数（尺寸、配方）由 `/content` 在运行时提供。

### admin 专属

| 接口 | 说明 |
|---|---|
| `POST /referee/setup?map=` | 加载地图、放核心、生成建造单位 |
| `POST /referee/host` | 打开游戏端口 6567 |
| `POST /referee/start` | 解除暂停 |
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
