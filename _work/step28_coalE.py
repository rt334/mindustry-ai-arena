#!/usr/bin/env python3
"""阶段 28：开发东侧大煤簇（102..110,114..121，49 格），带子沿 y=118 西行汇入 x=75 铅带。"""
import sys
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from order import order

S = []
# y=118 西行主干（从煤簇西缘到铅带）
for x in range(76, 104):
    S.append((x, 118, "conveyor", 2))
# 煤簇内收集：y=112 不适用（远），改为 y=113 东行 -> 接入 x=103 南北向 -> y=118
# 直接用 y=114 上行到 y=118 的短通道
for y in range(114, 118):
    S.append((103, y, "conveyor", 1))
# 钻机（覆盖煤格）
S += [
    (102, 114, "mechanical-drill", 0),   # 102-103 / 114-115
    (104, 115, "mechanical-drill", 0),   # 104-105 / 115-116
    (106, 115, "mechanical-drill", 0),   # 106-107 / 115-116
    (105, 117, "mechanical-drill", 0),   # 105-106 / 117-118
    (107, 117, "mechanical-drill", 0),   # 107-108 / 117-118
    (108, 119, "mechanical-drill", 0),   # 108-109 / 119-120
]
order(S, "东煤簇")
