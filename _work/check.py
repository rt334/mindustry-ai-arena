#!/usr/bin/env python3
"""产线体检：产率、堵塞、瓶颈定位。"""
import sys, time, collections
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
bs = a.buildings()
core = [b for b in bs.values() if b["block"] == "core-nucleus"][0]
print("core:", core["items"])
cnt = collections.Counter(b["block"] for b in bs.values())
print("建筑:", dict(cnt))

print("\n-- 关键方块 --")
for k in sorted(bs, key=lambda k: (bs[k]["block"], k[1], k[0])):
    b = bs[k]
    if b["block"] in ("conveyor", "router", "power-node"):
        continue
    print(f"  {b['block']:<20} ({k[0]:>3},{k[1]:>3}) eff={b.get('efficiency')} items={b.get('items')} pow={b.get('powerStatus')}")

print("\n-- 堵塞 --")
st = [s for s in a.stalls() if s.get("team") == "sharded"]
print(f"  共 {len(st)}")
for s in st[:25]:
    print(f"   ({s['x']},{s['y']}) {s['block']:<18} {s['kind']:<14} {s.get('missing')} held={s.get('heldSeconds'):.0f}")

# 产率
best = {}
t0 = time.time()
while time.time() - t0 < 90:
    v = {k: s.get("perSecond", 0) for k, s in (a.rates(window=15).get("stored") or {}).items()}
    for k, x in v.items():
        if x > best.get(k, -9):
            best[k] = x
    time.sleep(1.0)
print("\nrates:", {k: round(s.get("perSecond", 0), 3) for k, s in (a.rates(window=15).get("stored") or {}).items()})
print("peak :", {k: round(v, 3) for k, v in best.items()})
print("core :", [b for b in a.buildings().values() if b["block"] == "core-nucleus"][0]["items"])
print("queue:", a.queue())
