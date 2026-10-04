#!/usr/bin/env python3
"""阶段 29：把有限的煤优先给石墨压机——拆掉 3 台抢煤的发电机，只留 (65,114)。"""
import sys
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
dead = [(65, 110), (65, 111), (67, 111)]
print("拆发电机:", a.break_many(dead, workers=3))
print("queue:", a.queue()["builders"])
print("core:", [b for b in a.buildings().values() if b["block"] == "core-nucleus"][0]["items"])
