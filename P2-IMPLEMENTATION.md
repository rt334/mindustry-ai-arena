# AI 竞技场 · P2 实现报告

> 对应 `DESIGN.md` 第 9 节 P2。目标：11 条对等约束逐条落地。
>
> **结论：约束全部落地，其中唯一需要自行实现的「指挥范围」已实测生效。**

---

## 1. 交付物

```
C:\dsh\ai-arena\mod\src\aiarena\
  Shadow.java       影子 Player 池（让 allowAction 生效）
  Commander.java    指挥类操作 + 指挥范围约束
  Intel.java        「确认核心数据」状态机
  HttpApi.java      新增 6 个端点
  Snapshot.java     接入 Intel 的逐 tick 推进
```

---

## 2. 11 条对等约束的落地状态

| # | 约束 | 实现方式 | 状态 |
|---|---|---|---|
| 1 | 实体可见性 | `FogControl` 复用引擎判定 | ✅ P1 已完成 |
| 2 | 地形可见性 | 同上 | ✅ P1 已完成 |
| 3 | 听觉 | 无需处理（声学半径 20.2 格 < 最小视野 25 格） | ✅ 已论证 |
| 4 | 核心库存 | 刻意偏离，走「确认核心数据」 | ✅ 本次实现 |
| 5 | 建造位置与速度 | `BuilderComp` 自动 | ✅ P1 已验证 |
| 6 | **指挥范围** | **自行实现** | ✅ **本次实现并实测** |
| 7 | 建造范围 | 引擎自动（`finalPlaceDst`） | ✅ 引擎行为 |
| 8 | 资源 | 引擎自动（`hasAll`） | ✅ 引擎行为 |
| 9 | 移动速度 | 引擎自动 | ✅ 引擎行为 |
| 10 | 攻击 | 引擎自动 | ✅ 引擎行为 |
| 11 | 逻辑处理器 | 已核查无法绕过视野（`Units.bestEnemy` 含 `inFogTo`） | ✅ P0 已核查 |

**「指挥范围」是唯一必须自己写的一条** —— 引擎对指挥没有任何距离检查（`InputHandler.java:331` 只判定队伍归属）。

---

## 3. 新增端点

```
GET  /v1/{agent}/units                        单位列表（视野过滤）
GET  /v1/{agent}/buildings                    建筑列表（视野过滤）
GET  /v1/{agent}/content                      可建方块 / 物品 / 指令 / 姿态清单
GET  /v1/{agent}/intel                        核心数据情报
POST /v1/{agent}/command?action=...           指挥操作
POST /v1/{agent}/control?op=...               进入/退出单位与直接操纵
```

### 3.1 `/command` 的 8 种 action

| action | 参数 | 引擎调用 |
|---|---|---|
| `move` | `units=1,2&x=&y=` | `Call.commandUnits` |
| `attackUnit` | `units=1,2&target=<unitId>` | `Call.commandUnits` |
| `assistBuilding` | `units=1,2&x=&y=` | `Call.commandUnits` |
| `setCommand` | `units=1,2&cmd=mine` | `Call.setUnitCommand` |
| `setStance` | `units=1,2&stance=holdFire&enable=true` | `Call.setUnitStance` |
| `commandBuilding` | `buildings=1,2&x=&y=` | `Call.commandBuilding` |
| `requestItem` | `x=&y=&item=copper&amount=100` | `Call.requestItem` |
| `transferInventory` | `x=&y=` | `Call.transferInventory` |

### 3.2 `/control` 的 4 种 op

| op | 参数 | 说明 |
|---|---|---|
| `enter` | `unit=<id>` | 接管单位（对应玩家按 Ctrl） |
| `release` | — | 释放控制 |
| `move` | `x=&y=` | 被控单位向目标移动 |
| `fire` | `x=&y=&on=true` | 被控单位朝目标开火 |

### 3.3 实测输出

```
/units     → {"units":[{"id":209,"type":"poly","team":1,"x":467.59,"y":814.44,"canBuild":true}]}
/buildings → {"buildings":[{"x":61,"y":104,"team":1,"block":"core-nucleus","efficiency":1.0}]}
/content   → blocks=250  items=20
             unitCommands = move, repair, rebuild, assist, mine, enterPayload,
                            loadUnits, loadBlocks, unloadPayload, loopPayload
             unitStances  = stop, holdfire, pursuetarget, patrol, ram, boost,
                            holdposition, mineauto
/intel     → {"cores":[{"team":"crux","teamId":2,"state":"unknown"}],
              "confirmTicks":600,"toleranceTicks":30}
```

---

## 4. 指挥范围约束（4.6）

```java
// Commander.checkVisible —— 单位与目标都必须对己方可见
if(!Vars.state.rules.fog) return null;
if(!Vars.fogControl.isVisible(team, upx, upy))   return "unit ... is not visible";
if(checkTarget && !Vars.fogControl.isVisible(team, tpx, tpy)) return "target ... is not visible";
```

**实测**：

