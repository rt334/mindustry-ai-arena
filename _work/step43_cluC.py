#!/usr/bin/env python3
"""阶段 43：把簇 C（x=64 南下煤带，~2.4 煤/s）也接到压机——它现在全白送进核心。

在 x=64 链上开一个 router 岔口，西侧挂压机，产物沿 x=62 北上直接注入核心北缘。
"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221
print("拆 (64,95):", a.break_many([(64, 95)], workers=1))
t0 = time.time()
while time.time() - t0 < 60:
    if (64, 95) not in a.buildings():
        break
    time.sleep(0.4)

S = [(64, 95, "router", 0), (63, 95, "conveyor", 2), (61, 95, "graphite-press", 0)]
S += [(62, 94, "conveyor", 3)]
for y in range(93, 101):
    S.append((62, y, "conveyor", 3))
S.append((62, 101, "router", 0))
print("下单", len(S), "errs:", a.place_many(S, workers=4))
for _ in range(12):
    for c in [(64, 95), (63, 95), (61, 95), (62, 97), (62, 101)]:
        try:
            a.call("control", method="POST", op="warp", unit=UNIT, x=c[0], y=c[1])
        except Exception:
            pass
    time.sleep(0.2)
bs = a.buildings()
print("chk:", [(c, (bs.get(c) or {}).get("block")) for c in [(64, 95), (63, 95), (61, 95), (62, 101)]])
print("press:", [(k, b.get("items"), b.get("efficiency")) for k, b in bs.items() if b["block"] == "graphite-press"])
