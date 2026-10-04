#!/usr/bin/env python3
"""围绕核心的局部地图渲染 + 己方建筑清单。数据全部来自 /map 与 /buildings。"""
import argparse, collections, json, sys, urllib.request, urllib.parse

def call(base, tok, path, **p):
    url = f"{base}/{path}" + ("?" + urllib.parse.urlencode(p) if p else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        b = json.loads(r.read().decode())
    if not b.get("ok"):
        raise RuntimeError(b)
    return b["data"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", required=True)
    ap.add_argument("--agent", default="referee")
    ap.add_argument("--cx", type=int, default=61)
    ap.add_argument("--cy", type=int, default=104)
    ap.add_argument("--r", type=int, default=45)
    ap.add_argument("--ore-only", action="store_true")
    a = ap.parse_args()
    base = f"http://127.0.0.1:7199/v1/{a.agent}"

    x0, y0 = max(0, a.cx - a.r), max(0, a.cy - a.r)
    W = H = 2 * a.r
    g = {}
    STEP = 32                                    # 服务端对单次窗口有上限，分块拼
    for bx in range(x0, x0 + W, STEP):
        for by in range(y0, y0 + H, STEP):
            w = min(STEP, x0 + W - bx); h = min(STEP, y0 + H - by)
            d = call(base, a.token, "map", x=bx, y=by, w=w, h=h, view="all")
            for t in d["tiles"]:
                g[(t["x"], t["y"])] = t

    letters = {}
    def sym(t):
        if t.get("block") and t["block"] != "air":
            b = t["block"]
            return {"dune-wall": "#", "shale-wall": "%"}.get(b, "B")
        if t.get("drop"):
            return {"copper": "C", "lead": "L", "coal": "K", "titanium": "T",
                    "sand": "S", "thorium": "H", "scrap": "X"}.get(t["drop"], "?")
        return "."

    print(f"region x={x0}..{x0+2*a.r-1}  y={y0}..{y0+2*a.r-1}   (C=copper L=lead K=coal T=titanium S=sand #=dune-wall %=shale-wall B=other-block .=empty)")
    hdr = "    " + "".join(str((x0+i) % 10) for i in range(2*a.r))
    print(hdr)
    for y in range(y0, y0 + 2*a.r):
        row = "".join(sym(g[(x, y)]) if (x, y) in g else " " for x in range(x0, x0 + 2*a.r))
        print(f"{y:3d} {row}")

    print("\n=== 己方建筑 ===")
    bl = call(base, a.token, "buildings").get("buildings", [])
    cnt = collections.Counter(b["block"] for b in bl)
    for k, v in cnt.most_common():
        print(f"  {k:<22} {v}")
    print("\n=== 非传送带建筑坐标 ===")
    for b in bl:
        if b["block"] not in ("conveyor",):
            print(f"  {b['block']:<22} ({b['x']},{b['y']}) rot={b.get('rotation')} eff={b.get('efficiency')} items={b.get('items')} pow={b.get('powerStatus')}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
