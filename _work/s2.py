#!/usr/bin/env python3
"""极简状态读数。"""
import sys, collections
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
bs = a.buildings()
core = [b for b in bs.values() if b["block"] == "core-nucleus"][0]
print("core:", core["items"])
print("counts:", dict(collections.Counter(b["block"] for b in bs.values())))
print("press:", [(k, b.get("items"), b.get("efficiency")) for k, b in bs.items() if b["block"] == "graphite-press"])
print("gen:", [(k, b.get("items"), b.get("efficiency")) for k, b in bs.items() if b["block"] == "combustion-generator"])
print("smelt:", [(k, b.get("items"), b.get("efficiency"), b.get("powerStatus")) for k, b in bs.items() if b["block"] == "silicon-smelter"])
print("queue:", a.queue()["builders"])
print("rates:", {k: round(s.get("perSecond", 0), 3) for k, s in (a.rates(window=12).get("stored") or {}).items()})
