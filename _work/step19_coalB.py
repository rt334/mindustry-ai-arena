#!/usr/bin/env python3
"""阶段 19：西侧煤簇 B 扩产（钻机 + 接入长带）。下单即走。"""
import sys
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
S = [
    (39, 100, "mechanical-drill", 0),
    (41, 101, "conveyor", 1), (41, 102, "conveyor", 1), (41, 103, "conveyor", 1),
    (39, 102, "mechanical-drill", 0),
    (40, 103, "conveyor", 1),
    (38, 104, "mechanical-drill", 0),
    # 簇 A 再挤一台
    (67, 119, "mechanical-drill", 0),
]
print(f"下单 {len(S)}")
print("errs:", a.place_many(S, workers=6))
print("queue:", a.queue())
