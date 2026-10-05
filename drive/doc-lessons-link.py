#!/usr/bin/env python3
"""把 LESSONS.md 挂进文档索引，并从 TODO 与 DEVELOPING 指过去。"""
import pathlib
import sys

R = pathlib.Path(r"C:\dsh\ai-arena\docs\README.md")
T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")
D = pathlib.Path(r"C:\dsh\ai-arena\docs\DEVELOPING.md")

# README 主文档表：插在 DEVELOPING 之后
R_ANCHOR = "| [ENGINE-NOTES.md](ENGINE-NOTES.md) |"
R_NEW = ("| [LESSONS.md](LESSONS.md) | **经验教训**：判定与核实的陷阱、验证脚本自身会怎么骗人、"
         "以及本项目特有的一批「都会再错一次」的事实（都带实例与出处） | 动手排查之前、写验证脚本之前 |\n"
         "| [ENGINE-NOTES.md](ENGINE-NOTES.md) |")

# TODO 开头指一句
T_ANCHOR = "**不列**：已完成的（见 git log）、明确不做的（见 [§六](#六明确不做的)）。"
T_NEW = (T_ANCHOR + "\n\n> **动手之前先读 [LESSONS.md](LESSONS.md)** —— 那里记着判定与验证的陷阱。"
         "这份 TODO 里最费时间的几次返工，都是没先读它造成的。")

# DEVELOPING 的「验证铁律」节里挂一句
D_ANCHOR = "## 溯源命名"


def main():
    r = R.read_text(encoding="utf-8")
    if "LESSONS.md" in r:
        print("  · docs/README.md 已收录")
    else:
        if r.count(R_ANCHOR) != 1:
            print(f"  !! README 锚点 {r.count(R_ANCHOR)} 次")
            return 1
        R.write_text(r.replace(R_ANCHOR, R_NEW, 1), encoding="utf-8")
        print("  ✓ docs/README.md 索引已加 LESSONS.md")

    t = T.read_text(encoding="utf-8")
    if "LESSONS.md" in t:
        print("  · TODO.md 已指向")
    elif t.count(T_ANCHOR) == 1:
        T.write_text(t.replace(T_ANCHOR, T_NEW, 1), encoding="utf-8")
        print("  ✓ TODO.md 开头已指向 LESSONS.md")
    else:
        print(f"  !! TODO 锚点 {t.count(T_ANCHOR)} 次")

    d = D.read_text(encoding="utf-8")
    if "LESSONS.md" in d:
        print("  · DEVELOPING.md 已指向")
    else:
        add = ("> **写验证脚本之前先读 [LESSONS.md](LESSONS.md) §二** —— "
               "验证脚本自身的错误会伪装成被测对象的错误，我为此得出过一次完全相反的结论。\n\n")
        D.write_text(add + d, encoding="utf-8")
        print("  ✓ DEVELOPING.md 开头已指向")
    return 0


if __name__ == "__main__":
    sys.exit(main())
