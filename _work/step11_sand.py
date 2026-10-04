#!/usr/bin/env python3
"""阶段 11：补 (68,113) 断点 + 铺沙带 y=112（x35..62 朝东）+ 6 台沙钻机。

沙是当前最大瓶颈：熔炉要 3 sand/s，而单台沙钻机（2 格）只有 0.2/s。
"""
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


def smart_place(specs, batch=8, timeout=180):
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


print("拆原沙钻机:", a.break_many([(61, 110)], workers=1))
print("  cleared:", a.confirm_broken([(61, 110)], timeout=90))

S = [(68, 113, "conveyor", 2)]
for x in range(35, 63):
    S.append((x, 112, "conveyor", 0))
for x in (35, 37, 39, 56, 58, 60):
    S.append((x, 110, "mechanical-drill", 0))

print(f"建造 {len(S)} 项")
print("missing:", smart_place(S))
warp(61, 104)

# 轮询到沙带出现物品
t0 = time.time()
hit = None
while time.time() - t0 < 90:
    bs = a.buildings()
    for x in range(35, 63):
        it = (bs.get((x, 112)) or {}).get("items") or {}
        if it:
            hit = (x, it)
            break
    if hit:
        break
    time.sleep(0.5)
print("沙带首次出现物品:", hit)

t0 = time.time()
best = {}
while time.time() - t0 < 150:
    st = a.rates(window=15).get("stored") or {}
    v = {k: s.get("perSecond", 0) for k, s in st.items()}
    for k, x in v.items():
        if abs(x) > abs(best.get(k, 0)):
            best[k] = x
    if v.get("silicon", 0) > 0.3 and v.get("sand", 0) >= 0:
        break
    time.sleep(1.0)
print("rates:", {k: round(s.get("perSecond", 0), 3) for k, s in (a.rates(window=15).get("stored") or {}).items()})
print("peak:", {k: round(v, 3) for k, v in best.items()})
print("core:", [b for b in a.buildings().values() if b["block"] == "core-nucleus"][0]["items"])
print("stalls:", [(s['x'], s['y'], s['block'], s['kind'], s.get('missing')) for s in a.stalls() if s.get('team') == 'sharded'])
