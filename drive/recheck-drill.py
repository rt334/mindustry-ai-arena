#!/usr/bin/env python3
"""快速回读：钻机的 sendsTo 有没有跟上新放的带子。"""
import json
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])

st = a.state()
print(f"snapshotFresh={st.get('snapshotFresh')}  tick={st.get('tick')}")

for b in a.buildings():
    if b["block"].endswith("drill") or b["block"] == "conveyor":
        print(f"  {b['block']:<18} ({b['x']},{b['y']}) rot={b['rotation']} "
              f"acceptsFrom={b.get('acceptsFrom')} sendsTo={b.get('sendsTo')} "
              f"items={b.get('items')}")

for one in a.get("drill").get("drills", []):
    keys = ("x", "y", "block", "dominantItem", "dominantItems", "tier",
            "oreHardness", "canMine", "full", "efficiency")
    print("  /drill: " + json.dumps({k: one.get(k) for k in keys}, ensure_ascii=False))
