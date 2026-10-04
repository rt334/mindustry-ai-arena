#!/usr/bin/env python3
"""阶段 13：修煤柱分流点 + 补 y=116 收集带 + 行B钻机 + 北侧煤簇C 长带。"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221


def warp(x, y):
    try:
        a.call("control", method="POST", op="warp", unit=UNIT, x=int(x), y=int(y))
    except Exception:
        pass


def smart_place(specs, batch=10, timeout=200):
    miss_all = []
    for i in range(0, len(specs), batch):
        sub = specs[i:i + batch]
        a.place_many(sub, workers=4)
        warp(sum(s[0] for s in sub) / len(sub), sum(s[1] for s in sub) / len(sub))
        t0 = time.time()
        while time.time() - t0 < timeout:
            bs = a.buildings()
            if all(bs.get((s[0], s[1]), {}).get("block") == s[2] for s in sub):
                break
            time.sleep(0.25)
        bs = a.buildings()
        miss = [(s[0], s[1], s[2]) for s in sub if bs.get((s[0], s[1]), {}).get("block") != s[2]]
        if miss:
            print("   miss:", miss)
            miss_all += miss
    return miss_all


print("拆 (66,111) 带子:", a.confirm_broken([(66, 111)] if a.break_many([(66, 111)]) == [] else [], timeout=90))

S = []
# 煤柱改 router 链，多挂发电机
S += [(66, 111, "router", 0), (65, 111, "combustion-generator", 0), (66, 110, "router", 0)]
# 行B 接入通道
S += [(71, 115, "conveyor", 3)]
for x in range(65, 71):
    S.append((x, 116, "conveyor", 0))
S += [(65, 117, "mechanical-drill", 0), (67, 117, "mechanical-drill", 0), (69, 117, "mechanical-drill", 0)]
# 北侧煤簇 C：收集带 y=84 -> x=64 南下 -> 铜带 -> core
for x in range(64, 71):
    S.append((x, 84, "conveyor", 2))
S += [(69, 82, "conveyor", 1), (69, 83, "conveyor", 1)]
for y in range(85, 102):
    S.append((64, y, "conveyor", 1))
S += [(65, 80, "mechanical-drill", 0), (67, 80, "mechanical-drill", 0),
      (69, 80, "mechanical-drill", 0), (65, 82, "mechanical-drill", 0),
      (67, 82, "mechanical-drill", 0)]

print(f"建造 {len(S)} 项")
print("missing:", smart_place(S))
warp(61, 104)
print("done")
