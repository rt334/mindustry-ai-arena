# Mindustry AI Arena · 接口手册

一套让 AI 通过 HTTP/WebSocket 观察并操作 Mindustry 的接口层。服务端是打了补丁的
Mindustry v160.5 headless 服务端 + `ai-arena` mod；观战端是打了补丁的桌面客户端。

```
┌──────────────┐  HTTP :7199   ┌────────────────────────┐
│  AI 客户端    │ ────────────► │  Mindustry 服务端       │
│  (Python 等)  │  WS   :7200   │  + ai-arena mod        │
└──────────────┘               │  TCP 6567 (游戏协议)    │
┌──────────────┐   TCP+UDP    │                        │
│  观战端       │ ────────────► │                        │
└──────────────┘               └────────────────────────┘
```

---

## 一、铁律：禁止一切等待

**这不是风格建议，是硬要求。**

把「等了多久」当判据的代码一律不合格。判据必须是**目标状态是否出现**。

```python
# ✗ 错 —— 把 30 秒当判据
time.sleep(30)
b = arena.building_at(x, y)
if b: print("建好了")

# ✓ 对 —— 轮询 + 提前退出
b = arena.poll_until(lambda: arena.building_at(x, y), timeout=90)
```

```powershell
# ✗ 错
Start-Sleep -Seconds 30

# ✓ 对
$ok = '--'
for($i=0; $i -lt 120; $i++){
  $b = (& curl.exe -sS --max-time 5 -H "Authorization: Bearer $tok" "$base/buildings" 2>&1) -join '' | ConvertFrom-Json
  if($b.data.buildings | Where-Object { $_.x -eq $X -and $_.y -eq $Y }){ $ok='OK'; break }
  Start-Sleep -Milliseconds 100     # 采样间隔，不是「等待」
}
```

`Start-Sleep -Milliseconds 100` 作为**采样间隔**是允许的；`Start-Sleep -Seconds 30`
作为**「等它建好」**是禁止的。区别：前者每次醒来都检查状态、满足即退；后者把时长当判据。

**为什么较真**：`/place` 是**排队**的，返回 `ok` 只代表计划入队，不代表建成。
固定等待会给出「看起来成功、其实没建成」的假结论 —— 本项目在这一点上绕过好几轮弯路。

---

## 二、起局

```powershell
pwsh -File live-match.ps1                # 服务端 + AI + 观战端
pwsh -File live-match.ps1 -NoClient      # 只要服务端和对局
```

内部顺序**不可调换**：

1. `setup` —— 加载地图、放核心、生成建造单位（**必须先进 playing 状态**）
2. `host` —— 打开 6567 端口（注意它会把状态切回 menu/paused）
3. `start` —— 解除暂停
4. AI 客户端
5. 观战端

---

## 三、鉴权

所有接口需要 `Authorization: Bearer <token>`，token 在
`server-run/config/ai-arena.json` 按 agent 分配。

| agent | 角色 |
|---|---|
| `alpha` / `beta` / `agent3` / `agent4` | 参赛 AI，只能看自己队伍视野 |
| `referee` | 裁判（admin），可 `view=all` 看全图 |

```python
from arena import Arena, load_tokens

toks, admin = load_tokens()
a = Arena("alpha", toks["alpha"])
ref = Arena("referee", admin)
```

---

## 四、接口表

统一前缀 `http://127.0.0.1:7199/v1/<agent>/<action>`。写操作用 `POST`。

### 只读

| 接口 | 关键返回 |
|---|---|
| `GET /ping` | 无鉴权健康检查 |
| `GET /state` | `playing` `tick` `world{w,h}` |
| `GET /map?x&y&w&h[&view=all]` | `block` `floor` `drop` `dropHardness` `visible` |
| `GET /buildings` | `x y block rotation health items efficiency powered enabled` |
| `GET /units` | `id type x y health` |
| `GET /rates?window=15` | `core{item:{perSecond}}`、`stored{...}` |
| `GET /stalls` | `kind` ∈ `beltStall` `drillBlocked` `factoryBlocked` `missingInput` |
| `GET /drill` | 每台矿机的 `dominantItem`、脚下矿格、库存 |
| `GET /factory` | 单位工厂产出、`payload` 卡死诊断 |
| `GET /ore?x&y` | 该格矿脉明细 |
| `GET /queue` | 排队中的计划数 |
| `GET /diag` | 含快照路由计数器 `fullViewSends` `spectatorRouted` `teamBatchSends` |
| `GET /content` | 方块/物品/单位表 |
| `GET /database` | 汇总数据库 |

### 写

| 接口 | 说明 |
|---|---|
| `POST /place?x&y&block[&rot]` | **排队**建造；返回 ok ≠ 建成 |
| `POST /break?x&y` | 拆除 |
| `POST /config?x&y&...` | 设方块配置（分拣器过滤物品等） |
| `POST /control?op=...` | `pos` `order` `warp` `enter` `release` `fire` |
| `POST /mine?x&y&unit=` | 让单位挖指定格 |
| `POST /record?action=start\|stop` | 录像 |
| `GET :7200/ws` | WebSocket 事件流 |

### 裁判专属

