#!/usr/bin/env python3
"""阶段 31：突破点——用太阳能替代烧煤发电，把煤全部让给石墨压机。

solar-panel 只要铅 10 + 硅 8，不消耗煤；核心已有 383 硅。
power-node 负责把面板并到熔炉那侧的电网。
"""
import sys
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from order import order

S = []
# 面板阵列 (48..55, 105..108)
for x in range(48, 56):
    for y in range(105, 109):
        S.append((x, y, "solar-panel", 0))
# 电网：面板区 -> 熔炉
S += [(51, 107, "power-node", 0), (56, 108, "power-node", 0),
      (61, 109, "power-node", 0), (63, 110, "power-node", 0)]
# 掉一台多余的烧煤发电机，把煤留给压机
print("下单", len(S))
order(S, "太阳能阵列")
