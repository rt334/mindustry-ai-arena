#!/usr/bin/env python3
"""第 0 档：P 系列文档的矛盾回写。

不是改错别字，是改「文档 A 说完成、文档 B 说没验证」这类会误导决策的冲突：

- P7 §6 把 P5/P6 打成完成，而 P5 §5 与 P7 §7 自己写了未完成内容
- P7 的端点总表标题写 18 个、表里列 20 条，实际路由里 33 个
- P1 §4.3 断言核心方块 validPlace()「一律 false」，漏了前言（§5.1 ② 已给出口）
- P2 §2 表把「已落地」当「已验证」，与该文 §6 打架
- P3 §3.2 的 9 类监听表漏了 §6 提到的两类
"""
import pathlib
import sys

D = pathlib.Path(r"C:\dsh\ai-arena\docs\phases")

EDITS = {
    "P1-IMPLEMENTATION.md": [
        ("""isHidden()=true → isVisible()=false → isPlaceable()=false → validPlace() 一律 false
```

**核心只能建在地图的 spawn 点附近。** 竞品方案：setup 作为管理员操作，直接检查「size×size 全为空地」后用 `tile.setBlock()` 放置，绕过 `validPlace`。""",
         """isHidden()=true → isVisible()=false → isPlaceable()=false → validPlace() 失败
```

**「一律」有前提，这里早期漏写了。** §5.1 ② 找到了正规出口：
`isHidden()` 的定义是 `!buildVisibility.visible() && !state.rules.revealedBlocks.contains(this)`
（P1 §5.1 引的源码），所以把核心加进 `rules.revealedBlocks` 就能让 `isHidden()` 变回 false；
有 `core-zone` 地板的图上 `buildVisibility.visible()` 本来也为真，`validPlace` 正常放行。
§5.2 的自建核心路径（`findCoreSpot + layCoreZone + validPlace`）已在 P7 §3 实测成功。

**结论**：这一条只在「既无 core-zone 地板、也没配 `revealedBlocks`」时成立 ——
那种情况下核心确实无处可放。竞品方案（直接 `tile.setBlock()` 绕过 `validPlace`）不是必需的。"""),
    ],

    "P2-IMPLEMENTATION.md": [
        ("""## 2. 11 条对等约束的落地状态

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
| 11 | 逻辑处理器 | 已核查无法绕过视野（`Units.bestEnemy` 含 `inFogTo`） | ✅ P0 已核查 |""",
         """## 2. 11 条对等约束的落地状态

**表里的 ✅ 是「代码落地」，不是「已端到端验证」** —— 两者的差距见本文 §6，
以及 [DESIGN.md](../DESIGN.md) 第 10 节。别把这张表当验收结论。

| # | 约束 | 实现方式 | 状态 |
|---|---|---|---|
| 1 | 实体可见性 | `FogControl` 复用引擎判定 | ✅ P1 已完成 |
| 2 | 地形可见性 | 同上 | ✅ P1 已完成 |
| 3 | 听觉 | 无需处理（声学半径 20.2 格 < 最小视野 25 格） | ✅ 已论证 |
| 4 | 核心库存 | 刻意偏离，走「确认核心数据」 | ⚠️ **代码已落地，状态机未端到端验证**（见 §6） |
| 5 | 建造位置与速度 | `BuilderComp` 自动 | ✅ P1 已验证 |
| 6 | **指挥范围** | **自行实现** | ✅ **本次实现并实测** |
| 7 | 建造范围 | 引擎自动（`finalPlaceDst`） | ✅ 引擎行为 |
| 8 | 资源 | 建造路径由引擎 `hasAll` 把关；**`/spawn` 路径引擎没有任何成本判断**，且刻意不做（见 [P4](P4-IMPLEMENTATION.md) §4） | ✅ 建造路径 / ⚠️ spawn 路径不适用 |
| 9 | 移动速度 | 引擎自动 | ✅ 引擎行为 |
| 10 | 攻击 | 引擎自动 | ✅ 引擎行为 |
| 11 | 逻辑处理器 | 已核查无法绕过视野（`Units.bestEnemy` 含 `inFogTo`） | ✅ 已核查（**本次会话的源码核对，不是 P0 的验证项**） |"""),
    ],

    "P3-IMPLEMENTATION.md": [
        ("""**引擎监听**（9 类）：

| 事件 | 字段 |
|---|---|
| `UnitCreateEvent` | unit, type, health |
| `UnitDestroyEvent` | unit, type |
| `BlockBuildEndEvent` | x, y, block, byUnit, breaking |
| `BlockDestroyEvent` | x, y, block |
| `ConfigEvent` | block, value |
| `CoreChangeEvent` | block（并清空该队 intel） |
| `WaveEvent` | wave |
| `GameOverEvent` | winner |
| `WorldLoadEvent` | 触发 `clear()` |""",
         """**引擎监听**（11 类）：

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
> 不能缓存事件引用。早期这张表只写了 9 类，漏了它们。"""),
    ],

    "P7-IMPLEMENTATION.md": [
        ("至此 P0–P7 全部完成：", "至此 P0–P7 **服务器侧**全部完成（客户端两项另计，见下表状态列）："),
        ("""| P5 | 观战与裁判（view + 客户端 Mod） | `P5-IMPLEMENTATION.md` |
| P6 | 录像（JSONL Recorder） | 见本文件第 7 节 |""",
         """| P5 | 观战与裁判（view + 客户端 Mod） | `P5-IMPLEMENTATION.md` —— 服务器侧实测；**客户端 Mod 只做了编译 + 结构核对，图形未实测** |
| P6 | 录像（JSONL Recorder） | 见本文件第 7 节 —— 服务器侧就绪；**客户端图形回放未实现** |"""),
        ("""```
C:\\dsh\\ai-arena\\
  ../DESIGN.md               设计文档（含 9 项引擎发现）
  P0-VERIFICATION.md         P0 报告
  P1-IMPLEMENTATION.md       P1 报告
  P2-IMPLEMENTATION.md       P2 报告
  P3-IMPLEMENTATION.md       P3 报告
  P4-IMPLEMENTATION.md       P4 报告
  P5-IMPLEMENTATION.md       P5 报告
  P7-IMPLEMENTATION.md       本文件（含 P6 摘要）

  start-arena.ps1            编排脚本

  mod\\                       服务器 Mod（18 个端点）""",
         """```
C:\\dsh\\ai-arena\\
  README.md                  项目入口
  start-arena.ps1            编排脚本

  docs\\                      项目文档
    README.md                文档索引
    DESIGN.md                设计文档（含全部引擎发现）
    API.md                   接口手册
    ENGINE-NOTES.md          引擎层说明（维护者文档）
    FEASIBILITY.md           目标可行性
    STRESS-TEST.md           压力测试报告
    PROMPTS.md               提示词约定
    phases\\                  P0~P7 分阶段报告
      P0-VERIFICATION.md     P0 报告
      P1-IMPLEMENTATION.md   P1 报告
      P2-IMPLEMENTATION.md   P2 报告
      P3-IMPLEMENTATION.md   P3 报告
      P4-IMPLEMENTATION.md   P4 报告
      P5-IMPLEMENTATION.md   P5 报告
      P7-IMPLEMENTATION.md   本文件（含 P6 摘要）
    reviews\\                 产线攻坚复盘
      REPORT.md  DEBUG-LOG.md  FEATURE-REQUESTS.md  REVIEW-ADDENDUM.md

  mod\\                       服务器 Mod（33 个端点）"""),
        ("""### 端点总表（18 个）

```
GET  /ping                                  存活探测（无鉴权）
GET  /state                                 局面快照
GET  /units  /buildings                     视野内的实体
GET  /map?x=&y=&w=&h=  /  ?cursor=          区域 / 全图分页
GET  /content                               方块/物品/单位/液体/指令/姿态目录
GET  /intel                                 核心数据情报
GET  /events?since=                          事件流
GET  /observe                               观战信息
GET  /queue                                 建造队列
POST /place  /break                         单点 + 批量形状
POST /config  /spawn  /chat                 配置 / 生成 / 发言
POST /command?action=                       8 种指挥操作
POST /control?op=                           接管单位与直接操纵
GET  /setup  /maps  /record  (仅裁判)        初始化 / 地图列表 / 录像
```""",
         """### 端点总表（33 个）

> 早期版本这里标题写「18 个」而表里列了 20 条。以 `HttpApi.java` 的路由 `switch` 为准，
> 实际是 33 个。逐条参数见 [API.md](../API.md)。

```
读（GET，Bearer token）
GET  /state                                 局面快照
GET  /units  /buildings  /block             实体、单格
GET  /map?x=&y=&w=&h=  /  ?cursor=          区域 / 全图分页
GET  /ore                                   矿脉统计
GET  /content                               方块/物品/单位/液体/指令/姿态目录
GET  /rates?window=                         产率
GET  /stalls                                产线异常警报
GET  /drill  /factory                       矿机 / 单位工厂明细
GET  /intel                                 核心数据情报
GET  /events?since=                         事件流
GET  /observe                               观战信息
GET  /queue                                 建造队列
GET  /database                              汇总数据库
GET  /maps                                  地图列表

写（POST）
POST /place  /break                         单点 + 批量形状
POST /config                                设置方块配置
POST /mine                                  指定挖掘
POST /command?action=                       8 种指挥操作
POST /control?op=                           接管单位与直接操纵
POST /spawn                                 生成单位（**默认禁用**，见 API.md）
POST /chat                                  发言

裁判（admin = true）
GET  /diag                                  服务端诊断
GET+POST /observe  /record  /fog            视角 / 录像 / 迷雾
POST /setup  /host  /start                  初始化 / 开游戏端口 / 解除暂停
POST /admin                                 在线玩家管理

无鉴权
GET  /ping                                  存活探测
```""",
        ),
    ],
}


def main():
    bad = []
    for rel, rules in EDITS.items():
        p = D / rel
        if not p.exists():
            bad.append(f"{rel}: 文件不存在")
            continue
        text = p.read_text(encoding="utf-8")
        print(f"  {rel}")
        for old, new in rules:
            n = text.count(old)
            label = old.splitlines()[0][:52]
            if n != 1:
                bad.append(f"{rel}: {n} 次命中 -> {label}")
                print(f"      !! {n} 次  {label}")
                continue
            text = text.replace(old, new)
            print(f"      ok      {label}")
        p.write_text(text, encoding="utf-8")
    print()
    if bad:
        print("有问题：")
        for b in bad:
            print("  " + b)
        return 1
    print("P 系列回写完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
