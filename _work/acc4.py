#!/usr/bin/env python3
"""建造加速器（动态版）：每次循环重读 pending.json，warp 建造单位到尚未建成的坐标。"""
import json, sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221
PATH = r"C:\dsh\ai-arena\_work\pending.json"
runs = int(sys.argv[1]) if len(sys.argv) > 1 else 100000

moves = 0
idle = 0
for _ in range(runs):
    try:
        pending = [tuple(p) for p in json.load(open(PATH))]
    except Exception:
        pending = []
    bs = a.buildings()
    todo = [p for p in pending if p not in bs]
    if not todo:
        idle += 1
        if idle > 20:
            print("清单清空且长时间无待建")
            break
        time.sleep(0.6)
        continue
    idle = 0
    t = todo[0]
    try:
        a.call("control", method="POST", op="warp", unit=UNIT, x=t[0], y=t[1])
        moves += 1
    except Exception:
        pass
    time.sleep(0.45)

bs = a.buildings()
print("warp:", moves, "queue:", a.queue()["builders"])
print("core:", [b for b in bs.values() if b["block"] == "core-nucleus"][0]["items"])
print("rates:", {k: round(s.get("perSecond", 0), 3) for k, s in (a.rates(window=15).get("stored") or {}).items()})
