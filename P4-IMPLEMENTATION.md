# AI 竞技场 · P4 实现报告

> 对应 `DESIGN.md` 第 9 节 P4。目标：AI 拥有完整的「手」。
>
> **结论：操作 API 完整，批量建造端到端实测通过（40 个方块全部落地）。**

---

## 1. 交付物

```
C:\dsh\ai-arena\mod\src\aiarena\
  Operations.java   形状生成 + 批量建造/拆除 + spawn + chat + 队列管理
  HttpApi.java      /place /break 扩展形状；新增 /spawn /chat /queue
```

---

## 2. 端点

```
POST /place?x=&y=&block=&rot=&config=                       单点
POST /place?shape=line&x1=&y1=&x2=&y2=&block=               直线（Bresenham）
POST /place?shape=area&x1=&y1=&x2=&y2=&block=               实心矩形
POST /place?shape=outline&x1=&y1=&x2=&y2=&block=            矩形边框
POST /place?shape=circle&x=&y=&radius=&block=               实心圆
POST /place?shape=rect&...                                  与 area 同义
POST /place?shape=point&x=&y=&block=                        与单点同义

POST /break?...                                             参数同上，无需 block

POST /spawn?type=<unitType>&x=&y=                           生成单位（缺坐标时用核心位置）
POST /chat?text=...                                         发送消息
GET  /queue                                                 查看建造队列
POST /queue?clear=true                                      清空建造队列
```

---

## 3. 批量不是「直接改一片世界」

设计约束（DESIGN.md P4）写明「全部操作都要过 P2 的校验链，没有旁路」。因此批量建造的实现是：

```java
for (Point2 p : points) {
    Actor.Result one = Actor.place(team, p.x, p.y, blockName, rotation, config);
    // 逐格走：可见性 → 建造单位 → addBuild
}
```

每一格都完整走一遍校验，由引擎的 `BuilderComp` 决定哪些真的能建。返回值如实报告跳过原因：

```json
{"ok":true,"data":{
  "message":"batch requested=16 accepted=16 skipped[invisible=0,invalid=0,noUnit=0]",
  "shape":"outline","tiles":16}}
```

### 两个硬性上限

| 限制 | 值 | 理由 |
|---|---|---|
| 单次批量格数 | 200 | 超过直接拒绝（`code:1004`），而不是静默截断 —— 让 AI 能感知指令未被完全接受 |
| 单单位计划队列 | 60 | 建造单位的 `plans` 队列有实际容量，超出会挤掉之前的计划 |

达到队列上限时提前停止并在 message 里说明：

```
"plan queue limit reached at 60 plans"
```

---

## 4. 生成单位的真实约束

`CoreBlock.requestSpawn` 的实现（CoreBlock.java:585）：

```java
public void requestSpawn(Player player){
    //do not try to respawn in unsupported environments at all
    if(!unitType.supportsEnv(state.rules.env) || !allowSpawn) return;
    Call.playerSpawn(tile, player);
}
```

**引擎里从核心生成单位不消耗资源** —— 没有成本判断。单位成本只体现在工厂生产路径（`UnitFactory`）上。

因此 `Operations.spawn` 的约束是：

| # | 约束 | 来源 |
|---|---|---|
| 1 | 目标位置对己方可见 | 对等约束（P2） |
| 2 | `unitType.supportsEnv(rules.env)` | 引擎 `requestSpawn` |
| 3 | `unitCount < unitCap` | 引擎 `TeamData` |
| 4 | 地面单位需要可站立的格子 | 引擎 |

**刻意不做资源检查** —— 否则 AI 的能力会低于玩家，反而破坏对等。

不走 `requestSpawn` 的原因：它需要 `Player` 参数并走 `Call.playerSpawn`，那是「玩家重生」语义（会绑定到该玩家），不适合 AI 生成普通单位。

---

## 5. 实测输出

```
单位在格 (58,102)

1) line 直线 5 格      → {"ok":true,"message":"batch requested=5 accepted=5 ..."}
2) area 3x3 区域       → {"ok":true,"message":"batch requested=9 accepted=9 ..."}
3) circle 半径 2       → {"ok":true,"message":"batch requested=13 accepted=13 ..."}
4) outline 5x5 框      → {"ok":true,"message":"batch requested=16 accepted=16 ..."}
5) 900 格              → {"ok":false,"code":1004,"error":"batch too large: 900 tiles, max 200"}
6) spawn mono          → {"ok":true,"message":"spawned mono id=235 at tile(61,104) pop=2/24"}
7) spawn 未知类型      → {"ok":false,"code":1002,"error":"unknown unit type: nonsense"}
8) chat                → {"ok":true,"message":"sent: hello from alpha"}
9) queue 查看          → {"builders":[{"unit":209,"type":"poly","plans":22}]}
10) 未知 shape         → {"ok":false,"code":1001,
                          "error":"unknown shape: nonsense (point|line|rect|area|outline|circle)"}
11) queue 再看（12s后）→ {"builders":[{"unit":209,"plans":0},{"unit":293,"type":"gamma","plans":0}]}
12) queue 清空         → {"ok":true,"message":"cleared 0 pending plan(s)"}

/buildings 统计 → 41 个建筑
  core-nucleus x1
  conveyor     x40      ← 批量下令的方块全部落地
```

**端到端验证完成**：40 个 conveyor 从「HTTP 下令」→「引擎流水线」→「真实存在于世界」全程打通。

`pop=2/24` 说明人口约束生效（`mono` + `poly` + 核心自动生产的 `gamma`）。

---

## 6. 对 DESIGN.md 的修正

| 项 | 修正 |
|---|---|
| P4 交付 | 全部落地，含形状批量与队列管理 |
| **新增** | **引擎里从核心生成单位不消耗资源** —— `CoreBlock.requestSpawn` 只检查 `supportsEnv` 与 `allowSpawn`。若自行加资源检查，会让 AI 弱于玩家，破坏对等 |
| **新增** | **`UnitType` 没有 `requirements` / `unitCapModifier`** —— 前者只存在于 `UnitFactory`，后者是 `CoreBlock` 的字段 |
| **新增** | **`Call.sendMessage` 有三个重载**，参数分别是 `(String)` / `(String, String, Player)` / `(NetConnection, String, String, ...)` |
