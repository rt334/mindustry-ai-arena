#!/usr/bin/env python3
"""煤格覆盖率分析：找出近处还没被任何钻机覆盖的煤格。"""
import sys
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
bs = a.buildings()
# 近处煤区
regions = [(36, 40, 95, 105), (50, 56, 80, 88), (63, 74, 78, 86), (63, 76, 112, 120)]
coal = set()
for x0, x1, y0, y1 in regions:
    for t in a.map(x0, y0, x1 - x0 + 1, y1 - y0 + 1, view=None):
        if t.get("drop") == "coal":
            coal.add((t["x"], t["y"]))
covered = set()
for (x, y), b in bs.items():
    if b["block"].endswith("drill"):
        for dx in (0, 1):
            for dy in (0, 1):
                covered.add((x + dx, y + dy))
free = sorted(coal - covered)
print(f"近处煤格 {len(coal)}，被钻机覆盖 {len(coal & covered)}，未覆盖 {len(free)}")
rows = {}
for x, y in free:
    rows.setdefault(y, []).append(x)
for y in sorted(rows):
    print(f"  y={y}: {rows[y]}")
# 顺带看哪些 2x2 位置刚好覆盖 4 格煤
best = []
for x in range(30, 80):
    for y in range(75, 125):
        c = sum(1 for dx in (0, 1) for dy in (0, 1) if (x + dx, y + dy) in free)
        if c >= 3:
            best.append((c, x, y))
best.sort(reverse=True)
print("候选钻机位(覆盖 >=3 未覆盖煤格):")
for c, x, y in best[:12]:
    print(f"   ({x},{y}) 覆盖 {c} 格")
