#!/usr/bin/env python3
"""阶段 51：补齐铜/铅矿的钻机覆盖（pneumatic 0.15/格·秒，铜簇 45 格 -> 上限 6.75/s）。"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221
S = [
    (68, 100, "pneumatic-drill", 2),   # 铜，东侧 2 格 (70,100)/(70,101) 已有带子？朝西更稳
    (71, 98, "pneumatic-drill", 0),
    (66, 105, "pneumatic-drill", 0),
]
print("下单:", a.place_many(S, workers=3))
for _ in range(25):
    for c in S:
        try:
            a.call("control", method="POST", op="warp", unit=UNIT, x=c[0], y=c[1])
        except Exception:
            pass
    time.sleep(0.25)
bs = a.buildings()
print("chk:", [(c, (bs.get(c) or {}).get("block")) for c in [(68, 100), (71, 98), (66, 105)]])
print("铜区钻机:", [(k, b.get("items")) for k, b in sorted(bs.items())
                 if b["block"].endswith("drill") and 64 <= k[0] <= 74 and 97 <= k[1] <= 107])
print("rates:", {k: round(s.get("perSecond", 0), 3) for k, s in (a.rates(window=15).get("stored") or {}).items()})
