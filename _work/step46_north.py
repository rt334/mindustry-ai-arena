#!/usr/bin/env python3
"""阶段 46：修北煤簇两台钻机的出口（它们的东侧被邻居钻机挡死，只能往南推）。

(65,80) 往南是 (66,82) 已有带子却仍满 —— 改用西侧出口并接到 y=84 收集带。
"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221
bs = a.buildings()
print("现状:", [(c, (bs.get(c) or {}).get("block"), (bs.get(c) or {}).get("rotation")) for c in
              [(65, 80), (66, 82), (66, 83), (66, 84), (65, 84), (63, 80), (63, 81), (63, 82), (63, 83), (63, 84)]])

S = [
    (63, 81, "conveyor", 1), (63, 82, "conveyor", 1), (63, 83, "conveyor", 1),
    (63, 84, "conveyor", 0),
]
print("下单:", a.place_many(S, workers=4))
for _ in range(16):
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
