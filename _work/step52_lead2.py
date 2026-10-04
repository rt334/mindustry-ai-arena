#!/usr/bin/env python3
"""阶段 52：开发东侧铅簇（85..87,108..114），沿 y=110 走廊接回 x=75 铅带。"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221
S = []
for x in range(76, 83):
    S.append((x, 110, "conveyor", 2))
S += [(83, 110, "router", 0), (84, 110, "conveyor", 2)]
S += [(84, 112, "conveyor", 2), (83, 112, "conveyor", 3), (83, 111, "conveyor", 3)]
S += [(84, 109, "conveyor", 2), (83, 109, "conveyor", 1)]
S += [(85, 110, "pneumatic-drill", 2), (85, 112, "pneumatic-drill", 2), (85, 108, "pneumatic-drill", 2)]
print("下单", len(S), "errs:", a.place_many(S, workers=5))
for _ in range(35):
    for c in S:
        try:
            a.call("control", method="POST", op="warp", unit=UNIT, x=c[0], y=c[1])
        except Exception:
            pass
    time.sleep(0.25)
bs = a.buildings()
print("chk drills:", [(c, (bs.get(c) or {}).get("block")) for c in [(85, 110), (85, 112), (85, 108)]])
print("chk belts:", [(c, (bs.get(c) or {}).get("block")) for c in [(76, 110), (83, 110), (84, 110), (83, 112)]])
print("rates:", {k: round(s.get("perSecond", 0), 3) for k, s in (a.rates(window=15).get("stored") or {}).items()})
