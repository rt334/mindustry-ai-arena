#!/usr/bin/env python3
"""修 /drill 的速率字段：lastDrillSpeed 是**每 tick**，不是每秒。

引擎 Drill.java:303:
    lastDrillSpeed = (speed * dominantItems * warmup) / delay;
而引擎 UI 要 lastDrillSpeed * 60 * timeScale 才是「个/秒」（Drill.java:118）。

我的文档注释却写成「当前产出速率（个/秒）」—— 我自己就被绊了一次：
看到 0.01 以为是 0.01/s（那意味着 100 秒出 1 个矿），与实测 0.35/s 矛盾，
白查一轮。4 格铜矿真实值 0.0062/tick 被舍入成 0.01，×60 = 0.37/s 才对上。

修法：lastDrillSpeed 保持原样（引擎字段，改名会误导），旁边补
itemsPerSecond 与 dominantItems，让 AI 不必知道 ×60 这个隐含约定，
也不必去猜产率与矿格数的关系。

上一版的教训：两处 .put 的缩进是 20 和 16，而 16 空格那串是 20 空格行的
**子串**，直接 count/replace 会把一行匹配两次、计数全乱。改用正则整行匹配。
"""
import pathlib
import re
import sys

API = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\HttpApi.java")

OLD_COMMENT = "lastDrillSpeed 当前产出速率（个/秒）"
NEW_COMMENT = """lastDrillSpeed **每 tick** 速率（引擎字段，只两位小数，
     *                  0.01 可能对应真实 0.0062 —— 别当每秒读）
     *   itemsPerSecond  每秒产出（= lastDrillSpeed × 60）。**读这个**
     *   dominantItems   钻机脚印内的主矿格数。产率**正比于它**：
     *                   每秒 = 60 × dominantItems ÷ (drillTime + 50 × 硬度)"""

PUT_RE = re.compile(r'^(\s*)\.put\("lastDrillSpeed", d\.lastDrillSpeed\)$', re.M)


def main():
    t = API.read_text(encoding="utf-8")
    bad = []

    n = t.count(OLD_COMMENT)
    if n == 1:
        t = t.replace(OLD_COMMENT, NEW_COMMENT, 1)
        print("  ✓ 1 处  注释写准（每 tick，不是每秒）")
    else:
        bad.append(f"注释锚点 {n} 次")

    hits = PUT_RE.findall(t)
    if len(hits) == 2:
        t = PUT_RE.sub(
            lambda m: (f'{m.group(1)}.put("lastDrillSpeed", d.lastDrillSpeed)\n'
                       f'{m.group(1)}.put("itemsPerSecond", d.lastDrillSpeed * 60f)\n'
                       f'{m.group(1)}.put("dominantItems", d.dominantItems)'), t)
        print("  ✓ 2 处  补 itemsPerSecond 与 dominantItems")
    else:
        bad.append(f"put 锚点 {len(hits)} 次（期望 2）")

    if bad:
        print("有问题，未写盘：")
        for b in bad:
            print("   " + b)
        return 1
    API.write_text(t, encoding="utf-8")
    print("\n/drill 的速率字段已修")
    return 0


if __name__ == "__main__":
    sys.exit(main())
