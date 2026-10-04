#!/usr/bin/env python3
"""建造加速器：持续把建造单位 warp 到"正在建造中"的方块上（build* 占位）。

Mindustry 里单位必须在建造点附近才能推进进度，warp 省掉的就是跑路时间。
判据是 /buildings 里是否还有 build* 占位，不是时间。
"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221
deadline = time.time() + float(sys.argv[1] if len(sys.argv) > 1 else 300)

last = None
moves = 0
idle_rounds = 0
while time.time() < deadline:
    bs = a.buildings()
    pend = [k for k, b in bs.items() if b["block"].startswith("build")]
    if not pend:
        idle_rounds += 1
        if idle_rounds > 12:
            print("没有在建方块了（连续 12 次），停止")
            break
        time.sleep(0.7)
        continue
    idle_rounds = 0
    t = pend[0]
    if t != last:
        try:
            a.call("control", method="POST", op="warp", unit=UNIT, x=t[0], y=t[1])
            moves += 1
        except Exception as e:
            print("warp err:", e)
        last = t
    time.sleep(0.15)

bs = a.buildings()
core = [b for b in bs.values() if b["block"] == "core-nucleus"][0]
print("warp 次数:", moves)
print("core:", core["items"])
print("rates:", {k: round(s.get("perSecond", 0), 3) for k, s in (a.rates(window=15).get("stored") or {}).items()})
print("queue:", a.queue()["builders"])
