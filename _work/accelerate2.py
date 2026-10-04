#!/usr/bin/env python3
"""建造加速器 v2：按自己维护的待建坐标清单，循环 warp 建造单位过去。

/buildings 里没有的坐标 = 尚未建成 -> 单位必须到那儿才能推进。
"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221

pending = []
pending += [(66, 117), (66, 118), (67, 118), (68, 116), (68, 118), (70, 115),
            (70, 116), (70, 117), (70, 118), (67, 115), (67, 111), (64, 84)]
pending += [(64, y) for y in range(85, 102)]
pending += [(39, 100), (41, 101), (41, 102), (41, 103), (39, 102), (40, 103), (38, 104), (67, 119)]
pending += [(52, 83), (53, 85), (55, 86)] + [(x, 85) for x in range(55, 64)]
pending += [(66, 82), (66, 83), (68, 82), (68, 83)]
pending += [(65, 114), (67, 112), (68, 112), (70, 112), (72, 112), (74, 112),
            (69, 112), (71, 112), (73, 112), (70, 110), (72, 110), (74, 110)]
pending += [(x, 109) for x in range(70, 76)]
pending += [(x, 135) for x in range(76, 95)] + [(76, y) for y in range(126, 135)]
pending += [(89, 130), (91, 131), (92, 133), (89, 132), (89, 133), (89, 134), (94, 134)]

deadline = time.time() + float(sys.argv[1] if len(sys.argv) > 1 else 300)
moves = 0
while time.time() < deadline:
    bs = a.buildings()
    todo = [p for p in pending if p not in bs]
    if not todo:
        print("待建清单已清空")
        break
    t = todo[0]
    try:
        a.call("control", method="POST", op="warp", unit=UNIT, x=t[0], y=t[1])
        moves += 1
    except Exception as e:
        print("warp err:", e)
    time.sleep(0.5)

bs = a.buildings()
print("剩余待建:", len([p for p in pending if p not in bs]), "/", len(pending))
print("warp 次数:", moves)
print("unit:", a.call("units")["units"])
print("queue:", a.queue()["builders"])
print("core:", [b for b in bs.values() if b["block"] == "core-nucleus"][0]["items"])
