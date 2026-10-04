# AI 竞技场 · P3 实现报告

> 对应 `../DESIGN.md` 第 9 节 P3。目标：AI 拥有完整的「眼睛」。
>
> **结论：信息 API 完整，事件流可用且遵守视野约束。**

---

## 1. 交付物

```
C:\dsh\ai-arena\mod\src\aiarena\
  EventLog.java     事件流（环形缓冲 + 引擎监听 + diff 补齐）
  Snapshot.java     实体快照补全字段 + 差分逻辑
  HttpApi.java      /events 端点 + /map 分页 + 字段补全
```

---

## 2. 字段补全

### 2.1 `/units`

新增三个字段：

```json
{"id":209,"type":"poly","team":1,"x":468.42,"y":812.26,
 "health":400.0,"maxHealth":400.0,"rotation":0.0,"canBuild":true,
 "stack":{},                    ← 携带物（item → 数量）
 "command":"rebuild",           ← 当前指令
 "controller":-1}               ← 被控制的玩家 id，AI 控制时为 -1
```

`command` 取自 `CommandAI.command.name`，让 AI 能确认指令是否生效。

### 2.2 `/buildings`

新增五个字段：

```json
{"x":61,"y":104,"team":1,"block":"core-nucleus",
 "health":4000.0,"maxHealth":6000.0,"enabled":true,"efficiency":1.0,
 "items":{"copper":2000,"lead":2000,"metaglass":2000,"graphite":2000,
          "titanium":2000,"thorium":2000,"silicon":2000,"plastanium":2000,
          "phase-fabric":2000,"surge-alloy":2000},     ← 库存
 "liquids":{},                                          ← 液体
 "config":"...",                                        ← 配置值（有才出现）
 "constructing":true,"buildProgress":0.42}              ← 施工中（有才出现）
```

`constructing` / `buildProgress` 来自 `ConstructBuild` —— 这直接服务于「建造不是瞬时的」这条对等约束：AI 能看到方块正在施工中，而不是瞬间出现。

### 2.3 `/content`

```
blocks=250  items=20  units=56  liquids=10  commands=10  stances=8
```

`units` 给出 `health / flying / buildSpeed / fogRadius / speed / hitSize / itemCapacity`，
`liquids` 给出 `color / flammability / temperature`。

---

## 3. `/events` 事件流

### 3.1 协议

```
GET /v1/{agent}/events?since=<seq>&limit=<n>

响应：
{"ok":true,"data":{
  "since":0, "nextSince":5, "count":5, "buffered":5,
  "events":[{"seq":1,"tick":193,"type":"configure","team":1,
             "x":488.0,"y":832.0,"detail":{"block":"core-nucleus","value":"2"}}]
}}
```

- 首次调用传 `since=0`
- 后续用 `nextSince` 续传
- 游标被环形缓冲淘汰时返回 `410 code:1006 cursor_expired`，调用方重置 `since=0`

### 3.2 事件来源：引擎监听 + 差分补齐

**引擎监听**（11 类）：

| 事件 | 字段 |
|---|---|
| `UnitCreateEvent` | unit, type, health |
| `UnitDestroyEvent` | unit, type |
| `BlockBuildEndEvent` | x, y, block, byUnit, breaking |
| `BlockDestroyEvent` | x, y, block |
| `TileChangeEvent` | x, y, block |
| `BuildDamageEvent` | x, y, health |
| `ConfigEvent` | block, value |
| `CoreChangeEvent` | block（并清空该队 intel） |
| `WaveEvent` | wave |
| `GameOverEvent` | winner |
| `WorldLoadEvent` | 触发 `clear()` |

> 后两类是本文 §6 补记的：**它们的实例会被引擎复用**，监听器里必须立刻把字段抄出来，
> 不能缓存事件引用。早期这张表只写了 9 类，漏了它们。

**差分补齐**（4 类）：`unitAppear` / `unitGone` / `buildAppear` / `buildGone`

#### ⚠ 为什么必须有差分补齐

`UnitCreateEvent` 全代码库只在 **5 处**触发：

