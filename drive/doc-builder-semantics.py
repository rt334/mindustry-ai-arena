#!/usr/bin/env python3
"""两件事一起记：
  1. builderTooFar 实测到了（§三 的 stuckReason 取值）
  2. YG 指出的：建造绑在玩家控制的单位上 —— 「多建造单位」的前提可能是错的
"""
import pathlib
import sys

T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")
F = pathlib.Path(r"C:\dsh\ai-arena\docs\API.md")

# ── 1. builderTooFar ──────────────────────────────────────────────────
T1_OLD = "| **60 计划上限的触发分支** | 实测峰值 `plans=49`，没撞到上限 |"
T1_NEW = ("| **60 计划上限的触发分支** | 实测峰值 `plans=49`，没撞到上限 |\n"
          "| **`stuckReason` 的 `builderTooFar`** | **已实测**。`drive/bootstrap.py` "
          "在一张新图上布线时，远端的计划全部卡在这个原因上，带具体数字：\n"
          "`(298,109) conveyor: builderTooFar: 232px away, buildRange 220`、"
          "`(294,128) mechanical-drill: builderTooFar: 325px away, buildRange 220`。"
          "**`buildRange = 220px = 27.5 格`** —— 这也直接回答了「建造单位射程是不是被放大过」："
          "**没有**，27.5 格是引擎的常规值（`widenBuilderRange` 已停用，见 AIArena.java 注释）。 |")

# ── 2. 多建造单位的前提 ───────────────────────────────────────────────
T2_OLD = "| 多建造单位 |"
T2_NEW_MARK = "| **多建造单位（前提待澄清）** |"

T2_NEW = ("| **多建造单位（前提待澄清）** | **YG 指出：建造是绑定在「玩家控制的单位」上的，"
          "所以多几个建造单位也只能一次建一个方块。** 这与代码对得上 —— `/place` 的响应里带 "
          "`\"builder\": {\"id\": 219, ...}`，计划是分配给**某一个**单位的，不是分配给队伍。"
          "所以「多建造单位」这个待办**前提可能是错的**：真正的问题不是「有没有第二个单位」，"
          "而是「计划能不能分派给不同的单位、让它们并行建」。"
          "**在改接口之前先把这条问清楚**，否则会去实现一个没有收益的功能。 |")

# ── 3. API.md 补一句 builder 语义 ─────────────────────────────────────
F_ANCHOR = "## 增量查询：不要重拉全量建筑"
F_SECTION = """## 建造是**单位**的属性，不是队伍的属性

`/place` 的响应里带 `"builder": {"id": 219, "type": "gamma"}` ——
**计划是分配给某一个单位的，不是分配给队伍的**。

这解释了几件事：

- **多几个建造单位不等于并行建造。** 建造进度挂在具体单位的 `BuilderComp` 上，
  一个单位一次只推进一个方块。想让 N 个单位同时建，得让计划**分派到不同单位**
  （`/place?unit=<id>` 可以指定）—— 而当前默认的分派策略会把它们都塞给同一个。
- **`builderTooFar` 是对「那个」单位算的。** 报错里的 `buildRange 220` 是像素，
  = **27.5 格**。距离是「被分派的那台」到工地的距离，不是「最近的一台」。
  所以把第二个单位派过去并不能解开这条 —— 要解就得让计划改派给近的那个。
- **建造单位的射程没有被放大。** 27.5 格是引擎常规值。

"""
NEW_T2 = """> 上面这几条合起来意味着：**优化建造吞吐的正确方向是「分派策略」，
> 而不是「造更多单位」**。造更多单位但不改分派，只是多几台闲着的机器。

## 增量查询：不要重拉全量建筑"""


def main():
    t = T.read_text(encoding="utf-8")
    ok = True
    if t.count(T1_OLD) == 1:
        t = t.replace(T1_OLD, T1_NEW, 1)
        print("  ✓ §三 记录 builderTooFar 已实测")
    else:
        print(f"  !! T1 锚点 {t.count(T1_OLD)}")
        ok = False

    if T2_OLD in t and T2_NEW_MARK not in t:
        i = t.find("| 多建造单位 |")
        j = t.find("\n", i)
        t = t[:i] + T2_NEW + t[j:]
        print("  ✓ §三 多建造单位 已改（前提待澄清）")
    else:
        print("  · 多建造单位 行已处理或找不到")

    if ok:
        T.write_text(t, encoding="utf-8")

    f = F.read_text(encoding="utf-8")
    if "建造是**单位**的属性" in f:
        print("  · API.md 已有该节")
    else:
        f = f.replace(F_ANCHOR, F_SECTION + NEW_T2, 1)
        F.write_text(f, encoding="utf-8")
        print("  ✓ API.md 追加「建造是单位的属性」")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
