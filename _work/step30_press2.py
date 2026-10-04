#!/usr/bin/env python3
"""阶段 30：把簇 B 的煤从「直送核心浪费」改道到核心南侧的压机。

核心南邻 (59,108) 是汇流带 rot=3，背面朝南 = (59,109)；把压机放在那儿，
产物会被汇流带直接拉进核心——不需要额外出料带。
"""
import sys
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA
from order import order

a = Arena("alpha", ALPHA)
print("拆沙钻机/转向点:", a.break_many([(58, 110), (60, 110), (56, 104)], workers=3))

S = [(56, 104, "conveyor", 1)]
for y in range(105, 110):
    S.append((56, y, "conveyor", 1))
S += [(57, 109, "conveyor", 0), (58, 109, "conveyor", 0), (59, 109, "graphite-press", 0)]
order(S, "簇B煤改道+压机")
print("queue:", a.queue()["builders"])
