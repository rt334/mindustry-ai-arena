#!/usr/bin/env python3
"""判定实验：power-node 是否能把「不相邻」的发电机与熔炉并网。"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)

# 发电机 (66,113) size1，熔炉 (68,113) size2 -> 中间夹一格 (67,113)
specs = [(67, 113, "power-node", 0)]
print("place errs:", a.place_many(specs, workers=1))
got, missing = a.confirm_placed(specs, timeout=120)
print("placed:", len(got), "missing:", missing)

t0 = time.time()
hit = None
while time.time() - t0 < 60:
    g = a.building_at(66, 113)
    s = a.building_at(68, 113)
    n = a.building_at(67, 113)
    if s and (s.get("powerStatus") or 0) > 0:
        hit = (round(time.time() - t0, 1), g.get("powerStatus"), n.get("powerStatus"), s.get("powerStatus"))
        break
    time.sleep(0.3)

print("熔炉并网时刻(gensp, nodesp, smeltsp):", hit)
for k in [(66, 113), (67, 113), (68, 113)]:
    b = a.building_at(*k)
    print(f"  {k} {b['block']:<20} eff={b.get('efficiency')} pow={b.get('powerStatus')} items={b.get('items')}")
print("rates:", a.rates(window=15).get("stored"))
