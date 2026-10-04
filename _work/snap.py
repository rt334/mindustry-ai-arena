#!/usr/bin/env python3
"""现场快照：建筑、产率、堵塞、矿机、工厂。"""
import sys
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
bs = a.buildings()
print(f"== 建筑 {len(bs)} ==")
for k in sorted(bs, key=lambda k: (bs[k]["block"], k[1], k[0])):
    b = bs[k]
    if b["block"] == "conveyor":
        continue
    print(f"  {b['block']:<20} ({k[0]:>3},{k[1]:>3}) rot={b.get('rotation')} eff={b.get('efficiency')} "
          f"items={b.get('items')} pow={b.get('powerStatus')} links={b.get('powerLinks')}")
print("  -- conveyors --")
for k in sorted(bs, key=lambda k: (k[1], k[0])):
    b = bs[k]
    if b["block"] != "conveyor":
        continue
    print(f"    ({k[0]:>3},{k[1]:>3}) rot={b.get('rotation')} items={b.get('items')}")

core = [b for b in bs.values() if b["block"] == "core-nucleus"][0]
print("\ncore:", core["items"])
print("rates stored:", a.rates(window=20).get("stored"))
print("rates core  :", a.rates(window=20).get("core"))
print("drill:", a.drill())
print("factory:", a.factory())
print("queue:", a.queue())
print("stalls(own):")
for s in a.stalls():
    if s.get("team") == "sharded":
        print(f"   ({s['x']},{s['y']}) {s['block']:<18} {s['kind']:<14} miss={s.get('missing')} held={s.get('heldSeconds'):.0f}s")
