#!/usr/bin/env python3
"""阶段 9：读现状 + 测产率（轮询到出现正产出或超时，不用固定等待）。"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)

bs = a.buildings()
core = [b for b in bs.values() if b["block"] == "core-nucleus"][0]
print("core:", core["items"])
print(f"建筑 {len(bs)}:")
for k in sorted(bs, key=lambda k: (bs[k]["block"], k[1], k[0])):
    b = bs[k]
    print(f"  {b['block']:<20} ({k[0]:>3},{k[1]:>3}) rot={b.get('rotation')} eff={b.get('efficiency')} "
          f"items={b.get('items')} pow={b.get('powerStatus')}")

print("\nstalls(own):")
for s in a.stalls():
    if s.get("team") == "sharded":
        print(f"  ({s['x']},{s['y']}) {s['block']:<18} {s['kind']:<14} miss={s.get('missing')} held={s.get('heldSeconds'):.0f}")

# 产率：轮询到至少一项 > 0.05/s，或 3 分钟超时
t0 = time.time()
best = {}
while time.time() - t0 < 180:
    st = a.rates(window=20).get("stored") or {}
    vals = {k: v.get("perSecond", 0) for k, v in st.items()}
    for k, v in vals.items():
        if abs(v) > abs(best.get(k, 0)):
            best[k] = v
    if any(v > 0.05 for v in vals.values()):
        break
    time.sleep(1.0)
print("\nrates(window=20):", {k: round(v, 3) for k, v in (a.rates(window=20).get("stored") or {}).items()})
print("peak seen:", {k: round(v, 3) for k, v in best.items()})
print("core now:", [b for b in a.buildings().values() if b["block"] == "core-nucleus"][0]["items"])
