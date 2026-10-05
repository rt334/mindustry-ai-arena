#!/usr/bin/env python3
"""更新 TODO §2.3 零依赖上手行，并在根 README 里指一下 start.py。"""
import pathlib
import sys

T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")
R = pathlib.Path(r"C:\dsh\ai-arena\README.md")

TODO_OLD = "| 零依赖上手 | `start.py` 菜单，「看回放只需要浏览器」 | 起局要 JDK + 脚本，看回放要先做回放 |"
TODO_NEW = ("| 零依赖上手 | `start.py` 菜单，「看回放只需要浏览器」 | "
            "**已做**：根目录加了 `start.py`（菜单 + 子命令：check/status/play/watch/"
            "replay/stop）。**报告事实不猜** —— 前置检查逐项说清检查了什么、结果是什么，"
            "缺什么直说缺什么；`status` 会同时报端口、java 进程、tick、apiVersion。"
            "回放页本就是单文件零依赖，`replay` 子命令直接开浏览器。 |")

README_ANCHOR_MARK = "start.py"


def main():
    ok = True

    t = T.read_text(encoding="utf-8")
    n = t.count(TODO_OLD)
    if n == 1:
        T.write_text(t.replace(TODO_OLD, TODO_NEW, 1), encoding="utf-8")
        print("  ✓ TODO §2.3 零依赖上手行已更新")
    else:
        print(f"  !! TODO 锚点 {n} 次")
        for ln in t.splitlines():
            if "零依赖上手" in ln:
                print("   实际:", ln[:100])
        ok = False

    if R.exists():
        r = R.read_text(encoding="utf-8")
        if README_ANCHOR_MARK in r:
            print("  · README 已提到 start.py")
        else:
            add = ("\n## 上手\n\n```\npython start.py          # 菜单\n"
                   "python start.py check    # 前置检查（缺什么直说）\n"
                   "python start.py play     # 起局\n"
                   "python start.py watch    # 起局 + 观战端\n"
                   "python start.py replay   # 看回放（单文件，零依赖）\n```\n")
            R.write_text(r.rstrip() + "\n" + add, encoding="utf-8")
            print("  ✓ README 追加「上手」一节")
    else:
        print("  · 根 README.md 不存在，跳过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
