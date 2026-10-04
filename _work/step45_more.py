#!/usr/bin/env python3
"""阶段 45：给簇 C / 簇 B 补钻机（它们是直连压机的煤源，现在压机在等煤）。"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221
S = [
    (67, 82, "pneumatic-drill", 1),   # 朝南，出货给 (68,84) router
    (39, 102, "mechanical-drill", 1),  # 朝南，出货给 (40,104) router
    (38, 104, "mechanical-drill", 0),
]
print("下单:", a.place_many(S, workers=3))
for _ in range(25):
    for c in [(67, 82), (39, 102), (38, 104), (68, 84), (40, 104)]:
        try:
            a.call("control", method="POST", op="warp", unit=UNIT, x=c[0], y=c[1])
        except Exception:
            pass
    time.sleep(0.25)
bs = a.buildings()
print("chk:", [(c, (bs.get(c) or {}).get("block")) for c in S and [(67, 82), (39, 102), (38, 104)]])
print("簇C 钻机:", [(k, b.get("items")) for k, b in bs.items()
                  if b["block"].endswith("drill") and 63 <= k[0] <= 72 and 78 <= k[1] <= 85])
print("簇B 钻机:", [(k, b.get("items")) for k, b in bs.items()
                  if b["block"].endswith("drill") and 36 <= k[0] <= 42 and 95 <= k[1] <= 106])
print("press:", [(k, b.get("items"), b.get("efficiency")) for k, b in bs.items() if b["block"] == "graphite-press"])
print("rates:", {k: round(s.get("perSecond", 0), 3) for k, s in (a.rates(window=15).get("stored") or {}).items()})
