#!/usr/bin/env python3
"""阶段 41：簇 B 是「直连压机」的黄金煤源——加钻机 + 再加一台压机。"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221
bs = a.buildings()
print("簇B 现状:")
for y in range(96, 106):
    print(f"  y={y}", [(x, (bs.get((x, y)) or {}).get("block", "-")[:10]) for x in range(36, 44)])
print("簇B 煤钻机:", [(k, b.get("items")) for k, b in bs.items()
                  if b["block"].endswith("drill") and 36 <= k[0] <= 42 and 95 <= k[1] <= 105])
