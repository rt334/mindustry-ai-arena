#!/usr/bin/env python3
"""煤钻机出口自动体检：算出每台 2x2 钻机的四个输出侧，报告哪一侧有接货方。"""
import sys
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
bs = a.buildings()
ROTN = {0: "东", 1: "南", 2: "西", 3: "北"}

coal_drills = [(k, b) for k, b in sorted(bs.items())
               if b["block"].endswith("drill") and (b.get("items") or {}).get("coal") is not None
               or (b["block"].endswith("drill") and (b.get("items") or {}).get("coal"))]

print("—— 所有钻机（按矿种）的输出侧接货情况 ——")
for (x, y), b in sorted(bs.items()):
    if not b["block"].endswith("drill"):
        continue
    it = b.get("items") or {}
    eff = b.get("efficiency") or 0
    sides = {
        "东": [(x + 2, y), (x + 2, y + 1)],
        "南": [(x, y + 2), (x + 1, y + 2)],
        "西": [(x - 1, y), (x - 1, y + 1)],
        "北": [(x, y - 1), (x + 1, y - 1)],
    }
    found = []
    for name, cells in sides.items():
        for c in cells:
            nb = bs.get(c)
            if nb:
                found.append(f"{name}{c}:{nb['block'][:8]}")
    print(f"  ({x},{y}) {b['block'][:16]:<16} eff={eff} items={it} 接货方={found if found else '无!'}")
