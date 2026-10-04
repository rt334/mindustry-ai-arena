#!/usr/bin/env python3
"""阶段 42：簇 B 加钻机（它是唯一「直连压机」的煤源）。

(39,100) 东侧是邻居带子但背面对不上，永远推不出去 -> 改成朝南，配 (40,102) 下行带。
"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221
dead = [(39, 100), (40, 104)]
print("拆:", a.break_many(dead, workers=2))
t0 = time.time()
while time.time() - t0 < 90:
    if not [c for c in dead if c in a.buildings()]:
        break
    time.sleep(0.4)

S = [
    (40, 104, "router", 0),          # 长带起点改 router，便于南侧钻机倒货
    (40, 102, "conveyor", 1),        # (39,100) 下行
    (39, 100, "mechanical-drill", 1),
    (39, 102, "mechanical-drill", 1),
    (38, 104, "mechanical-drill", 0),
]
print("下单:", a.place_many(S, workers=3))
for _ in range(12):
    for c in [(39, 100), (40, 102), (40, 104), (39, 102), (38, 104)]:
        try:
            a.call("control", method="POST", op="warp", unit=UNIT, x=c[0], y=c[1])
        except Exception:
            pass
    time.sleep(0.2)
bs = a.buildings()
print("chk:", [(c, (bs.get(c) or {}).get("block")) for c in [(40, 104), (40, 102), (39, 100), (39, 102), (38, 104)]])
print("簇B 钻机:", [(k, b.get("items")) for k, b in bs.items()
                  if b["block"].endswith("drill") and 36 <= k[0] <= 42 and 95 <= k[1] <= 106])
print("press:", [(k, b.get("items"), b.get("efficiency")) for k, b in bs.items() if b["block"] == "graphite-press"])