`/referee/setup?map=` `/referee/host` `/referee/start` `/referee/diag`
`/referee/buildings?view=all` `/referee/units?view=all`
`/referee/admin?action=observe&player=<id>`

**注意**：裁判**不能替别队建造** —— `/place` 会返回
`target tile is not visible to team derelict`。要替某队建造只能用那队的 token。

---

## 五、三个必踩的坑

### ① 扫描矿脉必须用 `view=all`
### ① 扫描世界必须用 `view=all`

队伍 token 只能看到自己视野内的一小块。**据此推算的任何「上限」都是错的**，
而且错得很安静 —— 数字看起来完全合理，只是严重偏低。

裁判（admin）token 加 `view=all` 才能看到全图。

**做容量评估前先确认视野覆盖**：数一下返回里 `visible` 的格数与查询总数的比例。
低于全图就别对「能到多少」下结论。

### ② 传送带 `rotation` = 出料方向

```
0 = 东 (+x)      1 = 北 (+y)
2 = 西 (-x)      3 = 南 (-y)
```

`rotation` 指向的是**出料那一侧**，不是进料侧。要往「y 变小」的方向送料用 `rot=3`。

铺错朝向物品不流动，**而 `/place` 照样返回 ok** —— 从外部看就是「建筑都在、产率 0」。

### ③ `/place` 排队，建造单位要走到工地

`POST /place` 返回成功只代表**计划入队**。
建造单位必须**物理走到**工地才会施工；超出 `buildRange`（220px ≈ 27 格）它会自己走过去，
这需要时间。

**所以下完单必须轮询 `/buildings` 确认。** 固定等待会给出「看起来成功、其实没建成」的假结论。

排查入口：`GET /queue` —— `plans` 数字**降不下来**，说明建造单位到不了工地。

---


---

## 六、引擎层说明

**本手册只讲接口。** 引擎行为、方块语义、以及三个已修复的引擎缺陷，
都在 [`ENGINE-NOTES.md`](ENGINE-NOTES.md) 里。

这么分的理由：接口手册是给**调用方**看的，引擎笔记是给**维护者**看的。
把引擎事实混进接口手册，等于把「玩家要靠试验才能得到的知识」顺手塞给了读接口文档的人 ——
这与本项目「公平竞技」的第一原则冲突。

接口层需要调用方自己确定的只有一件事：`/place` 的 `rot` 参数语义。
到游戏里放一个、看它往哪边走即可，不需要文档告知。
## 七、观战端

```powershell
$jdk = 'C:\...\zulu17\bin\java.exe'
$jar = 'C:\dsh\Mindustry-src\desktop\build\libs\Mindustry.jar'   # 自建，不是 vanilla
Start-Process $jdk -ArgumentList '-Xmx2G',
  '-Djava.net.preferIPv4Stack=true',        # 必带：否则 JVM 把 UDP 绑 IPv6，
                                            # 收不到服务端按 IPv4 发的快照
  '-Dmindustry.autoreconnect=true',          # 断线自动重连
  '-jar', $jar
```

**⚠ 不要用 `C:\dsh\_dl\mindustry-v160.5\Mindustry.jar`** —— 原版客户端启动会报
`Unknown revision '3' for entity type 'PlayerComp'` 直接崩。

数据目录（存档/设置/mods）由引擎决定，是 OS 的 app-data 目录
（`%APPDATA%\Mindustry`），**与 `-WorkingDirectory` 无关**。

---

## 八、Python 客户端库

```python
from arena import Arena, load_tokens

toks, admin = load_tokens()
a = Arena("alpha", toks["alpha"])

a.wait_online(timeout=120)                        # 轮询等在线

b = a.place_and_confirm(61, 108, "mechanical-drill", timeout=90)
if b is None:
    print("没建成 —— 查 /queue 和 /stalls")

for k, v in (a.rates(window=15).get("core") or {}).items():
    print(f"{k:<10} {v['perSecond']:7.2f}/s")

for s in a.stalls()[:10]:
    print(s["kind"], s["x"], s["y"])
```

`Arena.poll_until(pred, timeout)` 是库中**唯一**的等待原语，语义是
「轮询直到 pred 为真，命中立刻返回」。

---

## 九、故障速查

| 现象 | 原因 | 处理 |
|---|---|---|
| `/place` 返回 ok 但建筑不出现 | 计划排队中，建造单位要走到工地；或目标格被占；或方块未解锁 | 轮询 `/buildings`；查 `/queue`（`plans` 卡住不降 = 到不了工地） |
| 产率 0 但建筑都在 | 传送带朝向错 / 没接上核心 | 查 `/stalls` 的 `beltStall`、`missingInput` |
| 客户端反复断连报 UDP 快照超时 | 服务端没发快照 | 查 `/diag` 的 `fullViewSends` `spectatorRouted` 是否为 0 |
| 单位不动 | `SyncComp.update()` 的插值补丁被改回 | 见第七节 |
| 观战端起不来 | 用了 vanilla jar | 换成自建 `desktop/build/libs/Mindustry.jar` |
| 只看到一小块地图 | 用了队伍 token 扫图 | 换 admin token 加 `view=all` |
