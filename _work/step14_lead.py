#!/usr/bin/env python3
"""阶段 14：开铅线（南侧铅簇经 x=75 北上汇入汇流带）+ 延长汇流带。"""
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


S = []
# 汇流带东延到 x=75
for x in range(71, 76):
    S.append((x, 108, "conveyor", 2))
# 铅收集带 y=126 朝东到 x=75
for x in range(64, 76):
    S.append((x, 126, "conveyor", 0))
# x=75 北上
for y in range(109, 127):
    S.append((75, y, "conveyor", 3))
# 铅钻机与其接入
S += [(65, 122, "conveyor", 1), (65, 123, "conveyor", 1), (65, 124, "conveyor", 1), (65, 125, "conveyor", 1),
      (69, 123, "conveyor", 1), (69, 124, "conveyor", 1), (69, 125, "conveyor", 1)]
S += [(66, 122, "mechanical-drill", 0), (67, 124, "mechanical-drill", 0),
      (68, 121, "mechanical-drill", 0)]

print(f"建造 {len(S)} 项")
print("missing:", smart_place(S))
warp(61, 104)
time.sleep(0)  # no fixed wait: 下面用轮询判断铅是否产出

bs = a.buildings()
core = [b for b in bs.values() if b["block"] == "core-nucleus"][0]
print("core:", core["items"])
print("counts:", {k: sum(1 for b in bs.values() if b["block"] == k) for k in
                  ('mechanical-drill', 'conveyor', 'combustion-generator', 'graphite-press', 'silicon-smelter')})
