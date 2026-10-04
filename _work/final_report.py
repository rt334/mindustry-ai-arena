#!/usr/bin/env python3
"""最终盘点：目标产物的当前净产出、关键瓶颈、建筑规模。"""
import sys, collections
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
bs = a.buildings()
core = [b for b in bs.values() if b["block"] == "core-nucleus"][0]
st = a.state()
print(f"tick={st['tick']}  playing={st['playing']}")
print("core:", core["items"])
print("counts:", dict(collections.Counter(b["block"] for b in bs.values())))
r = {k: s.get("perSecond", 0) for k, s in (a.rates(window=30).get("stored") or {}).items()}
print("rates:", {k: round(v, 3) for k, v in r.items()})
tgt = ["copper", "lead", "silicon", "titanium", "graphite"]
print()
for t in tgt:
    v = r.get(t, 0)
    print(f"  {t:<9} {v:7.3f} /s   {'达标' if v >= 5 else f'差 {5 - v:.2f}'}")
blk = [(s["x"], s["y"], s["block"], list((s.get('items') or {}).keys())) for s in a.stalls() if s.get("team") == "sharded" and s["kind"] == "drillBlocked"]
print("\n堵塞钻机:", blk)
stalls = [s for s in a.stalls() if s.get("team") == "sharded" and s["kind"] != "drillBlocked"]
print("其它异常数:", len(stalls))
print("press:", [(k, b.get("items"), b.get("efficiency")) for k, b in bs.items() if b["block"] == "graphite-press"])
print("gens:", [(k, b.get("items"), b.get("efficiency")) for k, b in bs.items() if b["block"] == "combustion-generator"])
print("smelters:", [(k, b.get("items"), b.get("powerStatus")) for k, b in bs.items() if b["block"] == "silicon-smelter"])
print("solar:", sum(1 for b in bs.values() if b["block"] == "solar-panel"))
