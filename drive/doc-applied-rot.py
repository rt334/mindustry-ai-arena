#!/usr/bin/env python3
"""回填条目 2 的状态，并把两项新改动记进 §八 的验证债账。"""
import pathlib
import sys

T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")

OLD2 = "| 2 | 钻机往哪几格推货查不到 | **部分已实现**：`Snapshot.java:501` `if (sendsTo == null) sendsTo = drillOutputs(b)`，钻机输出格已塞进 `sendsTo`。仍缺的是「实际生效的 rot」与 footprint 锚点差异的解释。 |"
NEW2 = ("| 2 | 钻机往哪几格推货查不到 | **已做完**。输出格：`Snapshot.java:501` `sendsTo = drillOutputs(b)`。"
        "锚点差异：`Actor.place` 的返回体现在带 `appliedRot` / `anchorX` / `anchorY` / `size` —— "
        "多格方块在引擎里按**左上角**定位而接口给**中心**（`sizeOffset = -((size-1)/2)`），"
        "与其让每个 AI 自己推这个偏移，不如把换回来的结果直接给出。**未运行时验证。** |")

LEDGER_OLD = "| 蓝图导入/导出 | 只编译过 | 缺：导出一段真实产线再导回去；特别是「多格方块只记锚点」只做了静态推理 |"
LEDGER_NEW = ("| 蓝图导入/导出 | 只编译过 | 缺：导出一段真实产线再导回去；特别是「多格方块只记锚点」只做了静态推理 |\n"
              "| `/place` 的 `appliedRot` / `anchorX` / `anchorY` / `size` | 只编译过 | "
              "缺：放一个 2x2 与一个 1x1，核对 `anchorX/Y` 是否算对（纯增字段，不改行为，风险低） |")


def main():
    t = T.read_text(encoding="utf-8")
    ok = True
    for old, new, label in (
        (OLD2, NEW2, "§7.8 条目 2 → 已做完"),
        (LEDGER_OLD, LEDGER_NEW, "§八 记账"),
    ):
        n = t.count(old)
        if n != 1:
            print(f"  !! {label} 锚点 {n} 次")
            ok = False
            continue
        t = t.replace(old, new, 1)
        print(f"  ✓ {label}")
    if not ok:
        print("未写盘")
        return 1
    T.write_text(t, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
