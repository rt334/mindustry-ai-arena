#!/usr/bin/env python3
"""阶段 21：补北侧煤簇 C 各钻机的出口通路；随后 warp 建造单位到该区加速。"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221

S = [
    (66, 82, "conveyor", 1), (66, 83, "conveyor", 1),
    (68, 82, "conveyor", 1), (68, 83, "conveyor", 1),
]
print("下单:", [s[:2] for s in S])
print("errs:", a.place_many(S, workers=2))

# 把建造单位拉到北侧煤簇，缩短它跑路时间
for _ in range(3):
    try:
        a.call("control", method="POST", op="warp", unit=UNIT, x=66, y=84)
    except Exception as e:
        print("warp err:", e)
    time.sleep(0.2)

t0 = time.time()
last = None
while time.time() - t0 < 60:
    bs = a.buildings()
    got = [b["block"] for k, b in bs.items() if k in [(66, 82), (66, 83), (68, 82), (68, 83)]]
    if len(got) == 4:
        print("通路已建成")
        break
    time.sleep(0.5)
print("queue:", a.queue()["builders"])