```
UnitSpawnAbility.java:54   （单位技能召唤）
PayloadSource.java:144     （载荷释放）
Reconstructor.java:350     （单位升级）
UnitAssembler.java:570     （装配器）
UnitFactory.java:436       （工厂生产）
```

**核心生产单位和直接 `ut.create(t) + add()` 都不触发它。** 若只依赖引擎事件，AI 不会知道敌方出现了新单位 —— 这是「完整的眼睛」的实质缺口。

差分事件刻意用不同名字（`unitAppear` 而非 `unitCreate`），避免与引擎语义混淆：

```
seq=2 tick=197 blockPlace   team=1 {"x":58,"y":104,"block":"conveyor","byUnit":209}
seq=3 tick=199 buildAppear  team=1 {"x":58,"y":104,"block":"conveyor"}
```

### 3.3 视野约束

事件按观察方过滤 —— 玩家只能看到自己视野内发生的事，AI 也一样：

```java
private static boolean visible(Ev ev, Team viewer) {
    if (viewer == null) return true;                 // 裁判：全见
    if (ev.teamId == viewer.id) return true;         // 自己的事总是知道
    if (!Vars.state.rules.fog) return true;
    if (Float.isNaN(ev.x)) return false;             // 无位置且非己方 → 不透露
    return Vars.fogControl.isVisible(viewer, ev.x, ev.y);
}
```

### 3.4 线程模型

主线程写（事件监听器 + 差分），HTTP 线程读。固定容量 4096 的环形缓冲 + 一把锁 —— 事件产生频率低（每秒几条），锁竞争可忽略。

---

## 4. `/map` 分页协议

两种模式：

```
区域模式   /map?x=&y=&w=&h=       取指定矩形，w*h ≤ 4096
全图模式   /map                   从 (0,0) 开始按行扫描
           /map?cursor=<token>    续传
```

全图模式响应带 `cursor_next`，为 `null` 表示扫完：

```
/map                → mode=whole x=0 y=0 w=4096 h=1 world=350x200 tiles=350 cursor_next=0,1
/map?cursor=0,1     → x=0 y=1 tiles=350 cursor_next=0,2
/map?x=55&y=98&w=8&h=8 → mode=region tiles=64
```

游标就是可读的 `"x,y"`，便于人工调试。

**为什么要有全图模式**：`veins` 350×200 有 70000 格，远超单次上限 4096；而 AI 有时确实需要完整扫描（找资源点、统计地形）。全图模式让它用 200 次请求扫完，每次都是小响应。

---

## 5. 实测输出

```
/units     → {"id":209,"type":"poly","stack":{},"command":"rebuild","canBuild":true}
/buildings → {"block":"core-nucleus","items":{"copper":2000,...,"surge-alloy":2000},"liquids":{}}
/content   → blocks=250 items=20 units=56 liquids=10 commands=10 stances=8

/events    → nextSince=5 count=5 buffered=5
  seq=1 tick=193 configure    team=1 {"block":"core-nucleus","value":"2"}
  seq=2 tick=197 blockPlace   team=1 {"x":58,"y":104,"block":"conveyor","byUnit":209}
  seq=3 tick=199 buildAppear  team=1 {"x":58,"y":104,"block":"conveyor"}
  seq=4 tick=199 blockPlace   team=1 {"x":58,"y":105,"block":"conveyor","byUnit":209}
  seq=5 tick=205 buildAppear  team=1 {"x":58,"y":105,"block":"conveyor"}

/map       → mode=whole tiles=350 cursor_next=0,1
```

---

## 6. 对 `../DESIGN.md` 的修正

| 项 | 修正 |
|---|---|
| 6.1 `/map` | 分页协议落地：区域模式 + 全图模式 + `cursor_next` |
| 6.3 事件流 | 落地为轮询协议（非 SSE），含游标过期处理 |
| **新增** | **`UnitCreateEvent` 覆盖不全** —— 只在 5 处触发，核心生产单位不触发。必须用快照差分补齐 |
| **新增** | **`TileChangeEvent` / `BuildDamageEvent` 的实例是复用的** —— 监听器里必须立即抄出字段，不能缓存引用 |
