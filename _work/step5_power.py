#!/usr/bin/env python3
"""判定实验：电力网络连接规则。

假设 A：直接相邻的 power 方块自动并网
假设 B：必须 power-node 才连
判据：silicon-smelter 的 powerStatus / efficiency（轮询，不睡固定时长）。
"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)

# 先清掉孤立熔炉
dead = [(58, 109), (64, 107)]
print("break errs:", a.break_many(dead, workers=2))
print("broken:", a.confirm_broken(dead, timeout=90))

# 发电机在 (66,113) 且已经在烧煤。把熔炉直接贴在它东侧。
specs = [(68, 113, "silicon-smelter", 0)]
print("place errs:", a.place_many(specs, workers=1))
got, missing = a.confirm_placed(specs, timeout=120)
print("placed:", len(got), "missing:", missing)

for i in range(20):
    b = a.building_at(68, 113)
    g = a.building_at(66, 113)
    if b and g:
        print(f"[{i}] gen eff={g.get('efficiency')} items={g.get('items')} pow={g.get('powerStatus')} links={g.get('powerLinks')}")
        print(f"    smelt eff={b.get('efficiency')} pow={b.get('powerStatus')} items={b.get('items')} links={b.get('powerLinks')}")
    time.sleep(0.8)
    if i >= 6 and b and (b.get("powerStatus") or 0) > 0:
        print(">>> 相邻即并网：powerStatus > 0")
        break
