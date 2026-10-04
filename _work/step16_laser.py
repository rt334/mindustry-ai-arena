#!/usr/bin/env python3
"""阶段 16：补回煤钻机 + 新增石墨压机（router 分煤）+ 首台 laser-drill 上铜线。"""
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


def smart_place(specs, batch=10, timeout=240):
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


# 铜区：拆两台机械钻，腾位给 3x3 laser-drill
old = [(68, 100), (70, 100)]
print("拆铜钻机:", a.break_many(old, workers=2), a.confirm_broken(old, timeout=90))

S = []
# 煤区：收集带入口改 router，向下一层分煤
S += [(66, 114, "router", 0), (66, 115, "conveyor", 1), (66, 116, "conveyor", 1),
      (67, 116, "conveyor", 0)]
S += [(68, 116, "graphite-press", 0), (69, 115, "conveyor", 3)]
# 补回一台煤钻机
S += [(65, 115, "mechanical-drill", 0)]
# 铜：laser-drill
S += [(68, 100, "laser-drill", 0), (70, 103, "conveyor", 3)]

print(f"建造 {len(S)} 项")
print("missing:", smart_place(S))
warp(61, 104)
bs = a.buildings()
print("core:", [b for b in bs.values() if b["block"] == "core-nucleus"][0]["items"])
