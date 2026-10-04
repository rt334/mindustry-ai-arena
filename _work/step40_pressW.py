#!/usr/bin/env python3
"""阶段 40：把核心西侧的长煤带（簇 B，~1.5 煤/s）直接接到新压机 —— 不再让它白送进核心。

长带 y=104 上插一个 router 分出北向支线到压机；
压机产物沿 y=102 东行，直接注入核心西缘（core 占 x59..63 y102..106）。
"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221

# 长带那一格改成 router
print("拆 (50,104):", a.break_many([(50, 104)], workers=1))
t0 = time.time()
while time.time() - t0 < 60:
    if (50, 104) not in a.buildings():
        break
    time.sleep(0.4)

S = [(50, 104, "router", 0), (50, 103, "conveyor", 3), (50, 102, "graphite-press", 0)]
for x in range(52, 59):
    S.append((x, 102, "conveyor", 0))
print("下单", len(S), "errs:", a.place_many(S, workers=3))
for _ in range(10):
    for c in [(50, 104), (50, 103), (50, 102), (54, 102)]:
        try:
            a.call("control", method="POST", op="warp", unit=UNIT, x=c[0], y=c[1])
        except Exception:
            pass
    time.sleep(0.2)
bs = a.buildings()
print("chk:", [(c, (bs.get(c) or {}).get("block")) for c in [(50, 104), (50, 103), (50, 102)]])
print("press:", [(k, b.get("items"), b.get("efficiency")) for k, b in bs.items() if b["block"] == "graphite-press"])
print("rates:", {k: round(s.get("perSecond", 0), 3) for k, s in (a.rates(window=15).get("stored") or {}).items()})
