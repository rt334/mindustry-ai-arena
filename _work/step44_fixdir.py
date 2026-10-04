#!/usr/bin/env python3
"""阶段 44：修正 (61,95) 压机的出料方向——上一版把链朝北修了，核心在南边。

出料走 (60,95) rot=2 -> x=59 南下 -> 注入核心北面 (59,102)。
"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221
dead = [(62, 94)] + [(62, y) for y in range(93, 102)]
have = [c for c in dead if c in a.buildings()]
print("拆错误链:", have)
a.break_many(have, workers=3)
t0 = time.time()
while time.time() - t0 < 90:
    if not [c for c in have if c in a.buildings()]:
        break
    time.sleep(0.4)

S = [(60, 95, "conveyor", 2), (59, 95, "conveyor", 1)]
for y in range(96, 102):
    S.append((59, y, "conveyor", 1))
print("下单", len(S), "errs:", a.place_many(S, workers=3))
for _ in range(12):
    for c in [(60, 95), (59, 95), (59, 100)]:
        try:
            a.call("control", method="POST", op="warp", unit=UNIT, x=c[0], y=c[1])
        except Exception:
            pass
    time.sleep(0.2)
bs = a.buildings()
print("chk:", [(c, (bs.get(c) or {}).get("block")) for c in [(60, 95), (59, 95), (59, 101)]])
print("press:", [(k, b.get("items"), b.get("efficiency")) for k, b in bs.items() if b["block"] == "graphite-press"])
print("rates:", {k: round(s.get("perSecond", 0), 3) for k, s in (a.rates(window=15).get("stored") or {}).items()})
