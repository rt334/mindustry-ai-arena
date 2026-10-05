#!/usr/bin/env python3
"""造一份「有真实变化」的录像，用来真正验证播放器。

上一份录像 91 帧只有 4 个核心、0 个事件 —— 因为没接 AI，没人建造。
所以 removed（拆除）和 events 两条分支压根没被覆盖。

这里手动制造变化：
  建一批方块（含不同朝向，验 rot）
  拆掉其中几个（验 removed）
  全程录制
"""
import json
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
adm = Arena("referee", toks["referee"])
a = Arena("beta", toks["beta"])


def main():
    core = next(b for b in a.buildings() if b["block"].startswith("core"))
    cx, cy = core["x"], core["y"]
    print(f"核心 ({cx},{cy})  库存 {core['items']}")

    print("\n== 起录制 ==")
    print(f"  {json.dumps(adm.post('record', action='start', label='changes'), ensure_ascii=False)}")
    time.sleep(2)

    built = []
    # 1) 一批不同朝向的带子（验 rot 是否真的记下来）
    print("\n== 建几段朝向不同的带子 ==")
    spots = [(cx + 6, cy + 6), (cx + 7, cy + 6), (cx + 8, cy + 6),
             (cx + 6, cy + 7), (cx + 6, cy + 8)]
    for i, (x, y) in enumerate(spots):
        try:
            a.post("place", x=x, y=y, block="conveyor", rot=i % 4)
            built.append((x, y, "conveyor", i % 4))
            print(f"  ({x},{y}) conveyor rot={i % 4}")
        except ArenaError as e:
            print(f"  ({x},{y}) 拒绝 {e.code}")
    time.sleep(3)

    # 2) 拆掉其中两个（验 removed）
    print("\n== 拆掉其中两个 ==")
    for (x, y, _b, _r) in built[:2]:
        try:
            a.post("break", x=x, y=y)
            print(f"  break ({x},{y})")
        except ArenaError as e:
            print(f"  break ({x},{y}) 拒绝 {e.code}")
    time.sleep(3)

    # 3) 再建点别的
    print("\n== 再建点别的 ==")
    for (x, y, blk, rot) in [(cx + 10, cy + 6, "conveyor", 1),
                             (cx + 10, cy + 7, "conveyor", 1)]:
        try:
            a.post("place", x=x, y=y, block=blk, rot=rot)
            print(f"  ({x},{y}) {blk} rot={rot}")
        except ArenaError as e:
            print(f"  ({x},{y}) 拒绝 {e.code}")
    time.sleep(4)

    print("\n== 停录制 ==")
    print(f"  {json.dumps(adm.post('record', action='stop'), ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
