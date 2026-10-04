#!/usr/bin/env python3
"""阶段 35：把 router 链改回直线（router 只在拐弯处用一格），并补钻机正对出口格。

教训：纵向直线段上的每一格都应该是 conveyor rot=1；插 router 只会把吞吐砍成 1/格。
另外，钻机只往「正对输出侧」的两个邻格推货，出口链首格必须落在那里。
"""
import sys, time, json
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221
P = r"C:\dsh\ai-arena\_work\pending.json"


def warp(x, y):
    try:
        a.call("control", method="POST", op="warp", unit=UNIT, x=int(x), y=int(y))
    except Exception:
        pass


# (38,103)/(38,104) 现在是 router，改回直线带
dead = [(38, 103), (38, 104)]
print("拆:", a.break_many(dead, workers=2))
t0 = time.time()
while time.time() - t0 < 60:
    if not [c for c in dead if c in a.buildings()]:
        break
    time.sleep(0.5)

S = [
    (38, 103, "conveyor", 1), (38, 104, "conveyor", 1),
    # (39,100) 钻机正对出口格
    (41, 100, "router", 0),
    # (52,83) 钻机 -> 54,84 拐弯点
    (54, 85, "router", 0),
]
print("下单", len(S), "errs:", a.place_many(S, workers=3))
for c in S:
    warp(c[0], c[1])
    time.sleep(0.2)

cur = [tuple(p) for p in json.load(open(P))]
cur += [(s[0], s[1]) for s in S]
json.dump([list(p) for p in dict.fromkeys(cur)], open(P, "w"))
print("queue:", a.queue()["builders"])
