#!/usr/bin/env python3
"""逐格追踪关键出口链，带 items 显示。"""
import sys
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
bs = a.buildings()


def dump(name, x0, x1, y0, y1):
    print(f"== {name} ==")
    for y in range(y0, y1 + 1):
        parts = []
        for x in range(x0, x1 + 1):
            b = bs.get((x, y))
            if b is None:
                parts.append(f"{x}:--")
            else:
                it = b.get("items") or {}
                tag = ",".join(f"{k[:4]}{v}" for k, v in it.items())
                parts.append(f"{x}:{b['block'][:9]}[{tag}]")
        print(f"  y={y:>3} " + " ".join(parts))


dump("簇B 出口 (39..42, 96..106)", 39, 42, 96, 106)
dump("簇C 出口 (64..70, 80..86)", 64, 70, 80, 86)
dump("钛接入 (36..40, 100..107)", 36, 40, 100, 107)
