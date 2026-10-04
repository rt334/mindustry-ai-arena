#!/usr/bin/env python3
"""阶段 38：钛带接入点改成 router（紧邻钻机），并查游戏进度。"""
import sys, time, json
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221
st = a.state()
print("tick:", st["tick"], "playing:", st["playing"], "wave:", st.get("wave"), "teams:", [(t["name"], t["cores"]) for t in st["teams"]])

dead = [(36, 106)]
print("拆:", a.break_many(dead, workers=1))
t0 = time.time()
while time.time() - t0 < 60:
    if (36, 106) not in a.buildings():
        break
    time.sleep(0.4)
S = [(36, 106, "router", 0)]
print("下单:", a.place_many(S, workers=1))
for _ in range(5):
    try:
        a.call("control", method="POST", op="warp", unit=UNIT, x=36, y=106)
    except Exception:
        pass
    time.sleep(0.2)
bs = a.buildings()
print("(36,106):", bs.get((36, 106)))
print("drills:", [(k, b.get("items")) for k, b in bs.items() if b["block"].endswith("drill") and k[0] < 45])
