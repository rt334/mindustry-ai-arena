#!/usr/bin/env python3
"""阶段 1：清理旧布局（拆传送带 / 发电机 / 路由器），保留核心、2 台钻机、硅熔炉。

判据：/buildings（拆完后再查），不用固定等待。
"""
import sys, json, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)

bl = a.buildings()
core_before = [b for b in bl.values() if b["block"] == "core-nucleus"][0]
print("core before:", core_before["items"])

victims = [(x, y) for (x, y), b in bl.items() if b["block"] in ("conveyor", "combustion-generator", "router")]
print("拆:", len(victims), "个")

errs = a.break_many(victims, workers=6)
print("下单错误:", errs)

ok, left = a.confirm_broken(victims, timeout=180)
print("全部拆除:", ok, " 残留:", left)

bl2 = a.buildings()
core_after = [b for b in bl2.values() if b["block"] == "core-nucleus"][0]
print("core after :", core_after["items"])
print("剩余建筑:", json.dumps({k: v for k, v in sorted(bl2.items()) and bl2.items()}, default=str)[:2000])
print("剩余清单:")
for (x, y), b in sorted(bl2.items(), key=lambda kv: (kv[1]["block"], kv[0][1], kv[0][0])):
    print(f"  {b['block']:<20} ({x:>3},{y:>3}) rot={b.get('rotation')} eff={b.get('efficiency')} items={b.get('items')}")
print("queue:", a.queue())
