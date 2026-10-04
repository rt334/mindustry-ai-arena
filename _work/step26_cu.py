#!/usr/bin/env python3
"""阶段 26：补回铜钻机 + 生成待建清单文件供加速器使用。"""
import sys, json
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
S = [
    (68, 100, "mechanical-drill", 2),
    (70, 100, "mechanical-drill", 2),
]
print("下单", len(S), "errs:", a.place_many(S, workers=2))

pending = []
pending += [(67, 112), (54, 84), (67, 116), (65, 116), (65, 115)]
pending += [(66, 82), (66, 83), (68, 82), (68, 83)]
pending += [(39, 100), (39, 102), (38, 104), (41, 101), (41, 102), (41, 103), (40, 103)]
pending += [(52, 83), (53, 85), (55, 85), (55, 86)] + [(x, 85) for x in range(55, 64)]
pending += [(68, 100), (70, 100)]
pending += [(66, 117), (66, 118), (67, 118), (68, 116), (68, 118), (70, 115),
            (70, 116), (70, 117), (70, 118), (67, 115), (64, 84)]
pending += [(64, y) for y in range(85, 102)]
pending += [(70, 110), (72, 110), (74, 110)]
pending += [(x, 109) for x in range(70, 76)]
pending += [(x, 135) for x in range(76, 95)] + [(76, y) for y in range(126, 135)]
pending += [(89, 130), (91, 131), (92, 133), (89, 132), (89, 133), (89, 134), (94, 134)]
json.dump(pending, open(r"C:\dsh\ai-arena\_work\pending.json", "w"))
print("pending:", len(pending))
