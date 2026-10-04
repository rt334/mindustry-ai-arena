#!/usr/bin/env python3
"""煤线专项体检：每台煤钻机的状态、煤带的流动情况。"""
import sys, collections
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
bs = a.buildings()
print("-- 钻机 --")
for k in sorted(bs):
    b = bs[k]
    if not b["block"].endswith("drill"):
        continue
    print(f"  {b['block']:<18} ({k[0]:>3},{k[1]:>3}) eff={b.get('efficiency')} items={b.get('items')}")

print("-- 煤区通道 (x=64..76, y=108..136) --")
for y in range(108, 137):
    row = []
    for x in range(64, 77):
        b = bs.get((x, y))
        if b is None:
            row.append(f"{x}:-")
        else:
            it = b.get("items") or {}
            row.append(f"{x}:{b['block'][:6]}{'.' if not it else list(it)[0][:4]}")
    print("  " + " ".join(row))
print("queue:", a.queue()["builders"])
