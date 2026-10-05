> **写验证脚本之前先读 [LESSONS.md](LESSONS.md) §二** —— 验证脚本自身的错误会伪装成被测对象的错误，我为此得出过一次完全相反的结论。

# 开发者上手

根 [README.md](../README.md) 面向「**用 AI 玩这个竞技场**」。这一份面向
「**改接口层本身**」—— 加端点、改协议、修引擎交互。

前提：Windows + JDK 17 + 已构建的 Mindustry 引擎 jar。路径见下面的编译一节。

---

## 一、代码结构

```
mod/src/aiarena/          服务器 Mod（改这里就要重新编译部署）
    AIArena.java          配置加载、agent 鉴权、限流、日志
    HttpApi.java          全部 HTTP 端点（4200 行，最大的一块）
    WsServer.java         WebSocket
    Operations.java       建造/拆除/单位指令的**入口**（Actor.place 等）
    Actor.java            底层世界操作：校验、队列、Config
    Commander.java        单位控制（order/move/stop/attack…）
    Snapshot.java         世界快照采集（给读端点用）
    StallWatch.java       停机判定、计划进度采样
    EventLog.java         事件环形缓冲
    Recorder.java         录像写入
    Intel.java            「确认核心数据」状态机
    VisionTracker.java    视野跟踪
    RateTracker.java      产率采样

observer/                 观察者客户端 Mod（图形回放，未完成）
skill/scripts/arena.py    Python 客户端库（AI 用它接接口）
replay/index.html         回放播放器（零依赖单文件，不碰游戏）
docs/                     全部文档，先读 README.md 那份索引
drive/                    开发期脚本（不是产品的一部分）
```

**分层的实际约束**：`HttpApi` 只负责解析参数、调 `Operations`/`Actor`、
序列化响应。**别在 `HttpApi` 里直接操作世界** —— 那会让校验和权限检查被绕过。

---

## 二、编译部署

没有 Gradle 任务，是**手动 javac + jar**：

```powershell
$jc  = 'C:\dsh\zulu17\...\bin\javac.exe'
$jar = 'C:\dsh\zulu17\...\bin\jar.exe'
$mj  = 'C:\dsh\Mindustry-src\desktop\build\libs\Mindustry.jar'
$r   = 'C:\dsh\ai-arena'

$src = @(Get-ChildItem "$r\mod\src\aiarena\*.java" | ForEach-Object { $_.FullName })
& $jc -encoding UTF-8 -cp $mj -d "$r\mod\classes" @src

$out = "$r\mod\ai-arena.jar"
& $jar cf $out -C "$r\mod" mod.hjson -C "$r\mod\classes" .
Copy-Item $out "$r\server-run\config\mods\ai-arena.jar" -Force
```

**`jar` 的条目数固定是 47**（1 个 `mod.hjson` + 46 个 class）。
数目变了说明有文件增删，值得看一眼是不是意外。

**改完必须重启服务器才生效** —— 服务器不热加载。

---

## 三、加一个端点

1. **在 `HttpApi.route()` 的 switch 里挂上** —— 所有端点都从那里分发，
   鉴权和限流已经在它之前做完了，别重复做。
2. **读端点**用 `respond(ex, 200, json)`；**写端点**用 `postToGame(ex, task)` ——
   后者把任务投到游戏主线程并等结果（超时 3000ms，超时返回 `504` + `1007`）。
3. **写操作走 `Operations`/`Actor`**，不要自己调 `InputHandler`。
4. **错误码**：`Json.error(code, msg)`。码表在 `API.md`，
   `statusFor()` 把码映射到 HTTP 状态码 —— 加了新码记得同步那里。
5. **视野过滤**：任何按坐标返回玩家的读端点都必须过滤。用现有的
   `safeVisibleTile(team, x, y)`，别自己判 `FogControl`。
6. **在 `API.md` 记上**，并看清它是否符合「信息可见性契约」。

---

## 四、验证方式

**铁律：不许用「等一会儿」当判据。** 一律等**状态**：

```python
# 对：等到条件成立，超时就是失败
arena.poll_until(lambda: T if cond() else None, timeout=120)

# 错：赌它建完了
time.sleep(10)
```

**交叉验证两个独立测量**。这个项目里所有可信结论都是这么来的：

