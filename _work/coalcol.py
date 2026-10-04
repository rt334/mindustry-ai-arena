#!/usr/bin/env python3
"""煤柱逐格诊断：方向 + 存货。"""
import sys
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
bs = a.buildings()
ROT = {0: "东", 1: "南", 2: "西", 3: "北", None: "?"}
print("煤柱 x=65..70, y=108..119")
for y in range(108, 120):
    parts = []
    for x in range(65, 71):
        b = bs.get((x, y))
        if b is None:
            parts.append(f"{x}:--")
        else:
            r = ROT.get(b.get("rotation"))
            it = b.get("items") or {}
            tag = ",".join(f"{k[:4]}{v}" for k, v in it.items())
            parts.append(f"{x}:{b['block'][:8]}({r})[{tag}]")
    print(f"  y={y:>3} " + " ".join(parts))
print()
print("煤钻机:")
for k, b in sorted(bs.items()):
    if b["block"].endswith("drill") and 60 <= k[0] <= 75 and 110 <= k[1] <= 125:
        print(f"   {k} {b['block']:<18} rot={b.get('rotation')} items={b.get('items')}")
print("press:", [(k, b.get("items"), b.get("efficiency")) for k, b in bs.items() if b["block"] == "graphite-press"])
