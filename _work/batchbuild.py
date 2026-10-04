#!/usr/bin/env python3
"""分批建造：服务端一次只接受约 27 个计划，其余会被丢弃 —— 所以按批下单并轮询队列。"""
import sys, json, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221


def warp(x, y):
    try:
        a.call("control", method="POST", op="warp", unit=UNIT, x=int(x), y=int(y))
    except Exception:
        pass


SPECS = []
# 簇 C 出口
SPECS += [(66, 82, "conveyor", 1), (66, 83, "conveyor", 1), (68, 82, "conveyor", 1), (68, 83, "conveyor", 1)]
# 簇 B 长带转向 + 压机
SPECS += [(56, 104, "conveyor", 1)] + [(56, y, "conveyor", 1) for y in range(105, 110)]
SPECS += [(57, 109, "conveyor", 0), (58, 109, "conveyor", 0), (59, 109, "graphite-press", 0)]
# 簇 B 新钻机 + 出口
SPECS += [(41, 101, "conveyor", 1), (41, 102, "conveyor", 1), (41, 103, "conveyor", 1), (40, 103, "conveyor", 1)]
SPECS += [(39, 100, "mechanical-drill", 0), (39, 102, "mechanical-drill", 0), (38, 104, "mechanical-drill", 0)]
# 簇 A 行B 出口 + 行A
SPECS += [(67, 116, "router", 0), (65, 116, "conveyor", 3), (65, 115, "conveyor", 3), (67, 115, "mechanical-drill", 0)]
# 压机煤路 + 第四台压机
SPECS += [(66, 117, "conveyor", 1), (66, 118, "router", 0), (67, 118, "conveyor", 0)]
SPECS += [(68, 116, "graphite-press", 0), (68, 118, "graphite-press", 0), (74, 110, "graphite-press", 0)]
SPECS += [(70, 115, "conveyor", 3), (70, 116, "conveyor", 3), (70, 117, "conveyor", 3), (70, 118, "conveyor", 3)]
# 北煤簇
SPECS += [(54, 84, "conveyor", 1), (52, 83, "mechanical-drill", 0), (53, 85, "mechanical-drill", 0)]
SPECS += [(55, 85, "conveyor", 0), (55, 86, "conveyor", 0)] + [(x, 85, "conveyor", 0) for x in range(55, 64)]
# 铜钻机
SPECS += [(68, 100, "mechanical-drill", 2), (70, 100, "mechanical-drill", 2)]

BATCH = 14
for i in range(0, len(SPECS), BATCH):
    sub = SPECS[i:i + BATCH]
    a.place_many(sub, workers=4)
    warp(sum(s[0] for s in sub) / len(sub), sum(s[1] for s in sub) / len(sub))
    # 轮询：等队列至少被消化一部分（或该批建成），最多 90 秒
    t0 = time.time()
    while time.time() - t0 < 90:
        bs = a.buildings()
        if all((s[0], s[1]) in bs for s in sub):
            break
        if a.queue()["builders"][0]["plans"] <= 4:
            break
        time.sleep(1.0)
    print(f"批 {i//BATCH}: done")
json.dump([[s[0], s[1]] for s in SPECS], open(r"C:\dsh\ai-arena\_work\pending.json", "w"))
bs = a.buildings()
print("core:", [b for b in bs.values() if b["block"] == "core-nucleus"][0]["items"])
print("queue:", a.queue()["builders"])
