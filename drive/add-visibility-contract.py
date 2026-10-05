#!/usr/bin/env python3
"""给 API.md 补「信息可见性契约」。

借鉴自 meow-ai-arena 的写法：它的 RULES.md 把缺省语义写死（「阵亡时 x、y 为 -1」），
全文没有一处模糊地带。我们这边相反 —— 红线只存在于判断里，文档里没有对应物，
既没法自检、也没法在被质疑时自证。

这一节把判据、正例、反例、缺省语义全部写死。
"""
import pathlib
import sys

P = pathlib.Path(r"C:\dsh\ai-arena\docs\API.md")

ANCHOR = """## 三、能获取的信息

### `GET /ping`"""

CONTRACT = """## 三、能获取的信息

> **本节所有字段都受一条契约约束，先读下面这节再看具体端点。**

### 信息可见性契约

**判据只有一条：一个真人玩家在同一队伍、同一状态下，用游戏 UI 能不能获取这条信息。**

能获取就给，不能获取就不给。**获取的难易不算数** —— 玩家放下一条带子看它往哪边流，
也算「能获取」，所以 `acceptsFrom` / `sendsTo` 是合规的。
界线落在**「看一眼就知道」**与**「要盯一段时间再算」**之间。

#### 给：屏幕上直接显示的

| 信息 | 对应玩家看到的什么 |
|---|---|
| `buildings[].items` / `liquids` | 选中自己的建筑，物品栏与液体栏直接列出来 |
| `buildings[].efficiency` | 选中建筑时的效率条 |
| `buildings[].powerStatus` / `powerLinks` | 电力条与激光连线 —— 断没断，一眼可见 |
| `buildings[].rotation` | 传送带流向、炮塔朝向、工厂出口，全画在屏幕上 |
| `buildings[].health` / `maxHealth` | 血条 |
| `buildings[].constructing` / `buildProgress` | 施工中的进度圈 |
| `buildings[].acceptsFrom` / `sendsTo` | 接口规则：放一条带子看它往哪流，玩家做一遍就知道 |
| `units[].*` 同理 | 血条、朝向、携带物；开火有枪口火光，弹道方向可见 |
| `stalls[]` 的 `kind` / `cause` | 带子完全不动、钻头不转、电力条空 —— 都是抬眼可见的现象 |
| `queue[].progress` | 建造进度条 |
| `queue[].etaSeconds` | 进度条在涨，盯着就能估出还要多久 |
| `intel` | 「确认核心数据」：连续看见敌方核心 10 秒，才放出库存快照 |
| `map[].visible` | 屏幕上那一块是不是亮的 |

#### 不给：需要观察 + 计算才能得出的

| 想要的东西 | 为什么不给 |
|---|---|
| 某条链的**吞吐上限**（如「1.2/s」） | 游戏从不显示速率数字。玩家要数物品、掐时间、自己除 |
| **瓶颈在哪一格** | 那是推导结果，不是显示结果 |
| **「这条链正在减速」** | 带子还在动，肉眼看不出来。`beltStall` 的判据是「完全不动」（`clogHeat` 逼近 1），不是「变慢了」 |
| **外推的产率预测** | `/rates` 给的是两个时间点的库存差 —— 玩家记两个数自己减也能得到，不外推 |
| **敌方建筑的 `items` / `liquids`** | 选中敌方建筑不显示库存。核心库存尤其：原版是无条件广播，本项目刻意改成「需确认」 |
| 敌方单位在雾里的**身份** | 看得到弹道往哪飞，看不到打的是谁（只给方向） |
| **视野内的全图矿脉** | 只能看 `map` 逐格查；不提供「附近有什么矿」的汇总 |

#### 缺省语义

**字段不出现，表示该信息当前不适用，不是「没查到」**：

| 字段 | 不出现的含义 |
|---|---|
| `buildings[].fogRadius` / `units[].fogRadius` | 该实体视野半径 ≤ 0（`gamma` 这类快速飞行单位就是 0，见 ENGINE-NOTES 第二十八节） |
| `units[].buildingAt` | 该单位没有待办计划 |
| `buildings[].acceptsFrom` / `sendsTo` | 该方块没有接货口 / 输出口的概念，或相邻格是空地 |
| `queue[].constructing` / `progress` | 该格还没开工（单位在赶路） |
| `queue[].stuckSeconds` / `hint` | 没有卡住 |
| `queue[].progressRate` / `etaSeconds` | 进度没在涨，推不出剩余时间 |
| `units[].targetX` | 没有交战目标 |
| `buildings[].config` | 该方块无配置 |

**别把「字段缺失」和「值为 0」混起来**：前者是不适用，后者是确确实实的零。
例如 `fogRadius` 不出现 ≠ 视野为 0 格，而是这个实体根本不贡献视野。

### `GET /ping`"""


def main():
    text = P.read_text(encoding="utf-8")
    n = text.count(ANCHOR)
    if n != 1:
        print(f"!! 锚点 {n} 次命中（应为 1），未写盘")
        return 1
    text = text.replace(ANCHOR, CONTRACT)

    # 顺手修重复的 /units 标题
    dup = "### `GET /units`\n\n### `GET /units`"
    if dup in text:
        text = text.replace(dup, "### `GET /units`", 1)
        print("  顺带修掉重复的 `### GET /units`")

    P.write_text(text, encoding="utf-8")
    print("API.md：已补「信息可见性契约」")
    return 0


if __name__ == "__main__":
    sys.exit(main())
