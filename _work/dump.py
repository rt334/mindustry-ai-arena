#!/usr/bin/env python3
"""把己方建筑清单与核心周边矿脉簇写到文本文件（避免控制台编码问题）。"""
import collections, json, sys, urllib.parse, urllib.request

TOK = sys.argv[1] if len(sys.argv) > 1 else "0dfdae3b5fbdbbc13976591ec467c9d44e957c6e6bd676da"
AG = sys.argv[2] if len(sys.argv) > 2 else "referee"
BASE = f"http://127.0.0.1:7199/v1/{AG}"

def call(p, **k):
    u = BASE + "/" + p + ("?" + urllib.parse.urlencode(k) if k else "")
    r = urllib.request.Request(u, headers={"Authorization": "Bearer " + TOK})
    b = json.loads(urllib.request.urlopen(r, timeout=30).read().decode())
    if not b.get("ok"):
        raise RuntimeError(b)
    return b["data"]

def tiles(x0, y0, w, h, step=32):
    out = []
    for bx in range(x0, x0 + w, step):
        for by in range(y0, y0 + h, step):
            ww = min(step, x0 + w - bx); hh = min(step, y0 + h - by)
            out += call("map", x=bx, y=by, w=ww, h=hh, view="all")["tiles"]
    return out

L = []
bl = call("buildings")["buildings"]
L.append(f"buildings={len(bl)}")
for b in sorted(bl, key=lambda b: (b["block"], b["y"], b["x"])):
    L.append(f"{b['block']:<22} ({b['x']:>3},{b['y']:>3}) rot={b.get('rotation')} "
             f"eff={b.get('efficiency')} items={b.get('items')} pow={b.get('powerStatus')} "
             f"links={b.get('powerLinks')}")

L.append("")
L.append("=== 核心周边 70x70 矿脉簇（连通块） ===")
cx, cy = 61, 104
x0, y0 = cx - 35, cy - 35
ts = tiles(x0, y0, 70, 70)
pts = collections.defaultdict(set)
for t in ts:
    if t.get("drop"):
        pts[t["drop"]].add((t["x"], t["y"]))
for ore, s in sorted(pts.items(), key=lambda kv: -len(kv[1])):
    seen, clusters = set(), []
    for p in s:
        if p in seen:
            continue
        stack, comp = [p], []
        seen.add(p)
        while stack:
            c = stack.pop(); comp.append(c)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    n = (c[0] + dx, c[1] + dy)
                    if n in s and n not in seen:
                        seen.add(n); stack.append(n)
        clusters.append(comp)
    clusters.sort(key=len, reverse=True)
    for c in clusters:
        xs = [p[0] for p in c]; ys = [p[1] for p in c]
        dc = min(abs(x - cx) + abs(y - cy) for x, y in c)
        cells = " ".join(f"{p[0]},{p[1]}" for p in sorted(c, key=lambda p: (p[1], p[0])))
        L.append(f"{ore:<9} n={len(c):>3} x={min(xs)}..{max(xs)} y={min(ys)}..{max(ys)} manhattan_core={dc}")
        L.append(f"          {cells}")

open(r"C:\dsh\ai-arena\_work\dump.txt", "w", encoding="utf-8").write("\n".join(L))
print("written", len(L), "lines")
