#!/usr/bin/env python3
"""路径审计：把关键产线逐格打印出来，找出断点。"""
import sys
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
bs = a.buildings()


def show(name, cells):
    print(f"-- {name} --")
    miss = []
    for c in cells:
        b = bs.get(c)
        if b is None:
            miss.append(c)
    print(f"   缺失 {len(miss)} 格: {miss[:25]}")
    return miss


# 钛线：钻机 (36,101)/(36,104) -> (38,102..105) -> y=106 带 -> x=58 -> core
show("钛带 y=106 (x=36..58)", [(x, 106) for x in range(36, 59)])
show("钛接入 x=38 y=102..105", [(38, y) for y in range(102, 106)])

# 簇 B：长带 y=104 -> 转向 x=56 -> y=109 -> press
show("簇B长带 y=104 (x=40..55)", [(x, 104) for x in range(40, 56)])
show("簇B转向 x=56 y=104..109", [(56, y) for y in range(104, 110)])
show("簇B压机进料 y=109 x=57..59", [(57, 109), (58, 109), (59, 109)])
show("簇B 出口 (40,98)/(41,98..103)/(40,103)", [(40, 98)] + [(41, y) for y in range(98, 104)] + [(40, 103)])
show("簇B 钻机出口 (41,101)", [(41, 101)])

# 簇 C：钻机出口 -> y=84 带 -> x=64 -> y=101 -> (64,102) 铜带
show("簇C 出口 (66,82)(66,83)(68,82)(68,83)", [(66, 82), (66, 83), (68, 82), (68, 83)])
show("簇C 收集带 y=84 (x=64..70)", [(x, 84) for x in range(64, 71)])
show("簇C 南下 x=64 (y=84..101)", [(64, y) for y in range(84, 102)])
show("簇C 接入 (69,82)(69,83)", [(69, 82), (69, 83)])

# 北煤簇 (52..54,82..86)
show("(54,84)(55,85)(55,86)", [(54, 84), (55, 85), (55, 86)])
show("y=85 东行 (x=55..63)", [(x, 85) for x in range(55, 64)])

# 煤区压机煤路
show("煤柱 x=66 (y=109..118)", [(66, y) for y in range(109, 119)])
show("煤道 y=112 (x=67..74)", [(x, 112) for x in range(67, 75)])
show("压机出料 y=109 (x=69..75)", [(x, 109) for x in range(69, 76)])
