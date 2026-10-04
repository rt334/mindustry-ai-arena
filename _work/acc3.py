#!/usr/bin/env python3
"""持续建造加速器：循环 warp 建造单位到 pending.json 里尚未建成的坐标。"""
import json, sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221
pending = [tuple(p) for p in json.load(open(r"C:\dsh\ai-arena\_work\pending.json"))]
runs = int(sys.argv[1]) if len(sys.argv) > 1 else 100000

moves = 0
stall = 0
for _ in range(runs):
    bs = a.buildings()
    todo = [p for p in pending if p not in bs]
    if not todo:
        print("清空")
        break
    t = todo[0]
    try:
        a.call("control", method="POST", op="warp", unit=UNIT, x=t[0], y=t[1])
        moves += 1
    except Exception as e:
        print("warp err:", e)
    time.sleep(0.45)

bs = a.buildings()
print("剩余:", len([p for p in pending if p not in bs]), "/", len(pending), "warp:", moves)
print("queue:", a.queue()["builders"])
print("core:", [b for b in bs.values() if b["block"] == "core-nucleus"][0]["items"])
print("rates:", {k: round(s.get("perSecond", 0), 3) for k, s in (a.rates(window=15).get("stored") or {}).items()})
