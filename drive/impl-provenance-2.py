#!/usr/bin/env python3
"""用正则整行匹配给 Recorder 的 meta 头加 apiVersion。

上一版锚点写死了 14 个空格，实际对不上 —— **别凭 Get-Content 的显示猜缩进**，
用 `^(\\s*)` 把缩进捕获下来原样带回去。
"""
import pathlib
import re
import sys

REC = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Recorder.java")

RE_ = re.compile(r'^(\s*)\.put\("version", 2\)$', re.M)

NEW = (r'\1.put("version", 2)'
       '\n'r'\1// 接口版本：跨版本的成绩不可比，成绩与录像必须带得上它。'
       '\n'r'\1// 见 docs/API.md「接口版本号」与 docs/DEVELOPING.md「溯源命名」。'
       '\n'r'\1.put("apiVersion", AIArena.API_VERSION)')


def main():
    t = REC.read_text(encoding="utf-8")
    hits = RE_.findall(t)
    if len(hits) != 1:
        print(f"  !! 整行命中 {len(hits)} 次（期望 1）")
        return 1
    t = RE_.sub(NEW, t, count=1)
    REC.write_text(t, encoding="utf-8")
    print(f"  ✓ Recorder meta 加 apiVersion（缩进 {' '*len(hits[0])}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
