#!/usr/bin/env python3
"""堵点诊断：列出所有堵塞的钻机及其缺口。"""
import sys
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
st = [s for s in a.stalls() if s.get("team") == "sharded"]
blk = [s for s in st if s["kind"] == "drillBlocked"]
print(f"drillBlocked = {len(blk)}")
for s in blk:
    print(f"  {s['block']:<18} ({s['x']:>3},{s['y']:>3}) items={s.get('items')}")
print("其他堵塞:", [(s['x'], s['y'], s['block'], s['kind']) for s in st if s['kind'] != 'drillBlocked'][:20])
print("queue:", a.queue()["builders"])
