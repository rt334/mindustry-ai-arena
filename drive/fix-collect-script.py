#!/usr/bin/env python3
"""修 collect-place-failures.py 写报告那步（dict() 用法错）。"""
import pathlib
import sys

P = pathlib.Path(r"C:\dsh\ai-arena\drive\collect-place-failures.py")

OLD = """    for code, n in sorted(by_code.items()):
        lines.append(f"| `{code}` | {dict((0, '成功'), (1001, '参数错'), (1002, '未知')
                                          ).get(code, '')} | {n} |")"""

NEW = """    for code, n in sorted(by_code.items()):
        lines.append("| `%d` | %s | %d |" % (code, NAMES.get(code, "?"), n))"""

NAMES_ANCHOR = "    # \u2500\u2500 \u5199\u62a5\u544a"
NAMES = """    NAMES = {0: "成功", 1001: "参数错", 1002: "未知方块/动作", 1003: "坐标越界",
             1004: "批量或上限", 1005: "不可见/不可用", 1007: "写队列预算",
             1008: "footprint 被占", 1009: "放置非法", 1429: "限流"}
    # \u2500\u2500 \u5199\u62a5\u544a"""


def main():
    t = P.read_text(encoding="utf-8")
    n = t.count(OLD)
    if n != 1:
        print(f"  !! OLD 锚点 {n} 次")
        return 1
    t = t.replace(OLD, NEW, 1)
    m = t.count(NAMES_ANCHOR)
    if m != 1:
        print(f"  !! NAMES 锚点 {m} 次")
        return 1
    t = t.replace(NAMES_ANCHOR, NAMES, 1)
    P.write_text(t, encoding="utf-8")
    print("  ✓ 已修")
    return 0


if __name__ == "__main__":
    sys.exit(main())
