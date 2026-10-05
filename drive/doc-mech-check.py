#!/usr/bin/env python3
"""条目 15 复核：三条机制我第 13 轮已写进 ENGINE-NOTES §二十九。

复盘列的三条：
  · 相邻发电机不会自动并网，必须补 power-node
  · 核心是终端，不向下游倒货
  · router 会被外来货物卡死，junction 不会

§二十九 里都写了，而且第一条按本轮实测做了更准的拆分
（发电机之间不互联 vs 发电机紧贴用电器能直供）。
"""
import pathlib
import sys

E = pathlib.Path(r"C:\dsh\ai-arena\docs\ENGINE-NOTES.md")
T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")

NEEDED = [
    "发电机 ↔ 发电机",          # 拆分后的第一条
    "核心是终端",               # 第二条
    "`router` 会被外来货物卡死",  # 第三条
]

TODO_OLD = ("| 15 | 几条游戏机制没写进文档 | **未做**。但其中「相邻发电机不会自动并网」要写准："
            "**发电机与发电机之间**不会自动互联，而**发电机紧贴用电器**是能直接供电的 —— "
            "实测过（`combustion-generator` 紧贴 `silicon-smelter`，`powerStatus=1.0`），"
            "不补 `power-node` 也成立。 |")

TODO_NEW = ("| 15 | 几条游戏机制没写进文档 | **已做**（第 13 轮）。`ENGINE-NOTES.md` §二十九 收了三条，"
            "第一条按实测做了更准的拆分：**发电机与发电机之间**不会自动互联（要 `power-node`），"
            "但**发电机紧贴用电器能直接供电** —— 实测 `combustion-generator` 紧贴 "
            "`silicon-smelter` 时 `powerStatus=1.0`，全程没放电力节点。"
            "另两条：核心是终端不向下游倒货（钻机贴核心会白送，实测被吃掉 198 煤）；"
            "`router` 会被外来货物卡死（`itemCapacity=1`），`junction` 不会。 |")


def main():
    e = E.read_text(encoding="utf-8")
    missing = [n for n in NEEDED if n not in e]
    if missing:
        print(f"  !! §二十九 缺这些：{missing}")
        return 1
    print(f"  ✓ ENGINE-NOTES §二十九 三条都在")

    t = T.read_text(encoding="utf-8")
    if t.count(TODO_OLD) != 1:
        print(f"  !! 条目15 锚点 {t.count(TODO_OLD)} 次")
        for ln in t.splitlines():
            if "几条游戏机制" in ln:
                print("   实际:", ln[:110])
        return 1
    T.write_text(t.replace(TODO_OLD, TODO_NEW, 1), encoding="utf-8")
    print("  ✓ §7.8 条目 15 改为已做")
    return 0


if __name__ == "__main__":
    sys.exit(main())
