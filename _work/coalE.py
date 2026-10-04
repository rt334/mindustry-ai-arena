#!/usr/bin/env python3
"""查东侧煤簇 (95..115,105..130) 的精确格子。"""
import sys, collections
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, REF

a = Arena("referee", REF)
ts = []
for bx in range(94, 116, 22):
    for by in range(104, 132, 28):
        ts += a.map(bx, by, min(22, 116 - bx), min(28, 132 - by), view="all")
coal = sorted([(t["x"], t["y"]) for t in ts if t.get("drop") == "coal"], key=lambda p: (p[1], p[0]))
print("coal cells:", len(coal))
rows = collections.defaultdict(list)
for x, y in coal:
    rows[y].append(x)
for y in sorted(rows):
    print(f"  y={y}: {rows[y]}")
# 顺带看这一带的地形是否可建
blk = [(t["x"], t["y"], t["block"]) for t in ts if t.get("block") and t["block"] != "air"]
print("blockers:", blk[:20], "...total", len(blk))
