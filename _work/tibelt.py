#!/usr/bin/env python3
"""追踪钛带整行 + 核心边缘。"""
import sys
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
bs = a.buildings()
print("y=106 全行 x=34..62:")
for x in range(34, 63):
    b = bs.get((x, 106))
    if b is None:
        print(f"   {x}: --")
    else:
        print(f"   {x}: {b['block']:<16} rot={b.get('rotation')} items={b.get('items')}")
print()
print("钛钻机:", [(k, b.get("items")) for k, b in bs.items() if b["block"].endswith("drill") and k[0] < 45])
print("core:", [b["items"] for b in bs.values() if b["block"] == "core-nucleus"])
print("rates:", {k: round(s.get("perSecond", 0), 3) for k, s in (a.rates(window=20).get("stored") or {}).items()})
