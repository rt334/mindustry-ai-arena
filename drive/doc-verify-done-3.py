#!/usr/bin/env python3
"""§八 表格里那两行改成已验。"""
import pathlib
import sys

T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")

RULES = [
    ("| 蓝图导入/导出 | **实机验过（部分）** | 导出 2 个方块、base64 180 字符、JSON 可解析；**导入那次 `placed:0`** —— 见下 |",
     "| 蓝图导入/导出 | **实机验过** | 导出 count=4；导到确认过的空地 **placed 4/4**，3 条带子 + 1 个 router 以正确的相对位置与方块名重建（`verify-blueprint-roundtrip.py`） |"),
    ("| 写队列每 tick 预算 | 只编译过 | 要造并发负载才有意义，见下 |",
     "| 写队列每 tick 预算 | **实机验过** | 24 线程 × 8s 并发写，放宽限流后触发 47 次 `(504, 1007) write queue budget exhausted for tick N`，消息与设计一致（`verify-write-budget.py`） |"),
    ("**结账：已实机验证。** `python drive/verify-all.py` 一次跑完，12 项全过。",
     "**结账：已实机验证。** `python drive/verify-all.py` 一次跑完 12 项全过，\n另有 `verify-blueprint-roundtrip.py` 与 `verify-write-budget.py` 补上余下两项。**八项全部验过。**"),
]


def main():
    t = T.read_text(encoding="utf-8")
    ok = True
    for old, new in RULES:
        n = t.count(old)
        if n != 1:
            print(f"  !! 锚点 {n} 次：{old[:56]}…")
            ok = False
            continue
        t = t.replace(old, new, 1)
        print(f"  ✓ {old[:44]}…")
    if not ok:
        print("未写盘")
        return 1
    T.write_text(t, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
