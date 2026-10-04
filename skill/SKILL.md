---
name: ai-arena
license: MIT
github: https://github.com/rt334/mindustry-ai-arena
description:
  操控 Mindustry AI 竞技场（dsh ai-arena）：起局、观战、下建造计划、读产率与堵塞警报、操控单位。
  触发场景：用户提到 ai-arena / Mindustry 对战 / AI 竞技场 / 观战端 / 矿机 / 传送带 / 产率 / 堵塞；
  或要求「直接接入游戏」「用接口操控」「起一局」「扩产」「查产线」。
  也适用于调试该项目的引擎补丁（BuilderComp 移动、SyncComp 快照、NetServer 路由）。
metadata:
  author: Little Code Sauce
  version: "1.0.0"
---

# ai-arena Skill

Mindustry v160.5 上的 **AI vs AI 竞技场**：服务端带 mod 暴露 HTTP/WebSocket 接口，
AI 客户端通过接口观察与操作，观战端是打了补丁的 Mindustry 桌面客户端。

- 项目根：`C:\dsh\ai-arena`
- 引擎源码（含补丁）：`C:\dsh\Mindustry-src`
- JDK17：`C:\dsh\zulu17\zulu17.68.203-ca-jdk17.0.20.1-win_x64`
- 服务端运行目录：`C:\dsh\ai-arena\server-run`（含 token 配置，**不入版本控制**）

---

## 0. 铁律：禁止一切等待

**这是本 skill 最重要的一条。**

**禁止** `Start-Sleep` / `sleep` / 固定次数轮询后放弃 —— 除非是等编译或等进程起来这类
**无法用状态观测替代**的场景，且必须短。

**正确做法：轮询 + 提前退出。** 判据是「目标状态是否出现」，不是「等了多久」。

```powershell
# ✗ 错：固定等 30 秒，无论成没成
Start-Sleep -Seconds 30
$b = ...

# ✓ 对：一有结果就退出
$ok = '--'
for($i=0; $i -lt 120; $i++){
  $b = (& curl.exe -sS --max-time 5 -H "Authorization: Bearer $tok" "$base/buildings" 2>&1) -join '' | ConvertFrom-Json
  if($b.data.buildings | Where-Object { $_.x -eq $X -and $_.y -eq $Y }){ $ok='OK'; break }
  Start-Sleep -Milliseconds 100     # 100ms 是采样间隔，不是「等待」
}
```

`Start-Sleep -Milliseconds 100` 作为**采样间隔**是允许的；`Start-Sleep -Seconds 30` 作为
**「等它建好」** 是禁止的。区别在于：前者每次醒来都检查状态并在满足时立刻退出，
后者把「多久」当成了判据。

同理，Python 里用 `while time.time() - t0 < timeout:` 加 `break`，不要裸 `time.sleep(N)`。

---

## 1. 起一局

```powershell
# 一条命令起完整对局（服务端 + AI 客户端 + 观战端）
pwsh -File C:\dsh\ai-arena\live-match.ps1

# 只要服务端和对局，不要客户端
pwsh -File C:\dsh\ai-arena\live-match.ps1 -NoClient
```

脚本内部顺序**不可调换**：`setup`（放核心、生成建造单位，必须先进 playing）→
`host`（开 6567 端口；注意它会把状态切回 menu/paused）→ `start`（解除暂停）→
AI 客户端 → 观战端。

---

## 2. 取 token

所有接口都要 `Authorization: Bearer <token>`。token 在
`server-run/config/ai-arena.json` 里按 agent 分配。

```powershell
$cfg = Get-Content 'C:\dsh\ai-arena\server-run\config\ai-arena.json' -Raw -Encoding UTF8 | ConvertFrom-Json
$ref = ($cfg.agents | Where-Object { $_.admin }).token      # 裁判，可看全图
$aa  = ($cfg.agents | Where-Object { $_.id -eq 'alpha' }).token
```

**`referee`（admin）能 `view=all` 看全图；队伍 token 只能看自己视野。**

---

## 3. 常见的三个坑（都实测踩过）

**① 扫描矿脉必须用 `view=all`。** 用队伍 token 扫只看得到自己那 17% 视野，
会得出完全错误的产能上限（实测因此误判「目标不可达」，白绕一整轮）。

```powershell
curl.exe -H "Authorization: Bearer $ref" "$base/referee/map?x=0&y=0&w=350&h=200&view=all"
```

**② 传送带 `rotation` = 出料方向，且 `1=北(+y) 3=南(-y)`。**
`0=东(+x) 1=北(+y) 2=西(-x) 3=南(-y)`。要往「y 变小」的方向送料用 `rot=3`。
铺错朝向物品不流动，而且 `/place` 照样返回 ok。

**③ `/place` 是排队的，HTTP 200 ≠ 已建好。** 建造单位要**真的走到**工地才会施工。
所以下完单必须轮询 `/buildings` 确认，不能假定成功。

---

## 4. 接口速查

全部走 `http://127.0.0.1:7199/v1/<agent>/<action>`，`POST` 用于写操作。

### 只读

