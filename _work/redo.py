#!/usr/bin/env python3
"""分批补单：把 pending.json 里尚未建成的坐标按批重下（服务端一次只吃 ~27 个计划）。"""
import sys, json, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
pend = json.load(open(r"C:\dsh\ai-arena\_work\pending.json"))
spec = json.load(open(r"C:\dsh\ai-arena\_work\specs.json")) if len(sys.argv) > 2 else None
bs = a.buildings()
todo = [tuple(p) for p in pend if tuple(p) not in bs]
print("未建成:", len(todo))
print(todo[:30])
