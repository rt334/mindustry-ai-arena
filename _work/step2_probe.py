#!/usr/bin/env python3
"""阶段 2：探针实验 —— 确定 drill 的输出格语义（rot 朝向哪一格出货）。

三台钻机各摆一个 rot，两侧邻格都铺带子并把末端留空（会堆料），
谁先拿到 items 谁就是输出格。判据是 /buildings 里的 items，不是时间。
"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)

print("== 拆除旧钻机（重摆 rot） ==")
errs = a.break_many([(61, 108), (66, 114)], workers=2)
print(" break errs:", errs)
print(" broken:", a.confirm_broken([(61, 108), (66, 114)], timeout=90))

specs = [
    # 铜：钻机 (68,101) 朝西，西邻两格都放带子
    (68, 101, "mechanical-drill", 2),
    (67, 101, "conveyor", 2),
    (67, 102, "conveyor", 2),
    # 煤：钻机 (66,114) 朝北，北邻两格都放带子
    (66, 114, "mechanical-drill", 3),
    (66, 113, "conveyor", 3),
    (67, 113, "conveyor", 3),
    # 沙：钻机 (61,108) 朝西，西邻两格都放带子
    (61, 108, "mechanical-drill", 2),
    (60, 108, "conveyor", 2),
    (60, 109, "conveyor", 2),
]
errs = a.place_many(specs, workers=4)
print(" place errs:", errs)
got, missing = a.confirm_placed(specs, timeout=180)
print(f" placed {len(got)}/{len(specs)}  missing={missing}")

# 轮询观察：谁的 items 先非空
def probe():
    bs = a.buildings()
    return {k: v.get("items") for k, v in bs.items()
            if k in [(67, 101), (67, 102), (66, 113), (67, 113), (60, 108), (60, 109)]}

t0 = time.time()
seen = {}
while time.time() - t0 < 60:
    cur = probe()
    for k, v in cur.items():
        if v and k not in seen:
            seen[k] = (round(time.time() - t0, 1), v)
    if len(seen) >= 3:
        break
    time.sleep(0.4)

print("== 首次拿到物品的带子（输出格） ==")
for k, v in sorted(seen.items()):
    print(f"  {k} -> {v}")
print()
bs = a.buildings()
for k in [(68, 101), (67, 101), (67, 102), (66, 114), (66, 113), (67, 113),
          (61, 108), (60, 108), (60, 109)]:
    b = bs.get(k)
    print(f"  {k} {b['block'] if b else '-'} rot={b.get('rotation') if b else '-'} "
          f"eff={b.get('efficiency') if b else '-'} items={b.get('items') if b else '-'}")
