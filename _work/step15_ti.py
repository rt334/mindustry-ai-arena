#!/usr/bin/env python3
"""阶段 15：开钛线（钛带 y=106 -> core 西侧），并把煤簇 C 的钻机升级为 pneumatic-drill。"""
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


# 先把旧钻机拆掉换成 pneumatic
old = [(65, 80), (67, 80), (69, 80), (65, 82), (67, 82)]
print("拆旧钻机:", a.confirm_broken(old, timeout=120) if a.break_many(old, workers=3) == [] else "err")

S = []
# 钛线
for x in range(36, 58):
    S.append((x, 106, "conveyor", 0))
S.append((58, 106, "conveyor", 0))
S += [(38, 102, "conveyor", 1), (38, 103, "conveyor", 1), (38, 104, "conveyor", 1), (38, 105, "conveyor", 1)]
S += [(36, 104, "pneumatic-drill", 0), (36, 101, "pneumatic-drill", 0)]
# 煤簇 C 升级
S += [(65, 80, "pneumatic-drill", 0), (67, 80, "pneumatic-drill", 0),
      (69, 80, "pneumatic-drill", 0), (65, 82, "pneumatic-drill", 0),
      (67, 82, "pneumatic-drill", 0)]
# 煤区行A 升级
old2 = [(65, 115), (67, 115), (69, 115)]
print("拆行A:", a.confirm_broken(old2, timeout=120) if a.break_many(old2, workers=3) == [] else "err")
S += [(65, 115, "pneumatic-drill", 0), (67, 115, "pneumatic-drill", 0), (69, 115, "pneumatic-drill", 0)]

print(f"建造 {len(S)} 项")
print("missing:", smart_place(S))
warp(61, 104)
bs = a.buildings()
print("core:", [b for b in bs.values() if b["block"] == "core-nucleus"][0]["items"])
print("drills:", sum(1 for b in bs.values() if b["block"].endswith("drill")))
