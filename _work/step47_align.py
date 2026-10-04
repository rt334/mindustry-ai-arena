#!/usr/bin/env python3
"""阶段 47：真正对齐北煤簇两台钻机的出口格。

教训：(65,80) 是 2x2，西邻是 (64,80)/(64,81)，不是 (63,*)——之前算错了一格。
"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221
print("拆 (67,80):", a.break_many([(67, 80)], workers=1))
t0 = time.time()
while time.time() - t0 < 60:
    if (67, 80) not in a.buildings():
        break
    time.sleep(0.4)

S = [
    (64, 80, "conveyor", 2), (63, 80, "conveyor", 1),   # (65,80) 的西向出口
    (67, 80, "pneumatic-drill", 1),                      # 朝南出货到 (68,82)
]
print("下单:", a.place_many(S, workers=3))
for _ in range(20):
    for c in S:
        try:
            a.call("control", method="POST", op="warp", unit=UNIT, x=c[0], y=c[1])
        except Exception:
            pass
    time.sleep(0.25)
bs = a.buildings()
print("chk:", [(c, (bs.get(c) or {}).get("block")) for c in S])
print("簇C 钻机:", [(k, b.get("items")) for k, b in bs.items()
                  if b["block"].endswith("drill") and 63 <= k[0] <= 72 and 78 <= k[1] <= 85])
print("rates:", {k: round(s.get("perSecond", 0), 3) for k, s in (a.rates(window=15).get("stored") or {}).items()})
