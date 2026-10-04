#!/usr/bin/env python3
"""快照 + 大批量下单（不阻塞等待建造完成）。"""
import sys, collections
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
bs = a.buildings()
core = [b for b in bs.values() if b["block"] == "core-nucleus"][0]
print("core:", core["items"])
print("counts:", dict(collections.Counter(b["block"] for b in bs.values())))
print("-- 非传送带 --")
for k in sorted(bs, key=lambda k: (bs[k]["block"], k[1], k[0])):
    b = bs[k]
    if b["block"] in ("conveyor", "power-node"):
        continue
    print(f"  {b['block']:<20} ({k[0]:>3},{k[1]:>3}) eff={b.get('efficiency')} items={b.get('items')} pow={b.get('powerStatus')}")
print("-- (66,114)-(69,119) 一带 --")
for y in range(112, 121):
    row = []
    for x in range(64, 72):
        b = bs.get((x, y))
        row.append(f"{x},{y}:{b['block'][:12] if b else '-'}")
    print("  " + " | ".join(row))
