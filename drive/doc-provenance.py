#!/usr/bin/env python3
"""更新 TODO §2.3 溯源命名行。"""
import pathlib
import sys

T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")

OLD = "| 溯源命名 | bot 目录 `模型@工具#编号`，表格带 SHA-256 | 对局记录不带版本号 |"
NEW = ("| 溯源命名 | bot 目录 `模型@工具#编号`，表格带 SHA-256 | "
       "**已做**：录像 `meta` 头加 `apiVersion`（与录像格式的 `version` 是两个东西）；"
       "命名约定、`MANIFEST.json` 该有什么、成绩表该带哪两列"
       "（`sha256` + `apiVersion`）写进 `DEVELOPING.md`「溯源命名」。 |")


def main():
    t = T.read_text(encoding="utf-8")
    n = t.count(OLD)
    if n != 1:
        print(f"  !! 锚点 {n} 次")
        return 1
    T.write_text(t.replace(OLD, NEW, 1), encoding="utf-8")
    print("  ✓ TODO §2.3 溯源命名行已更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
