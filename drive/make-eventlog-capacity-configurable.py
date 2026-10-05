#!/usr/bin/env python3
"""把事件环形缓冲容量做成可覆盖，用来验证 cursor_expired 契约。

背景：EventLog.CAPACITY = 4096，而 cursorExpired 的判据是
    since > 0 && since < firstSeq - 1
firstSeq 只在缓冲绕圈后才前进。开局十几分钟才攒到 140 条事件 ——
靠正常游玩把缓冲打满要十几分钟，且会把这个局刷得没法看。

改成可覆盖（-Darena.eventlog.capacity=N）后，用小容量复现同一条契约，
验完再用默认值跑。这不是把测试做假：绕过的是「攒够 4096 条」这件与
契约本身无关的事，firstSeq 前进与判定逻辑一行没动。
"""
import pathlib
import sys

E = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\EventLog.java")

OLD = "    private static final int CAPACITY = 4096;"
NEW = """    /**
     * 环形缓冲容量。
     *
     * 可被 -Darena.eventlog.capacity=N 覆盖 —— 只为**测试游标过期契约**用：
     * cursorExpired 判定要等缓冲绕一圈（firstSeq 前进）才会成立，而攒满 4096 条
     * 事件要十几分钟的正常游玩。用小容量复现同一条判定，与契约本身无关。
     * 生产一律用默认值。
     */
    private static final int CAPACITY =
        Math.max(2, Integer.getInteger("arena.eventlog.capacity", 4096));"""


def main():
    t = E.read_text(encoding="utf-8")
    n = t.count(OLD)
    if n != 1:
        print(f"!! 锚点 {n} 次（期望 1），未写盘")
        return 1
    E.write_text(t.replace(OLD, NEW), encoding="utf-8")
    print("EventLog：CAPACITY 可覆盖")
    return 0


if __name__ == "__main__":
    sys.exit(main())
