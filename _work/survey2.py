#!/usr/bin/env python3
"""全图普查 + 矿脉定位。只用 /map 的运行时数据，不猜。"""
import argparse, collections, json, sys, urllib.request, urllib.parse

def call(base, tok, path, **params):
    url = f"{base}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        b = json.loads(r.read().decode("utf-8"))
    if not b.get("ok"):
        raise RuntimeError(b)
    return b["data"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:7199/v1/referee")
    ap.add_argument("--token", required=True)
    ap.add_argument("--out", default=r"C:\dsh\ai-arena\_work\world.json")
    ap.add_argument("--step", type=int, default=50)
    a = ap.parse_args()

    st = call(a.base, a.token, "state")
    W, H = st["world"]["w"], st["world"]["h"]
    tiles = []
    for bx in range(0, W, a.step):
        for by in range(0, H, a.step):
            w = min(a.step, W - bx); h = min(a.step, H - by)
            d = call(a.base, a.token, "map", x=bx, y=by, w=w, h=h, view="all")
            tiles.extend(d["tiles"])
    json.dump({"w": W, "h": H, "tiles": tiles}, open(a.out, "w", encoding="utf-8"))

    vis = [t for t in tiles if t.get("visible")]
    print(f"world {W}x{H}  queried {len(tiles)}  visible {len(vis)}")

    # 矿脉：按 drop 聚合，并做连通块聚类（8 邻）
    pts = collections.defaultdict(set)
    for t in vis:
        if t.get("drop"):
            pts[t["drop"]].add((t["x"], t["y"]))
    print(f"{'ore':<10}{'tiles':>7}  clusters (size>=4)")
    for ore, s in sorted(pts.items(), key=lambda kv: -len(kv[1])):
        seen, clusters = set(), []
        for p in s:
            if p in seen: continue
            stack, comp = [p], []
            seen.add(p)
            while stack:
                cx, cy = stack.pop(); comp.append((cx, cy))
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        n = (cx+dx, cy+dy)
                        if n in s and n not in seen:
                            seen.add(n); stack.append(n)
            clusters.append(comp)
        clusters.sort(key=len, reverse=True)
        head = " | ".join(
            f"n={len(c)} x={min(p[0] for p in c)}..{max(p[0] for p in c)} y={min(p[1] for p in c)}..{max(p[1] for p in c)}"
            for c in clusters[:6] if len(c) >= 4)
        print(f"{ore:<10}{len(s):>7}  {head}")

    fl = collections.Counter(t.get("floor") for t in vis)
    print("\nfloors:", dict(fl.most_common(20)))
    blk = collections.Counter(t.get("block") for t in vis if t.get("block") and t["block"] != "air")
    print("blocks:", dict(blk.most_common(20)))
    return 0

if __name__ == "__main__":
    sys.exit(main())
