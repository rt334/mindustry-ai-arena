#!/usr/bin/env python3
"""条目 18 的实质动作：把那条边界判定写进 §六（它此前只在 §7.9 里记着）。"""
import pathlib
import sys

T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")

ANCHOR = "| **反向提示系统** | 会额外给 AI 免费情报，违反对等约束 |"

NEW_ROW = """| **物流归属判断**（「哪些邻格属于其他资源的干线、会不会混料」） | 按「暴露规则可以、暴露结论越线」的标准：让服务端指出「这条带子属于谁、你会不会灌错料」是**结论**，属于 AI 该自己推的事，替它推等于代打。同一标准下**可以做**的是「每台钻机实际往哪几格推货」——那是**规则**，与 `acceptsFrom` / `sendsTo` 同级，见 §7.9 |
| **反向提示系统** | 会额外给 AI 免费情报，违反对等约束 |"""


def main():
    t = T.read_text(encoding="utf-8")
    n = t.count(ANCHOR)
    if n != 1:
        print(f"  !! 锚点 {n} 次")
        return 1
    t = t.replace(ANCHOR, NEW_ROW, 1)

    # §7.8 里条目 18 那行也要改，别再说「未做」
    old18 = "| 18 | 一条该进 §六 明确不做的边界判定 | **未做**。见 §7.9。 |"
    new18 = "| 18 | 一条该进 §六 明确不做的边界判定 | **已做**。§六 已加入「物流归属判断」一行（结论越线不做），并把同一标准下**可以做**的那条（钻机实际推货格 = 规则）一并写明，见 §7.9。 |"
    if t.count(old18) != 1:
        print(f"  !! 条目18 锚点 {t.count(old18)} 次（继续写 §六）")
    else:
        t = t.replace(old18, new18, 1)
        print("  ✓ §7.8 条目 18 改为已做")

    T.write_text(t, encoding="utf-8")
    print("  ✓ §六 已加入「物流归属判断」")
    return 0


if __name__ == "__main__":
    sys.exit(main())
