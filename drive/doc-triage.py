#!/usr/bin/env python3
"""给 §七 追加甄别结果：哪些条目其实已经做完了。"""
import pathlib
import sys

T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")

SECTION = """

### 7.8 甄别：§七 里哪些其实已经做完了

> 复盘文档记录的是**当时的**状态，写进 §七 时没逐条对照现在的代码。
> 以下是核对现状后的结论 —— 动工前先看这里，别重复劳动。

| # | 复盘的说法 | 现状 |
|---|---|---|
| 1 | `acceptsFrom` 没有任何实现 | **已实现**。`Snapshot.java:499` `acceptsFrom = conveyorInputs(b)`，`HttpApi` 用 `if (b.acceptsFrom != null) o.putRaw("acceptsFrom", ...)` 输出。核对时若抽样的第一个建筑是核心（非 conveyor），该字段本就是 null 故不输出，**别据此判定「没实现」** —— 要看带子。 |
| 2 | 钻机往哪几格推货查不到 | **部分已实现**：`Snapshot.java:501` `if (sendsTo == null) sendsTo = drillOutputs(b)`，钻机输出格已塞进 `sendsTo`。仍缺的是「实际生效的 rot」与 footprint 锚点差异的解释。 |
| 6 | `/map` 窗口上限 400 无任何文字 | **已修**。`HttpApi.java:339`：`region too large: <N> tiles, max 4096 — use /map?cursor= for whole-map scan`，实测能拿到完整文案。 |
| 13 | `ENGINE-NOTES.md` 的 `rot` 编码写反 | **已修**。改为 `1=南(+y) / 3=北(-y)` 并加了勘误说明。 |
| 14 | 矿机产出公式没进任何文档 | **部分**：已进 `PRODUCTION.md` §四，但没进 `ENGINE-NOTES.md`（引擎层事实该在的地方）。**待搬**。 |
| 15 | 几条游戏机制没写进文档 | **未做**。但其中「相邻发电机不会自动并网」要写准：**发电机与发电机之间**不会自动互联，而**发电机紧贴用电器**是能直接供电的 —— 实测过（`combustion-generator` 紧贴 `silicon-smelter`，`powerStatus=1.0`），不补 `power-node` 也成立。 |
| 16 | 「5/s 不可达」措辞该改 | **未做**。`PRODUCTION.md` 仍写着「矿脉密度的硬上限」，应改为「近处矿量 + 干线成本」的**工程约束**。**待改**。 |
| 18 | 一条该进 §六 明确不做的边界判定 | **未做**。见 §7.9。 |

### 7.9 补进 §六 的边界判定

按「暴露规则可以、暴露结论越线」的标准：

- **可以做**：「每台钻机实际在往哪几格推货」—— 这是**规则**，与 `acceptsFrom` / `sendsTo` 同级。
- **越线不做**：「哪些邻格属于其他资源的干线，给出告警」—— 这是**结论**。判断一条邻格带子属于谁、会不会混料，是 AI 该自己推的事；服务端替它推等于代打。
"""


def main():
    t = T.read_text(encoding="utf-8")
    if "### 7.8 甄别" in t:
        print("  已存在，跳过")
        return 0
    T.write_text(t.rstrip() + SECTION, encoding="utf-8")
    print("  已追加 §7.8 / §7.9")
    return 0


if __name__ == "__main__":
    sys.exit(main())
