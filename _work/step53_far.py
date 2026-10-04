#!/usr/bin/env python3
"""阶段 53：开发东北大煤簇（102..110,114..121，49 格）——本地压机 + 石墨长带回核心。

距离 45 格，直接运煤等于白送进核心；所以本地先把煤压成石墨，再用一条长带回核心。
"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221
bs = a.buildings()
# 先看这一带是否可建
ts = a.map(96, 112, 16, 12, view=None)
blocked = [(t["x"], t["y"], t["block"]) for t in ts if t.get("block") and t["block"] != "air" and t.get("build") is False]
print("不可建格:", blocked[:16], "总数", len(blocked))

S = []
# 收集带 y=122 向东? 煤簇 y=114..121，在南侧 y=122 铺收集带朝西
for x in range(96, 111):
    S.append((x, 122, "conveyor", 2))
# x=96 北上/西行到铅带：先北到 y=118 再西行
for y in range(119, 122):
    S.append((96, y, "conveyor", 3))
for x in range(76, 96):
    S.append((x, 118, "conveyor", 2))
# 本地压机（吃 y=122 收集带的煤）
S += [(97, 120, "graphite-press", 0), (99, 120, "graphite-press", 0)]
for y in range(119, 121):
    S.append((96, y, "conveyor", 3))
# 钻机
S += [(102, 114, "pneumatic-drill", 0), (104, 115, "pneumatic-drill", 0),
      (106, 115, "pneumatic-drill", 0), (105, 117, "pneumatic-drill", 0),
      (107, 117, "pneumatic-drill", 0), (108, 119, "pneumatic-drill", 0)]
print("下单", len(S), "errs:", a.place_many(S, workers=6))
for _ in range(40):
    for c in S[::4]:
        try:
            a.call("control", method="POST", op="warp", unit=UNIT, x=c[0], y=c[1])
        except Exception:
            pass
    time.sleep(0.25)
bs = a.buildings()
got = sum(1 for s in S if (s[0], s[1]) in bs)
print(f"建成 {got}/{len(S)}")
print("新钻机:", [(c, (bs.get(c) or {}).get("block")) for c in [(102, 114), (104, 115), (106, 115), (105, 117), (107, 117), (108, 119)]])
print("rates:", {k: round(s.get("perSecond", 0), 3) for k, s in (a.rates(window=15).get("stored") or {}).items()})
