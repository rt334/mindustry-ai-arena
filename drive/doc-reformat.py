#!/usr/bin/env python3
"""清理 PRODUCTION.md 的结构：删掉被推翻的旧可达性小节，重编号。

旧的 §四「可达性」用的是「钻机位 × 0.35/s」这个已被推翻的口径，
留着会和 §六 打架。它里面唯一还有价值的是「窗口 vs 视野」那个坑，
那条已经写在 §三 里了。
"""
import pathlib
import sys

P = pathlib.Path(r"C:\dsh\ai-arena\docs\PRODUCTION.md")


def main():
    t = P.read_text(encoding="utf-8")

    a = t.find("## 四、可达性：「+5/s」在这个图上行不行")
    b = t.find("## 五、产率模型")
    if a < 0 or b < 0 or b <= a:
        print(f"!! 定位失败 a={a} b={b}")
        return 1
    t = t[:a] + t[b:]

    for old, new in (
        ("## 五、产率模型", "## 四、产率模型"),
        ("## 六、可达性（用正确的模型重算）", "## 五、可达性：用正确的模型重算"),
        ("## 六、下一步", "## 六、下一步"),
    ):
        n = t.count(old)
        if n != 1:
            print(f"!! {old!r} 命中 {n} 次")
            return 1
        t = t.replace(old, new, 1)

    P.write_text(t, encoding="utf-8")
    print("结构已清理")


if __name__ == "__main__":
    sys.exit(main())
