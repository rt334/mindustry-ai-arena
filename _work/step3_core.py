#!/usr/bin/env python3
"""阶段 3：搭第一条最小回路并测速。

布局（rot: 0=东 1=南 2=西 3=北）
  铜：(68,101)钻 rot=2 -> (67,102) 起 y=102 向西 -> (64,102) 注入 core
  煤：(66,114)钻 rot=3 -> (66,113)->(66,112) 北行 -> (66,111) 转西 -> y=111 向西
      -> (60,111) router -> 北 (60,110)->(60,109) 发电机
                        -> 西 (59,111) 北行 -> 硅熔炉
  硅：熔炉 (58,109) rot=3 输出北 -> (58,108)->(58,107) 北行 -> (58,106) 东行 -> core
      沙：(61,108)钻 rot=2 -> (60,108) 西行 -> (59,108) 南行 -> 熔炉
"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)

print("== 拆掉多余探针带子与旧熔炉 ==")
dead = [(67, 101), (60, 109), (67, 113), (64, 104)]
errs = a.break_many(dead, workers=4)
print("  errs:", errs)
print("  broken:", a.confirm_broken(dead, timeout=90))

specs = [
    # ---- 铜线 ----
    (66, 102, "conveyor", 2),
    (65, 102, "conveyor", 2),
    (64, 102, "conveyor", 2),
    # ---- 煤线 ----
    (66, 112, "conveyor", 3),
    (66, 111, "conveyor", 2),
    (65, 111, "conveyor", 2),
    (64, 111, "conveyor", 2),
    (63, 111, "conveyor", 2),
    (62, 111, "conveyor", 2),
    (61, 111, "conveyor", 2),
    (60, 111, "router", 0),
    (60, 110, "conveyor", 3),
    (60, 109, "combustion-generator", 0),
    (59, 111, "conveyor", 3),
    # ---- 硅熔炉 + 沙线 ----
    (58, 109, "silicon-smelter", 3),
    (59, 108, "conveyor", 1),
    (58, 108, "conveyor", 3),
    (58, 107, "conveyor", 3),
    (58, 106, "conveyor", 0),
]
errs = a.place_many(specs, workers=4)
print("place errs:", errs)
got, missing = a.confirm_placed(specs, timeout=300)
print(f"placed {len(got)}/{len(specs)} missing={missing}")

print()
print("== 现场 ==")
bs = a.buildings()
for k in sorted(bs):
    b = bs[k]
    print(f"  {b['block']:<20} ({k[0]:>3},{k[1]:>3}) rot={b.get('rotation')} eff={b.get('efficiency')} "
          f"items={b.get('items')} pow={b.get('powerStatus')} links={b.get('powerLinks')}")
print("queue:", a.queue())
print("rates:", a.rates(window=12).get("stored"))
print("stalls:", [(s['x'], s['y'], s['kind'], s.get('missing')) for s in a.stalls()[:12]])
