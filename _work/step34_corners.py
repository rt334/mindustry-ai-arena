#!/usr/bin/env python3
"""阶段 34：系统修正「拐弯死结」。

规则：传送带只从背面收料，所以链上每个拐弯点都必须换成 router（router 收任意方向）。
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


corners = [(41, 98), (41, 104), (66, 84), (68, 84), (69, 84), (38, 106), (54, 85)]
have = [c for c in corners if c in a.buildings()]
print("拆拐弯带子:", have)
a.break_many(have, workers=3)
t0 = time.time()
while time.time() - t0 < 60:
    if not [c for c in have if c in a.buildings()]:
        break
    time.sleep(0.5)

S = [(c[0], c[1], "router", 0) for c in corners]
# 钛带在 router 之后要重新接续：(39,106) 保持原带
print("下单 router:", len(S), "errs:", a.place_many(S, workers=3))
for _ in range(3):
    for c in corners:
        warp(c[0], c[1])
        time.sleep(0.2)

cur = [tuple(p) for p in json.load(open(P))]
cur += corners
json.dump([list(p) for p in dict.fromkeys(cur)], open(P, "w"))
print("queue:", a.queue()["builders"])
