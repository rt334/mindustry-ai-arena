#!/usr/bin/env python3
"""阶段 17：煤柱纵向 router 链分煤，沿线挂多台石墨压机。"""
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


def smart_place(specs, batch=8, timeout=240):
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


# (66,116) 由带子改 router
print("改 (66,116):", a.break_many([(66, 116)], workers=1), a.confirm_broken([(66, 116)], timeout=90))

S = [
    (66, 116, "router", 0),
    (66, 117, "conveyor", 1),
    (66, 118, "router", 0),
    (67, 116, "conveyor", 0),
    (67, 118, "conveyor", 0),
    (68, 116, "graphite-press", 0),
    (68, 118, "graphite-press", 0),
    (69, 116, "conveyor", 3),
    (69, 117, "conveyor", 3),
    (69, 118, "conveyor", 3),
    (69, 115, "conveyor", 3),
]
print(f"建造 {len(S)}")
print("missing:", smart_place(S))
warp(61, 104)

t0 = time.time()
while time.time() - t0 < 120:
    v = {k: s.get("perSecond", 0) for k, s in (a.rates(window=15).get("stored") or {}).items()}
    if v.get("graphite", 0) > 0.3:
        break
    time.sleep(1.0)
print("rates:", {k: round(s.get("perSecond", 0), 3) for k, s in (a.rates(window=15).get("stored") or {}).items()})
print("core:", [b for b in a.buildings().values() if b["block"] == "core-nucleus"][0]["items"])
print("stalls:", [(s['x'], s['y'], s['block'], s['kind'], s.get('missing')) for s in a.stalls() if s.get('team') == 'sharded'])
