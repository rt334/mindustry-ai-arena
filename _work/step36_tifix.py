#!/usr/bin/env python3
"""阶段 36：修「煤改道链压掉了钛带」的冲突。

(56,106) 原本是钛带的一格，被簇 B 煤改道链占成 rot=1，钛带整条断在 x=56。
把改道链挪到 x=55，恢复 (56,106) 为钛带。
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


dead = [(56, y) for y in range(104, 109)]
print("拆煤改道链:", dead, a.break_many(dead, workers=3))
t0 = time.time()
while time.time() - t0 < 90:
    if not [c for c in dead if c in a.buildings()]:
        break
    time.sleep(0.5)

S = [(56, 104, "conveyor", 0)]           # 恢复钛带方向占位（实际会被 55,104 送入）
S += [(55, 104, "conveyor", 1)]
for y in range(105, 110):
    S.append((55, y, "conveyor", 1))
S += [(56, 106, "conveyor", 0), (56, 107, "conveyor", 0), (56, 108, "conveyor", 0)]
print("下单", len(S), "errs:", a.place_many(S, workers=4))
for c in S:
    warp(c[0], c[1])
    time.sleep(0.15)

cur = [tuple(p) for p in json.load(open(P))]
cur += [(s[0], s[1]) for s in S]
json.dump([list(p) for p in dict.fromkeys(cur)], open(P, "w"))
print("queue:", a.queue()["builders"])
