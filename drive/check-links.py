#!/usr/bin/env python3
"""扫描全部 markdown 的相对链接，报告指向不存在文件的死链。

搬家之后必须跑一次：md 之间的互链是最容易断的东西。
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(r"C:\dsh\ai-arena")
LINK = re.compile(r"\]\(([^)]+)\)")
SKIP_PREFIX = ("http://", "https://", "#", "mailto:")


def main():
    bad, total, files = [], 0, 0
    for p in sorted(ROOT.rglob("*.md")):
        if ".git" in p.parts:
            continue
        files += 1
        text = p.read_text(encoding="utf-8", errors="replace")
        for m in LINK.finditer(text):
            target = m.group(1).strip()
            if target.startswith(SKIP_PREFIX):
                continue
            target = target.split("#", 1)[0].strip()
            if not target:
                continue
            total += 1
            if not (p.parent / target).resolve().exists():
                line = text[: m.start()].count("\n") + 1
                bad.append(f"{p.relative_to(ROOT)}:{line}  ->  {target}")

    print(f"扫描 {files} 个 md，相对链接 {total} 条")
    if bad:
        print(f"死链 {len(bad)} 条：")
        for b in bad:
            print("  " + b)
        return 1
    print("无死链")
    return 0


if __name__ == "__main__":
    sys.exit(main())
