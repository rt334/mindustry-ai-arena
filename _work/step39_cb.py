#!/usr/bin/env python3
"""阶段 39：簇 B 出口链减负——(39,100) 钻机改朝南，去掉链中间多余的 router。"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221

dead = [(39, 100), (41, 100)]
print("拆:", a.break_many(dead, workers=2))
t0 = time.time()
while time.time() - t0 < 90:
    if not [c for c in dead if c in a.buildings()]:
        break
    time.sleep(0.4)

S = [
    (40, 102, "conveyor", 1),
    (41, 100, "conveyor", 1),
    (39, 100, "mechanical-drill", 1),
]
print("下单:", a.place_many(S, workers=3))
for _ in range(8):
    for c in [(39, 100), (40, 102), (41, 100)]:
        try:
            a.call("control", method="POST", op="warp", unit=UNIT, x=c[0], y=c[1])
        except Exception:
            pass
    time.sleep(0.2)
bs = a.buildings()
print("chk:", [(c, (bs.get(c) or {}).get("block")) for c in [(39, 100), (40, 102), (41, 100)]])
print("drills<45:", [(k, b.get("items")) for k, b in bs.items() if b["block"].endswith("drill") and k[0] < 45])
print("blocked:", [(s['x'], s['y']) for s in a.stalls() if s.get('team') == 'sharded' and s['kind'] == 'drillBlocked'])