```
move 到视野内 (+4,+4)  → {"ok":true,"message":"commanded 1 unit(s) to position"}
move 到视野内 (+10,0)  → {"ok":true,...}
move 到视野外 (5,5)    → {"ok":false,"code":1005,
                          "error":"target at tile(5,5) is not visible to sharded"}
```

单位确实按指令移动了 —— 从 (468,814) 移到 (489,818)。

### ⚠ 坐标单位陷阱

`FogControl` 提供两个重载，参数单位不同：

```java
isVisibleTile(Team team, int x, int y)        // 格坐标
isVisible(Team team, float x, float y)        // 世界坐标（像素）
```

`Commander` 早期版本把 HTTP 传来的格坐标直接喂给 `isVisible`，导致**相邻 8 格的目标也被判定为不可见**。全部 13 处调用点已改为显式换算：

```java
private static float px(float tile) { return tile * Vars.tilesize; }
```

---

## 5. 影子 Player（4.7）

```java
// Shadow.java
public static Player of(Team team)              // 取得或创建
public static Player at(Team team, float x, float y)   // 并设定位置
public static void clear()                      // 换图时清理
```

**为什么必需**：

```java
// Administration.java:173-175
public boolean allowAction(Player player, ActionType type, Cons<PlayerAction> setter){
    //some actions are done by the server (null player) and thus are always allowed
    if(player == null) return true;          // ← 传 null 直接跳过全部校验
    ...
}
```

传 `null` 会放弃权限校验，传影子 Player 则校验生效 —— AI 与将来的真人玩家走同一套规则。

**位置的作用**：引擎自带的距离检查依赖它，例如 `InputHandler.requestItem` 里的 `player.within(build, itemTransferRange)`（`itemTransferRange = 220f` ≈ 27.5 格）。因此 `Shadow.at()` 在调用这类方法前必须先把影子挪到操作点。

**P0 实测结论仍然成立**：影子会进入 `Groups.player`，但 `team().data().players.size` 保持 0，不污染胜负判定。

---

## 6. `/intel` 状态机（6.2）

```
unknown ──[连续可见 600 tick]──→ confirmed
                                   └─ 保存快照 {items, tick}，永久保留
                                      再次达成阈值 → 追加（保留历史）
```

| 参数 | 值 | 理由 |
|---|---|---|
| 确认时长 | 600 tick（10 秒） | 接近「一次成功的穿插」，而非「驻扎」 |
| 抖动容错 | 30 tick（0.5 秒） | 视野边缘每 tick 重算会出现瞬时丢失，一次丢失就清零会让机制几乎无法完成 |
| 加速 | 无 | 多单位不加速 |
| 己方核心 | 全知 | 不走确认流程 |

**「察觉」不需要额外机制** —— 防守方能看见敌方单位，这就是察觉。加「你正在被侦察」的提示反而是额外免费情报，违背对等原则。

**保留历史快照而非覆盖** —— 两次读数的差额直接给出对方在此期间的经济增长。

**边界情况已处理**：核心被摧毁 → `clearTeam()`；核心易主 → `resetPair()`；多 AI 侦察同一核心 → 各自独立（key 是 `(观察方队伍, 目标队伍)`）。

**待实际对局验证**：状态机的完整推进需要真实侦察过程（把单位派到敌方核心旁持续 10 秒）。`veins` 上两个核心相距 228 格，远超视野半径，因此初始状态必然全是 `unknown` —— 这与实测一致。

---

## 7. 编译期踩到的三个 API 细节

**① `UnitCommand` / `UnitStance` 没有 `all` 数组**

它们是 `MappableContent`，只暴露静态字段，而且这些字段由 `init()` 赋值 —— 必须在运行时读取，不能缓存到静态初始化块：

```java
private static UnitCommand[] allCommands() {
    return new UnitCommand[]{
        UnitCommand.moveCommand, UnitCommand.repairCommand, UnitCommand.rebuildCommand,
        UnitCommand.assistCommand, UnitCommand.mineCommand, UnitCommand.enterPayloadCommand,
        UnitCommand.loadUnitsCommand, UnitCommand.loadBlocksCommand,
        UnitCommand.unloadPayloadCommand, UnitCommand.loopPayloadCommand,
    };
}
```

**② `World.toTile(float)` 需要 `mindustry.core.World`**

**③ PowerShell 的 `Set-Content -Encoding UTF8` 会写入 BOM**

带 BOM 的 `.java` 文件会让 `javac` 在第一行就解析失败。改用：

```powershell
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($path, $text, $utf8NoBom)
```

---

## 8. 对 DESIGN.md 的修正

| 项 | 修正 |
|---|---|
| 4.6 指挥范围 | 已实现并实测，附坐标单位陷阱说明 |
| 4.7 影子 Player | 已实现为池化管理，附位置语义说明 |
| 6.2 `/intel` | 已实现，状态机与参数按设计落地 |
| **新增** | **`FogControl` 两个重载的坐标单位不同** —— 混用会导致视野判定错误 |
| **新增** | **`UnitCommand` / `UnitStance` 的静态字段由 `init()` 赋值**，不能在静态块缓存 |
