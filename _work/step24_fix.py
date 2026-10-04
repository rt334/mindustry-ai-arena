#!/usr/bin/env python3
"""阶段 24：修煤道起点 (67,112)（发电机挡路），再跑建造加速。"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221

print("拆 (67,112):", a.break_many([(67, 112)], workers=1))
time.sleep(1.5)
print("建 (67,112) 带:", a.place_many([(67, 112, "conveyor", 0)], workers=1))

pending = [(67, 112)]
pending += [(66, 117), (66, 118), (67, 118), (68, 116), (68, 118), (70, 115),
            (70, 116), (70, 117), (70, 118), (67, 115), (64, 84)]
pending += [(64, y) for y in range(85, 102)]
pending += [(39, 100), (41, 101), (41, 102), (41, 103), (39, 102), (40, 103), (38, 104), (67, 119)]
pending += [(52, 83), (53, 85), (55, 86)] + [(x, 85) for x in range(55, 64)]
pending += [(66, 82), (66, 83), (68, 82), (68, 83)]
pending += [(70, 110), (72, 110), (74, 110)]
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
    except Exception:
        pass
    time.sleep(0.4)

bs = a.buildings()
core = [b for b in bs.values() if b["block"] == "core-nucleus"][0]
print("剩余待建:", len([p for p in pending if p not in bs]), "/", len(pending), "warp:", moves)
print("core:", core["items"])
print("press:", [(k, b.get("items"), b.get("efficiency")) for k, b in bs.items() if b["block"] == "graphite-press"])
print("gen:", [(k, b.get("items"), b.get("efficiency")) for k, b in bs.items() if b["block"] == "combustion-generator"])
print("smelt:", [(k, b.get("items"), b.get("powerStatus")) for k, b in bs.items() if b["block"] == "silicon-smelter"])
print("rates:", {k: round(s.get("perSecond", 0), 3) for k, s in (a.rates(window=15).get("stored") or {}).items()})
