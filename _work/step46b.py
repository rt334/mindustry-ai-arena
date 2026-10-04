#!/usr/bin/env python3
"""阶段 46：北煤簇 (65,80) 改朝西出货（东/南两个候选格都被邻居占/堵），
接一条 x=63 下行链接回 y=84 收集带。"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221
print("拆 (65,80):", a.break_many([(65, 80)], workers=1))
t0 = time.time()
while time.time() - t0 < 60:
    if (65, 80) not in a.buildings():
        break
    time.sleep(0.4)

S = [(65, 80, "pneumatic-drill", 2),
     (63, 81, "conveyor", 1), (63, 82, "conveyor", 1), (63, 83, "conveyor", 1),
     (63, 84, "conveyor", 0)]
print("下单:", a.place_many(S, workers=4))
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
