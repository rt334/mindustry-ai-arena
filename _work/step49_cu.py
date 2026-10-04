#!/usr/bin/env python3
"""阶段 49：升级铜/铅钻机为 pneumatic-drill（石墨够多少升多少）。"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221
TARGETS = {(72, 100): 0, (67, 104): 0, (69, 104): 0,
           (66, 122): 0, (67, 124): 0, (68, 121): 0}


def warp(x, y):
    try:
        a.call("control", method="POST", op="warp", unit=UNIT, x=int(x), y=int(y))
    except Exception:
        pass


done = 0
for (x, y), rot in TARGETS.items():
    bs = a.buildings()
    b = bs.get((x, y))
    if b is None or b["block"] != "mechanical-drill":
        print(f"跳过 {x},{y} ({b['block'] if b else '空'})")
        continue
    core = [v for v in bs.values() if v["block"] == "core-nucleus"][0]["items"]
    if core.get("graphite", 0) < 11:
        print(f"石墨不足 {core.get('graphite', 0)}，停")
        break
    a.break_many([(x, y)], workers=1)
    t0 = time.time()
    while time.time() - t0 < 45:
        if (x, y) not in a.buildings():
            break
        time.sleep(0.3)
    a.place_many([(x, y, "pneumatic-drill", rot)], workers=1)
    t0 = time.time()
    while time.time() - t0 < 60:
        nb = a.buildings().get((x, y))
        if nb and nb["block"] == "pneumatic-drill":
            break
        warp(x, y)
        time.sleep(0.3)
    nb = a.buildings().get((x, y))
    print(f"  ({x},{y}) -> {nb['block'] if nb else '缺失'}")
    if nb and nb["block"] == "pneumatic-drill":
        done += 1
print("升级:", done)
print("core:", [v['items'] for v in a.buildings().values() if v['block'] == 'core-nucleus'])
print("rates:", {k: round(s.get("perSecond", 0), 3) for k, s in (a.rates(window=15).get("stored") or {}).items()})
