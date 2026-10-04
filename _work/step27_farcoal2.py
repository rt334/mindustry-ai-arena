#!/usr/bin/env python3
"""阶段 27：开发西南远煤簇（28..31,127..130）——沿 x=27 北上接钛带西延段。"""
import sys
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
S = []
# 簇内收集带 y=131 朝西
for x in range(27, 33):
    S.append((x, 131, "conveyor", 2))
# x=27 北上
for y in range(107, 131):
    S.append((27, y, "conveyor", 3))
# 钛带西延，把这条线并入 y=106
for x in range(27, 36):
    S.append((x, 106, "conveyor", 0))
# 钻机
S += [(28, 128, "mechanical-drill", 0), (29, 129, "mechanical-drill", 0)]
print("下单", len(S))
print("errs:", a.place_many(S, workers=6))
print("queue:", a.queue()["builders"])