| 结论 | 测量 A | 测量 B |
|---|---|---|
| 钻机输出格对不对 | 钻机报的 `sendsTo` | 带子报的 `acceptsFrom` |
| 视野半径是不是 61 | `/state.vision.maxRadius` | 实测能看到多远 |
| 施工时长公式对不对 | `/place.buildTime.seconds` | 从 `progressRate` 反推 |
| 增量重建对不对 | Map 覆盖+删除 | 集合差（`verify-player.js`） |

**验证脚本放 `drive/`**，它们不是产品的一部分，但别删 ——
下一个人复现你的结论要靠它们。

---

## 五、容易踩的坑

**坐标是多格方块的「中心」，不是左上角。** `/buildings`、`/place`、`/map`
一律用中心。引擎内部（`Edges.getEdges`、`getLinkedTiles`）才用左上角，
换算是 `block.sizeOffset`。**别手算 `-((size-1)/2)`** —— 2x2 时两者都是 0，
看着一样，3x3 以上才分道扬镳。

**`allowAction` 传 `null` player 会无条件放行。** 服务器侧的写操作没有真实玩家，
权限校验会失效。所以**可见性和权限必须自己在 `Actor` 层做**。

**建造单位不含移动代码。** `BuilderComp` 只管建造，移动由控制器负责。
而竞技场里单位被影子 AI 玩家持有（`controller = Player#NNN`），影子玩家从不发移动输入 ——
所以 `AIArena` 里把建造单位的 `buildRange` 放大到覆盖全图来绕开这点。

**多格方块的坐标中心对偶数尺寸是「左上那一格」。** `size=2` 时 `sizeOffset = 0`，
所以 2x2 的中心就是它左上角那格，不是几何中心。

**读端点读的是缓存快照。** `/buildings`、`/units`、`/state` 里的数据来自
`Snapshot.State`，可能滞后一帧。`snapshotFresh` 字段说明新鲜度。
需要绝对实时的值用 `/control?op=pos`（直接读引擎）。

**`pp.points.size` 是字段不是方法。** Arc 的 `Seq` 用 `.size`。

**改 `HttpApi` 时注意别把 javadoc 和方法的顺序弄反。** 编译错误信息会指向
诡异的位置。

---

## 六、相关文档

| 文档 | 什么时候读 |
|---|---|
| [API.md](API.md) | 改任何端点前 —— 特别是「信息可见性契约」与「并发与执行顺序」 |
| [ENGINE-NOTES.md](ENGINE-NOTES.md) | 要动引擎行为时（它记的全是实测出来的引擎细节） |
| [CONDITIONS.md](CONDITIONS.md) | 想知道「边界是怎么定的」和「出过什么事」 |
| [TODO.md](TODO.md) | 接手时 |
| [DESIGN.md](DESIGN.md) | 想知道为什么这么设计 |
| [STRESS-TEST.md](STRESS-TEST.md) | 改并发相关的东西前 |

---

## 溯源命名

**这是 AI 客户端侧的约定，服务端只负责把接口版本号写进录像。**

### bot 目录

```
模型@工具#编号
```

例：`claude@arena_ops#12`、`deepseek@acc4#03`。三段缺一不可 ——
换模型、换工具、换编号都会影响成绩，只写「claude」等于没写。

每个 bot 目录里放一份 `MANIFEST.json`：

```json
{"model": "claude-sonnet-4.5", "tool": "arena_ops",
 "number": 12, "sha256": "<脚本目录的哈希>", "apiVersion": "1.4"}
```

### 成绩表

成绩表必须带 `sha256` 与 `apiVersion` 两列：

- `sha256` —— 确认两批成绩跑的是同一份代码
- `apiVersion` —— 确认两件事：**接口没变**（变了字段语义就不可比），
  以及**记录里有什么字段**（老客户端跑出的成绩少了新字段的信息，
  与新版本的成绩不是同一批可比数据）

`apiVersion` 由 `GET /ping` 取（无鉴权），也写在录像的 `meta` 头里，
所以对不上的时候能直接查。

### 录像

`meta` 头带 `apiVersion`，与 `version`（录像格式版本）是两个东西：

| 字段 | 含义 | 谁改 |
|---|---|---|
| `version` | **录像格式**版本（现在是 2） | 改 JSONL 结构时 +1 |
| `apiVersion` | **接口**版本（现在是 1.4） | 改端点/字段时 +1 |

回放端只用 `version`；做成绩对比时才看 `apiVersion`。
