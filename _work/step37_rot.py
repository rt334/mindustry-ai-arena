#!/usr/bin/env python3
"""阶段 37：北煤簇两台钻机朝向错了（东侧被邻居钻机占着，推不出去）——改成朝南。

钻机只向「正对输出侧」的两格推货；(65,80)/(67,80) 的东侧是另一台钻机，所以永远推不出去。
"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221
dead = [(65, 80), (67, 80)]
print("拆:", a.break_many(dead, workers=2))
t0 = time.time()
while time.time() - t0 < 90:
    if not [c for c in dead if c in a.buildings()]:
        break
    time.sleep(0.4)

S = [(65, 80, "pneumatic-drill", 1), (67, 80, "pneumatic-drill", 1)]
print("下单:", a.place_many(S, workers=2))
for _ in range(6):
    for c in [(65, 80), (67, 80)]:
        try:
            a.call("control", method="POST", op="warp", unit=UNIT, x=c[0], y=c[1])
        except Exception:
            pass
        time.sleep(0.2)
bs = a.buildings()
print("现状:", [(c, (bs.get(c) or {}).get("block"), (bs.get(c) or {}).get("rotation")) for c in [(65, 80), (67, 80)]])
