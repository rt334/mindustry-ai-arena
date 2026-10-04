#!/usr/bin/env python3
"""己方(alpha)建筑清单 + 核心占用矩形。地图用 referee+view=all。"""
import json, sys, urllib.parse, urllib.request

ALPHA = "72d17a532ac7296c7f9eaddb2718c133a3d7e724862f006f"
REF = "0dfdae3b5fbdbbc13976591ec467c9d44e957c6e6bd676da"

def call(agent, tok, p, **k):
    u = f"http://127.0.0.1:7199/v1/{agent}/{p}" + ("?" + urllib.parse.urlencode(k) if k else "")
    r = urllib.request.Request(u, headers={"Authorization": "Bearer " + tok})
    b = json.loads(urllib.request.urlopen(r, timeout=30).read().decode())
    if not b.get("ok"):
        raise RuntimeError(b)
    return b["data"]

blocks = {b["name"]: b for b in call("referee", REF, "content")["blocks"]}
L = []
bl = call("alpha", ALPHA, "buildings")["buildings"]
L.append(f"alpha buildings = {len(bl)}")
for b in sorted(bl, key=lambda b: (b["block"], b["y"], b["x"])):
    s = blocks.get(b["block"], {}).get("size", 1)
    L.append(f"{b['block']:<20} ({b['x']:>3},{b['y']:>3}) size={s} rot={b.get('rotation')} "
             f"eff={b.get('efficiency')} items={b.get('items')} liq={b.get('liquids')} "
             f"pow={b.get('powerStatus')} links={b.get('powerLinks')}")

L.append("")
L.append("=== 核心格位判定 ===")
tiles = []
for bx in range(40, 90, 25):
    for by in range(90, 130, 25):
        tiles += call("referee", REF, "map", x=bx, y=by, w=25, h=25, view="all")["tiles"]
for t in sorted(tiles, key=lambda t: (t["y"], t["x"])):
    if t.get("block") and t["block"] != "air" and 50 <= t["x"] <= 75 and 95 <= t["y"] <= 115:
        L.append(f"  ({t['x']},{t['y']}) block={t['block']} team={t.get('team')} floor={t.get('floor')} build={t.get('build')}")

open(r"C:\dsh\ai-arena\_work\dump2.txt", "w", encoding="utf-8").write("\n".join(L))
print("ok", len(L))
