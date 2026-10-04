#!/usr/bin/env python3
"""阶段 18：加石墨压机 + 修煤道 + 补发电机。下单即走，不阻塞等建造完成。"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221

# 拆除与建造同时下发；/place 是排队的，返回成功只代表入队
dead = [(69, 117)]
print("break:", a.break_many(dead, workers=1))

S = []
# 煤柱纵向延伸：给第二台压机供煤
S += [(66, 117, "conveyor", 1), (66, 118, "router", 0), (67, 118, "conveyor", 0)]
# 两台石墨压机 + 产物上行
S += [(68, 116, "graphite-press", 0), (68, 118, "graphite-press", 0)]
S += [(70, 115, "conveyor", 3), (70, 116, "conveyor", 3),
      (70, 117, "conveyor", 3), (70, 118, "conveyor", 3)]
# 煤区行A 补钻机
S += [(67, 115, "mechanical-drill", 0)]
# 加一台发电机
S += [(67, 111, "combustion-generator", 0)]
# 北侧煤簇 C 南下链重建（x=64）
S += [(64, 84, "conveyor", 1)]
for y in range(85, 102):
    S.append((64, y, "conveyor", 1))

print(f"下单 {len(S)} 项")
errs = a.place_many(S, workers=6)
print("place errs:", errs)
print("queue:", a.queue())
bs = a.buildings()
print("core:", [b for b in bs.values() if b["block"] == "core-nucleus"][0]["items"])
