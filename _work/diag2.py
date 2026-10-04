#!/usr/bin/env python3
"""诊断 (52,83) 出口链与 x=64 南下链。"""
import sys
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
bs = a.buildings()
print("y=83..86, x=52..66:")
for y in range(83, 87):
    parts = []
    for x in range(52, 67):
        b = bs.get((x, y))
        parts.append(f"{x}:{'-' if b is None else b['block'][:8]}")
    print(f"  y={y} " + " ".join(parts))
print()
print("x=64 列 y=84..102:")
for y in range(84, 103):
    b = bs.get((64, y))
    print(f"   y={y}: {b['block'] if b else '--'} rot={b.get('rotation') if b else '-'} items={b.get('items') if b else ''}")
