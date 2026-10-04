#!/usr/bin/env python3
"""阶段 23：开发东南远煤簇（89..94,129..134），带子沿 x=76 北上汇入 y=126 收集带。"""
import sys
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
S = []
# 簇内收集带 y=135 朝西
for x in range(76, 95):
    S.append((x, 135, "conveyor", 2))
# x=76 北上
for y in range(127, 135):
    S.append((76, y, "conveyor", 3))
S.append((76, 126, "conveyor", 2))
# 钻机 + 接入
S += [(89, 130, "mechanical-drill", 0), (91, 131, "mechanical-drill", 0),
      (92, 133, "mechanical-drill", 0)]
S += [(89, 132, "conveyor", 1), (89, 133, "conveyor", 1), (89, 134, "conveyor", 1),
      (94, 134, "conveyor", 1)]
print(f"下单 {len(S)}")
print("errs:", a.place_many(S, workers=6))
print("queue:", a.queue()["builders"])
