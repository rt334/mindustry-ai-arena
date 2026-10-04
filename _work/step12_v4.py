#!/usr/bin/env python3
"""阶段 12：清场 + v4 主布局（汇流带/沙带/煤柱/煤区/铜带）+ 西侧煤簇长带。"""
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


def smart_place(specs, batch=8, timeout=200):
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


bs = a.buildings()
victims = [k for k, b in bs.items() if b["block"] != "core-nucleus"]
print(f"清场 {len(victims)}")
a.break_many(victims, workers=6)
print("  cleared:", a.confirm_broken(victims, timeout=400)[0])
warp(61, 104)

S = []
# 汇流带 y=108 -> core
for x in range(59, 71):
    S.append((x, 108, "conveyor", 2))
S += [(59, 108, "conveyor", 3), (59, 107, "conveyor", 3)]
# 硅
S += [(63, 111, "silicon-smelter", 0), (64, 110, "conveyor", 3), (64, 109, "conveyor", 3)]
# 沙带 y=112 朝东 + 沙钻机
for x in range(35, 63):
    S.append((x, 112, "conveyor", 0))
for x in (35, 37, 39, 56, 58, 60):
    S.append((x, 110, "mechanical-drill", 0))
# 煤柱 x=66（y109-113）
S += [(66, 113, "router", 0), (66, 112, "router", 0), (66, 111, "conveyor", 3),
      (66, 110, "router", 0), (66, 109, "conveyor", 3)]
# 煤分配 + 电
S += [(65, 112, "conveyor", 2), (65, 110, "combustion-generator", 0),
      (67, 112, "combustion-generator", 0), (67, 110, "conveyor", 0),
      (64, 112, "power-node", 0), (65, 113, "power-node", 0),
      (65, 111, "power-node", 0), (65, 109, "power-node", 0)]
# 煤区：干线 y=113 / 收集带 y=114 / 行A / 行B
for x in range(67, 74):
    S.append((x, 113, "conveyor", 2))
for x in range(67, 75):
    S.append((x, 114, "conveyor", 2))
S.append((66, 114, "conveyor", 3))
S += [(65, 115, "mechanical-drill", 0), (67, 115, "mechanical-drill", 0),
      (69, 115, "mechanical-drill", 0)]
S += [(71, 117, "mechanical-drill", 0), (71, 116, "conveyor", 3), (72, 116, "conveyor", 3)]
# 石墨
S += [(68, 110, "graphite-press", 0), (69, 109, "conveyor", 3)]
# 铜带 + 铜钻机
for x in range(64, 74):
    S.append((x, 102, "conveyor", 2))
S += [(67, 103, "conveyor", 3), (69, 103, "conveyor", 3)]
S += [(68, 100, "mechanical-drill", 0), (70, 100, "mechanical-drill", 0),
      (72, 100, "mechanical-drill", 0), (67, 104, "mechanical-drill", 0),
      (69, 104, "mechanical-drill", 0)]
# 西煤簇 B：长带 y=104 x=40..58 -> core
for x in range(40, 59):
    S.append((x, 104, "conveyor", 0))
S += [(40, 98, "conveyor", 0), (41, 98, "conveyor", 1)]
for y in range(99, 104):
    S.append((41, y, "conveyor", 1))
S += [(40, 102, "conveyor", 1), (40, 103, "conveyor", 1)]
S += [(38, 97, "mechanical-drill", 0), (39, 101, "mechanical-drill", 0)]

print(f"建造 {len(S)} 项")
print("missing:", smart_place(S, batch=10))
warp(61, 104)
print("done")
