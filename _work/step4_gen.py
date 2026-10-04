#!/usr/bin/env python3
"""判定实验：煤钻机直接推煤入 combustion-generator，绕开传送带。

判据：发电机 /buildings 里的 items 是否出现 coal（轮询），以及 efficiency。
"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)

# 煤钻机 (66,114) rot=3 的输出格已实测为 (66,113)
dead = [(66, 113), (60, 110), (60, 109)]
errs = a.break_many(dead, workers=3)
print("break errs:", errs, "->", a.confirm_broken(dead, timeout=90))

specs = [(66, 113, "combustion-generator", 0)]
print("place errs:", a.place_many(specs, workers=1))
got, missing = a.confirm_placed(specs, timeout=120)
print("placed:", len(got), "missing:", missing)

t0 = time.time()
first = None
while time.time() - t0 < 90:
    b = a.building_at(66, 113)
    if b and (b.get("items") or {}).get("coal"):
        first = (round(time.time() - t0, 1), b.get("items"), b.get("efficiency"), b.get("powerStatus"))
        break
    time.sleep(0.3)

print("发电机首次出现煤:", first)
b = a.building_at(66, 113)
print("发电机现状:", {k: b.get(k) for k in ("block", "items", "efficiency", "powerStatus", "powerLinks", "powerLinksHidden")} if b else None)
print("煤钻机:", {k: a.building_at(66, 114).get(k) for k in ("items", "efficiency")})
