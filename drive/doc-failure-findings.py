#!/usr/bin/env python3
"""把失败码统计的实测结论补进报告，并把 rot 环绕写进 ENGINE-NOTES。"""
import pathlib
import sys

DOC = pathlib.Path(r"C:\dsh\ai-arena\docs\place-failure-stats.md")
E = pathlib.Path(r"C:\dsh\ai-arena\docs\ENGINE-NOTES.md")

FINDINGS = """

## 实测发现（不只数码，还要看「这个行为对不对」）

### 1. `rot` 越界被**静默环绕**，从不报错

用干净格子分别下单：

| 下单 `rot` | 回读 `rotation` | 环绕规则 |
|---|---|---|
| `9` | `1` | `9 mod 4 = 1` |
| `-1` | `3` | 负数取模绕回 |
| `4` | `0` | `4 mod 4 = 0` |
| `100` | `0` | `100 mod 4 = 0` |

**四种全部 `code=0` 成功。** `rot=4` 几乎肯定是调用方写错（比如当成 1-based），
却静默变成朝东 —— AI 以为放了个朝 4 的方块，实际朝东。
这与 `ENGINE-NOTES` 里那条「铺错朝向不会报错，只表现为产率为 0」是同一类陷阱，
但更隐蔽：这次连**越界的值**都不报。

**处置**：**不改行为**（拒绝越界会破坏现有能跑的客户端），
但 `/place` 的返回体**已经带 `appliedRot`**（第 25 轮加的），
所以「实际生效的朝向」现在可查 —— 调用方自己比对 `rot` 与 `appliedRot` 就能发现。
这条是 `appliedRot` 的第二个用途，第一个是解释 footprint 锚点差异。

### 2. 「材料不足」在下单时**不拒**，而是排队后卡住

`solar-panel`（要 8 硅、核心 0 硅）下单返回 `code=0`，计划进队。
失败要到之后再查：`/queue` 的 `planList` 里会出现
`stuckReason: missingMaterials`。

**这是设计如此**（`stuckReason` 就是为它做的），但**必须写清楚** ——
只看下单响应的 AI 会以为计划已成功，直到发现核心不进硅。
`hint` 字段会给出补救方向。

### 3. 同格重复放置是 `transfer` 而不是错误

对已有计划的格子再下单，返回 `mode: "transfer"` 与 `previousBlock`，
把那个建造单位的目标改成新方块。**不报 1008** —— 1008 只在
「该格已有**实体建筑**」时出现。

这两件事容易混：**「有别的计划」→ transfer（不报错）**、
**「有实体建筑」→ 1008（报错）**。

### 4. 这轮的统计口径与局限

- 每类只跑了 1–3 次，**是「各类有没有、报什么」，不是频率分布**
- 第一轮把「对照组」也跑成 1008，因为前一次崩溃的跑已经在那些格子放了方块 ——
  **测试自身留下的残留会把后续结论污染**（复盘条目 24 说的就是这件事）
- 要频率分布得在干净局面上跑成百上千次，且每次都用新格子

## 码表（本轮实际出现过的）

| code | 含义 | 本轮次数 |
|---|---|---|
| `0` | 成功（含材料不足与 rot 越界） | 2 |
| `1002` | 未知方块名 / 未知动作 | 1 |
| `1003` | 坐标越界 | 1 |
| `1005` | 不可见 / 不可用 | 1 |
| `1008` | footprint 被实体建筑占 | 3 |
"""

ROT_SECTION = """

## 三十、`rot` 越界会被**静默环绕**，不报错

实测（干净格子，四种越界值全部 `code=0` 成功）：

| 下单 `rot` | 回读 `rotation` |
|---|---|
| `9` | `1` |
| `-1` | `3` |
| `4` | `0` |
| `100` | `0` |

引擎按 `mod 4` 环绕。`rot=4` 几乎肯定是调用方写错（当成 1-based），
却静默变成朝东 —— 这比「铺错朝向」更隐蔽：连越界的值都不报。

**若你的朝向推理结果不对，先核对 `rot` 有没有越界。**
`/place` 的返回体带 `appliedRot`（实际生效值），拿它与自己传的 `rot` 比对即可发现。
"""


def main():
    d = DOC.read_text(encoding="utf-8")
    if "## 实测发现" not in d:
        # 去掉脚本自动生成的简陋码表，换成实测结论
        i = d.find("## 码表")
        if i > 0:
            d = d[:i].rstrip() + "\n"
        DOC.write_text(d + FINDINGS, encoding="utf-8")
        print("  ✓ 失败码报告补入实测发现")

    e = E.read_text(encoding="utf-8")
    if "## 三十、`rot` 越界会被" in e:
        print("  · ENGINE-NOTES 已有该节")
    else:
        E.write_text(e.rstrip() + "\n" + ROT_SECTION, encoding="utf-8")
        print("  ✓ ENGINE-NOTES 追加 §三十")
    return 0


if __name__ == "__main__":
    sys.exit(main())
