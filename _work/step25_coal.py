#!/usr/bin/env python3
"""阶段 25：硬化煤路（每个堵点都补出口）+ 继续扩煤钻机。下单即走。"""
import sys
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)

# (67,116) 由带子改 router，让两台北侧钻机的煤汇回煤道
print("拆 (67,116):", a.break_many([(67, 116)], workers=1))

S = [
    # 簇 (52..54,82..86) 钻机 (52,83) 的出口
    (54, 84, "conveyor", 1),
    # 簇 A 行B 两台钻机 -> (65,114) 发电机
    (67, 116, "router", 0),
    (65, 116, "conveyor", 3),
    (65, 115, "conveyor", 3),
    # 簇 C 两台钻机出口
    (66, 82, "conveyor", 1), (66, 83, "conveyor", 1),
    (68, 82, "conveyor", 1), (68, 83, "conveyor", 1),
    # 西煤簇 B 补钻机
    (39, 100, "mechanical-drill", 0), (39, 102, "mechanical-drill", 0),
    (38, 104, "mechanical-drill", 0),
    (41, 101, "conveyor", 1), (41, 102, "conveyor", 1), (41, 103, "conveyor", 1),
    (40, 103, "conveyor", 1),
    # 北煤簇 (52..54,82..86) 第二台
    (53, 85, "mechanical-drill", 0),
    (55, 85, "conveyor", 0), (55, 86, "conveyor", 0),
]
print("下单", len(S))
print("errs:", a.place_many(S, workers=6))
print("queue:", a.queue()["builders"])
