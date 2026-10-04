#!/usr/bin/env python3
"""煤钻机通畅性总账 + 目标差距。"""
import sys
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
bs = a.buildings()
core = [b for b in bs.values() if b["block"] == "core-nucleus"][0]
print("core:", core["items"])
rows = []
for k, b in sorted(bs.items()):
    if b["block"].endswith("drill"):
        it = b.get("items") or {}
        eff = b.get("efficiency") or 0
        rows.append((k, b["block"][:16], eff, it))
print(f"钻机 {len(rows)}:")
for k, blk, eff, it in rows:
    flag = "堵" if eff == 0 else "ok"
    print(f"   {k} {blk:<16} {flag} {it}")
r = {k: s.get("perSecond", 0) for k, s in (a.rates(window=25).get("stored") or {}).items()}
print("rates:", {k: round(v, 3) for k, v in r.items()})
for t in ["copper", "lead", "silicon", "titanium", "graphite"]:
    print(f"  {t:<9} {r.get(t, 0):7.3f} /s")
