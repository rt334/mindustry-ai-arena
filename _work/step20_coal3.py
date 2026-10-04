#!/usr/bin/env python3
"""阶段 20：再开一个煤簇（52..54,82..86），接进 x=64 南下煤带。下单即走。"""
import sys
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
S = [
    (52, 83, "mechanical-drill", 0),
    (53, 85, "mechanical-drill", 0),
]
# 东向接入带 (55..63,85) -> (64,85)（x=64 是南下煤带）
for x in range(55, 64):
    S.append((x, 85, "conveyor", 0))
S += [(55, 86, "conveyor", 0)]  # 备用一格
print(f"下单 {len(S)}")
print("errs:", a.place_many(S, workers=6))
print("queue:", a.queue())
