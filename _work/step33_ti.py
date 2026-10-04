#!/usr/bin/env python3
"""阶段 33：修钛线出口（router 链，避开「带子只认背面」的死结）+ 补缺失的煤出口带。"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA
from order import order

a = Arena("alpha", ALPHA)
UNIT = 221


def warp(x, y):
    try:
        a.call("control", method="POST", op="warp", unit=UNIT, x=int(x), y=int(y))
    except Exception:
        pass


dead = [(38, 102), (38, 103), (38, 104), (38, 105)]
print("拆钛接入:", a.break_many(dead, workers=2))
t0 = time.time()
while time.time() - t0 < 60:
    if not [c for c in dead if c in a.buildings()]:
        break
    time.sleep(0.5)

S = [
    (38, 102, "router", 0), (38, 103, "router", 0), (38, 104, "router", 0),
    (38, 105, "conveyor", 1),
    # 簇 C 缺失的四条出口带
    (66, 82, "conveyor", 1), (66, 83, "conveyor", 1),
    (68, 82, "conveyor", 1), (68, 83, "conveyor", 1),
    # 压机煤路缺的两格
    (66, 117, "conveyor", 1), (66, 118, "router", 0),
]
print("下单", len(S))
a.place_many(S, workers=4)
warp(38, 104)
warp(66, 83)
order([], "登记")
import json
cur = json.load(open(r"C:\dsh\ai-arena\_work\pending.json"))
cur += [[s[0], s[1]] for s in S] + [[c[0], c[1]] for c in dead]
json.dump(list({tuple(p) for p in cur}), open(r"C:\dsh\ai-arena\_work\pending.json", "w"), default=list)
print("queue:", a.queue()["builders"])
