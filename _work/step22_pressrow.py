#!/usr/bin/env python3
"""阶段 22：把煤道铺到 y=112，沿煤道挂一排石墨压机（router 直接供煤，产物走北侧汇流带）。

这是关键结构：router 主动分发，不依赖「背面对齐」，因此可以在同一行密集排压机。
"""
import sys
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)

print("拆 (67,112) 发电机:", a.break_many([(67, 112)], workers=1))

S = []
# 发电机搬到 (65,114)（与 (66,114) router 相邻，直接吃煤）
S.append((65, 114, "combustion-generator", 0))
# 煤道 y=112：朝东
S += [(67, 112, "conveyor", 0)]
for x in (68, 70, 72, 74):
    S.append((x, 112, "router", 0))
for x in (69, 71, 73):
    S.append((x, 112, "conveyor", 0))
# 三台压机
S += [(70, 110, "graphite-press", 0), (72, 110, "graphite-press", 0), (74, 110, "graphite-press", 0)]
# 产物输出带（北侧 -> y=108 汇流带）
for x in range(70, 76):
    S.append((x, 109, "conveyor", 3))

print(f"下单 {len(S)}")
print("errs:", a.place_many(S, workers=6))
print("queue:", a.queue()["builders"])
bs = a.buildings()
print("core:", [b for b in bs.values() if b["block"] == "core-nucleus"][0]["items"])
