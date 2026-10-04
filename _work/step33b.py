#!/usr/bin/env python3
"""阶段 33：修钛线出口（router 链，避开「带子只认背面」的死结）+ 补缺失的煤出口带。"""
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
    (66, 82, "conveyor", 1), (66, 83, "conveyor", 1),
    (68, 82, "conveyor", 1), (68, 83, "conveyor", 1),
    (66, 117, "conveyor", 1), (66, 118, "router", 0),
]
print("下单", len(S), "errs:", a.place_many(S, workers=4))
for _ in range(4):
    warp(38, 104)
    time.sleep(0.2)
    warp(66, 83)
    time.sleep(0.2)

cur = [tuple(p) for p in json.load(open(P))]
cur += [(s[0], s[1]) for s in S]
json.dump([list(p) for p in dict.fromkeys(cur)], open(P, "w"))
print("queue:", a.queue()["builders"])
print("core:", [b for b in a.buildings().values() if b["block"] == "core-nucleus"][0]["items"])
