#!/usr/bin/env python3
"""贴着核心环布矿机 —— 零传送带直喂。

为什么这么做：
  `BuildingComp.updateProximity()` 用锚点 + `Edges.getEdges(size)` 判定邻近。
  2×2 矿机的邻近偏移是 {(0,-1),(0,2),(-1,0),(2,0),(1,-1),(1,2),(-1,1),(2,1)}，
  所以只要矿机的 footprint 与核心的 footprint 相邻，矿机就会把产物**直接推给核心**。

  实测（本文件第一版之前）核心 (61,104) 的 5×5 覆盖 (59..63,102..106)，
  2×2 矿机放 (59,107) 覆盖 (59..60,107..108)，正好命中偏移 (0,-1) -> (59,106)，
  也就是核心本体 —— 中间一格传送带都不需要。

  这比「矿机 -> 传送带 -> 核心」省掉全部传送带成本（1 铜/格）和全部朝向风险
  （实测朝向铺错是产能归零最常见的原因）。

用法：
    python core-drills.py --token T --dry
    python core-drills.py --token T --apply
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request

DRILLS = {
    "mechanical-drill": (600, 2, 2),
    "pneumatic-drill":  (400, 2, 3),
}
HARDNESS_MULT = 50
HARDNESS = {"sand": 0, "copper": 1, "lead": 1, "coal": 2,
            "titanium": 3, "thorium": 4, "tungsten": 5}

# 优先级：煤最关键（石墨/硅都要），其次铜铅，最后沙
PRIORITY = ["coal", "copper", "lead", "titanium", "sand"]


def api(host, port, agent, token, path, params=None, method="GET", timeout=30):
    url = f"http://{host}:{port}/v1/{agent}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch(host, port, agent, token, x0, y0, w, h, step=40):
    tiles = {}
    for bx in range(x0, x0 + w, step):
        for by in range(y0, y0 + h, step):
            try:
                j = api(host, port, agent, token, "map",
                        {"x": bx, "y": by, "w": step, "h": step})
            except Exception:
                continue
            if not j.get("ok"):
                continue
            for t in j["data"]["tiles"]:
                tiles[(t["x"], t["y"])] = t
    return tiles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7199)
    ap.add_argument("--agent", default="alpha")
    ap.add_argument("--token", required=True)
    ap.add_argument("--drill", default="mechanical-drill")
    ap.add_argument("--rings", type=int, default=2,
                    help="围绕核心向外铺几圈矿机（1 圈紧贴核心）")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    drill_time, size, tier = DRILLS[args.drill]

    b = api(args.host, args.port, args.agent, args.token, "buildings")
    core = next((x for x in b["data"]["buildings"]
                 if x["block"].startswith("core-")), None)
    if core is None:
        print("找不到核心", file=sys.stderr)
        return 1
    cx, cy = core["x"], core["y"]
    cs = 5 if "nucleus" in core["block"] else 3
    coff = -((cs - 1) // 2)
    cmin_x, cmin_y = cx + coff, cy + coff
    cmax_x, cmax_y = cmin_x + cs - 1, cmin_y + cs - 1
    print(f"核心 {core['block']} @({cx},{cy}) footprint "
          f"({cmin_x}..{cmax_x},{cmin_y}..{cmax_y})")
    print(f"库存 {core.get('items')}")

    # 矿机候选：锚点使得 footprint 与核心相邻（或更外圈）
    tiles = fetch(args.host, args.port, args.agent, args.token,
                  max(0, cmin_x - 12), max(0, cmin_y - 12), 25, 25)

    cands = []
    # 环1：footprint 与核心相邻；环2..N：再向外
    for ring in range(1, args.rings + 1):
        d = (cs - 1) // 2 + 1 + (size - 1) // 2 + (ring - 1) * size
        anchors = []
        # 南 / 北 各 (cs) 个位置
        for i in range(cs):
            ax = cmin_x + i
            anchors.append((ax, cmax_y + 1 + (ring - 1) * size))   # 南
            anchors.append((ax, cmin_y - size - (ring - 1) * size))  # 北
        # 西 / 东
        for j in range(cs):
            ay = cmin_y + j
            anchors.append((cmin_x - size - (ring - 1) * size, ay))  # 西
            anchors.append((cmax_x + 1 + (ring - 1) * size, ay))     # 东

        for (ax, ay) in anchors:
            fp = {(ax + dx, ay + dy) for dx in range(size) for dy in range(size)}
            ok = True
            counts = {}
            for c in fp:
                t = tiles.get(c)
                if t is None or t.get("block") != "air":
                    ok = False
                    break
                dr = t.get("drop")
                if dr:
                    h = t.get("dropHardness")
                    if h is not None and h <= tier:
                        counts[dr] = counts.get(dr, 0) + 1
            if not ok:
                continue
            item = None
            for name in PRIORITY:
                if counts.get(name, 0) > 0:
                    item = name
                    break
            if item is None:
                continue
            delay = drill_time + HARDNESS_MULT * HARDNESS.get(item, 0)
            cands.append({"x": ax, "y": ay, "item": item,
                          "n": counts[item],
                          "rate": counts[item] / delay * 60.0,
                          "ring": ring,
                          "prio": PRIORITY.index(item)})

    used = {(x, y) for x in range(cmin_x, cmax_x + 1)
            for y in range(cmin_y, cmax_y + 1)}
    picked = []
    acc = {}
    for c in sorted(cands, key=lambda c: (c["prio"], c["ring"], -c["rate"])):
        fp = {(c["x"] + dx, c["y"] + dy) for dx in range(size) for dy in range(size)}
        if fp & used:
            continue
        used |= fp
        picked.append(c)
        acc[c["item"]] = acc.get(c["item"], 0.0) + c["rate"]

    print(f"\n=== 候选矿机 {len(picked)} 台（直喂核心，零传送带）===")
    for c in picked:
        print(f"   ({c['x']},{c['y']}) {c['item']:<8} {c['n']}格  "
              f"{c['rate']:.3f}/s  环{c['ring']}")
    total = sum(c["rate"] for c in picked)
    print(f"   合计 {total:.2f}/s")
    for it in sorted(acc):
        print(f"      {it:<8} {acc[it]:5.2f}/s")

    if args.dry:
        return 0
    if not args.apply:
        return 0

    done = 0
    for c in picked:
        try:
            r = api(args.host, args.port, args.agent, args.token, "place",
                    {"x": c["x"], "y": c["y"], "block": args.drill}, method="POST")
            if r.get("ok"):
                done += 1
            else:
                print(f"   FAIL ({c['x']},{c['y']}) {r.get('error')}")
        except Exception as e:
            print(f"   ERR ({c['x']},{c['y']}) {e}")
    print(f"\n下单 {done}/{len(picked)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