| 接口 | 说明 |
|---|---|
| `GET /ping` | 无鉴权健康检查 |
| `GET /state` | 局状态、tick、世界尺寸 |
| `GET /map?x&y&w&h[&view=all]` | 地形：`block/floor/drop/dropHardness` |
| `GET /buildings` | 己方建筑（含 `items/efficiency/powered`） |
| `GET /units` | 己方单位 |
| `GET /rates?window=15` | **产率**（/s），分 `core` 与 `stored` |
| `GET /stalls` | **堵塞/缺料警报**：`beltStall` `drillBlocked` `factoryBlocked` `missingInput` |
| `GET /drill` | 每台矿机的 `dominantItem`、脚下矿格、库存 |
| `GET /factory` | 单位工厂的产出与卡死诊断 |
| `GET /ore` | 指定格子的矿脉明细 |
| `GET /queue` | 建造队列（排队中的计划数） |
| `GET /diag` | 服务端诊断（含快照路由计数器） |
| `GET /content` | 方块/物品/单位表 |
| `GET /database` | 汇总数据库 |

### 写操作

| 接口 | 说明 |
|---|---|
| `POST /place?x&y&block[&rot]` | 下建造计划（**排队**） |
| `POST /break?x&y` | 拆除 |
| `POST /config?x&y&...` | 设置方块配置（如分拣器过滤物品） |
| `POST /control?op=...` | 单位操控：`pos` `order` `warp` `enter` `release` `fire` |
| `POST /mine?x&y&unit=` | 让单位挖指定格 |
| `POST /admin?action=...` | 管理操作（仅 admin） |
| `POST /record?action=start\|stop` | 录像 |
| `GET /ws`（端口 7200） | WebSocket 事件流 |

**裁判专属**：`/referee/setup?map=` `/referee/host` `/referee/start` `/referee/diag`
`/referee/buildings?view=all` `/referee/units?view=all` `/referee/admin?action=observe&player=`

---

## 5. 脚本

| 脚本 | 用途 |
|---|---|
| `scripts/arena.py` | **Python 客户端库**：连接、重试、自动重连 |
| `scripts/place-line.py` | 按坐标表批量下单并轮询确认 |
| `scripts/survey.py` | 全图矿脉/地板普查（自动用 view=all） |
| `../plan-ore.py` | 矿脉规划器：算非重叠最优选址与产能上限 |
| `../build-all.py` | 主干 + 梳状矿机阵列一键铺设 |
| `../core-drills.py` | 贴着核心环布矿机（零传送带直喂） |

`plan-ore.py` 用法（**先算上限再下结论**）：

```powershell
python plan-ore.py --token $ref --drill laser-drill --all --x0 0 --y0 0 --w 350 --h 200
```

---

## 6. 引擎已验证的关键事实

| 事实 | 值/行为 |
|---|---|
| 传送带 `rotation` | **出料方向**；`0=东(+x) 1=北(+y) 2=西(-x) 3=南(-y)` |
| 2×2 建筑邻近偏移 | `{(0,-1),(0,2),(-1,0),(2,0),(1,-1),(1,2),(-1,1),(2,1)}` |
| 矿机公式 | `getDrillTime = (drillTime + 50*hardness) / drillMultipliers` |
| 矿机带水加成 | `liquidBoostIntensity = 1.6` |
| 矿脉硬度 | sand 0 / copper 1 / lead 1 / coal 2 / titanium 3 / thorium 4 |
| 建造单位射程 | `buildRange = 220px ≈ 27 格` |
| 分拣器 `sorter` | 匹配 `config` 走正面；**不匹配走两侧** |
| `router` | 会被成品倒灌堵死，慎用 |

矿机速率（每 2×2 footprint = 4 格）：沙 0.400/s、铜/铅 0.369/s、煤 0.343/s。

---

## 7. 三条已修好的引擎缺陷（别改回去）

| 位置 | 缺陷 | 正确做法 |
|---|---|---|
| `SyncComp.update()` | 无头服务端 `isLocal()` 恒 false ⇒ `isRemote()` 对每个玩家单位恒 true ⇒ 每帧 `interpolate()` 把坐标插值回出生点，**单位永不移动** | 在 `SyncComp.update()` 开头 `if(Vars.headless \|\| Vars.net.server()) return;`。**不要改 `isLocal()`** —— `NetServer.sync()` 用它跳过玩家，改全局会导致**一个快照都不发** |
| `Logic.update()` | 缺 `netServer.sync()` 调用 | 每帧调用（`!state.isPaused()` 内） |
| `BuilderComp.updateBuildLogic()` | `!within()` 分支**没有任何移动代码** ⇒ 只建 27 格内的东西 | 补上朝目标移动（`x += …`，步长与玩家一致） |

详见 `../LESSONS.md`。

---

## 8. 观战端

```powershell
$jdk  = 'C:\dsh\zulu17\zulu17.68.203-ca-jdk17.0.20.1-win_x64\bin\java.exe'
$jar  = 'C:\dsh\Mindustry-src\desktop\build\libs\Mindustry.jar'   # 自建，不是 vanilla
Start-Process $jdk -ArgumentList '-Xmx2G',
  '-Djava.net.preferIPv4Stack=true',        # 必带，否则 UDP 快照收不到
  '-Dmindustry.autoreconnect=true',          # 断线自动重连
  '-jar', $jar
```

**⚠ 不要用 `C:\dsh\_dl\mindustry-v160.5\Mindustry.jar`** —— 那是原版，启动会报
`Unknown revision '3' for entity type 'PlayerComp'` 直接崩。
