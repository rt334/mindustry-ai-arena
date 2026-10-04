#!/usr/bin/env python3
"""阶段 32：重置建造队列，只保留「解锁链」上的关键项。

理由：队列里 95 个计划里有 79 个是远期煤线，占满建造带宽；
真正的解锁链是 太阳能(电) -> 压机(石墨) -> 更好钻机(煤/铜/铅/钛)。
"""
import sys, json, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
print("清空队列:", a.call("queue", method="POST", clear="true"))
time.sleep(2)
print("queue now:", a.queue()["builders"])

S = []
# 1) 太阳能阵列 + 电网
for x in range(48, 56):
    for y in range(105, 109):
        S.append((x, y, "solar-panel", 0))
S += [(51, 107, "power-node", 0), (56, 108, "power-node", 0),
      (61, 109, "power-node", 0), (63, 110, "power-node", 0)]
# 2) 簇 C 两台 pneumatc 钻机出口
S += [(66, 82, "conveyor", 1), (66, 83, "conveyor", 1),
      (68, 82, "conveyor", 1), (68, 83, "conveyor", 1)]
# 3) 簇 B：长带转向 + 钻机出口 + 新钻机
S += [(56, 104, "conveyor", 1)]
for y in range(105, 110):
    S.append((56, y, "conveyor", 1))
S += [(57, 109, "conveyor", 0), (58, 109, "conveyor", 0), (59, 109, "graphite-press", 0)]
S += [(41, 101, "conveyor", 1), (41, 102, "conveyor", 1), (41, 103, "conveyor", 1), (40, 103, "conveyor", 1)]
S += [(39, 100, "mechanical-drill", 0), (39, 102, "mechanical-drill", 0), (38, 104, "mechanical-drill", 0)]
# 4) 簇 A：行B 两台钻机出口 + 行A 补钻机
S += [(67, 116, "router", 0), (65, 116, "conveyor", 3), (65, 115, "conveyor", 3),
      (67, 115, "mechanical-drill", 0)]
# 5) 压机煤路 + 第三台压机
S += [(66, 117, "conveyor", 1), (66, 118, "router", 0), (67, 118, "conveyor", 0),
      (68, 116, "graphite-press", 0), (68, 118, "graphite-press", 0),
      (70, 115, "conveyor", 3), (70, 116, "conveyor", 3), (70, 117, "conveyor", 3), (70, 118, "conveyor", 3),
      (74, 110, "graphite-press", 0)]
# 6) 北煤簇延伸
S += [(54, 84, "conveyor", 1), (52, 83, "mechanical-drill", 0), (53, 85, "mechanical-drill", 0)]
S += [(55, 85, "conveyor", 0), (55, 86, "conveyor", 0)]
for x in range(55, 64):
    S.append((x, 85, "conveyor", 0))
# 7) 铜钻机补位
S += [(68, 100, "mechanical-drill", 2), (70, 100, "mechanical-drill", 2)]

print("重下", len(S))
print("errs:", a.place_many(S, workers=6))
json.dump([[s[0], s[1]] for s in S], open(r"C:\dsh\ai-arena\_work\pending.json", "w"))
print("queue:", a.queue()["builders"])
