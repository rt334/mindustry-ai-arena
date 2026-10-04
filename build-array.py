#!/usr/bin/env python3
"""梳状矿机阵列。

核心思路：**让主干穿过矿区，矿机直接吐进主干。**

`BuildingComp.updateProximity()` 用 anchor + `Edges.getEdges(size)` 建邻接表，
对 2x2 方块来说**东西两侧偏移 2 格的那一格也在表里**（见 LESSONS §1.1）。
所以主干在 (X,y) 时：

    矿机摆在 (X-2, y)  ->  footprint (X-2..X-1)  ->  (X-1,y) 与主干相邻，直接吐
    矿机摆在 (X+1, y)  ->  footprint (X+1..X+2)  ->  (X+1,y) 与主干相邻，直接吐

**每台矿机零额外传送带。** 几十台机器手点几百个坐标的问题直接消失。

y 按 2 步进，保证同侧矿机不重叠。

用法：
    python build-array.py --token T --item coal --spine-x 58 --y0 74 --y1 86 --dry
    python build-array.py --token T --item coal --spine-x 58 --y0 74 --y1 86 --apply
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request

DRILLS = {
    "mechanical-drill": (600, 2, 2),
    "pneumatic-drill":  (400, 2, 3),
    "laser-drill":      (280, 3, 4),
    "blast-drill":      (280, 4, 5),
}
HARDNESS_MULT = 50
HARDNESS = {"sand": 0, "copper": 1, "lead": 1, "coal": 2,
            "titanium": 3, "thorium": 4, "tungsten": 5}


def api(host, port, agent, token, path, params=None, method="GET"):
    url = f"http://{host}:{port}/v1/{agent}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_tiles(host, port, agent, token, x0, y0, w, h, step=40):
    tiles = {}
    for bx in range(x0, x0 + w, step):
        for by in range(y0, y0 + h, step):
            try:
                j = api(host, port, agent, token, "map",
                        {"x": bx, "y": by, "w": step, "h": step})
            except Exception as e:
                print(f"  区块 ({bx},{by}) 失败: {e}", file=sys.stderr)
                continue
            if not j.get("ok"):
                continue
            for t in j["data"]["tiles"]:
                tiles[(t["x"], t["y"])] = t
    return tiles


def footprint(x, y, size):
    return {(x + dx, y + dy) for dx in range(size) for dy in range(size)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7199)
    ap.add_argument("--agent", default="alpha")
    ap.add_argument("--token", required=True)
    ap.add_argument("--item", required=True)
    ap.add_argument("--drill", default="mechanical-drill")
    ap.add_argument("--spine-x", type=int, required=True)
    ap.add_argument("--y0", type=int, required=True)
    ap.add_argument("--y1", type=int, required=True)
    ap.add_argument("--sides", default="-2,+1",
                    help="矿机 anchor 相对主干的 x 偏移，逗号分隔")
    ap.add_argument("--target", type=float, default=5.0)
    ap.add_argument("--only", default=None,
                    help="只允许这些矿种（逗号分隔，**顺序即优先级**）。"
                         "不指定则每台选自身最优矿种 —— 但那样沙会挤掉煤，"
                         "因为沙速率最高。")
    ap.add_argument("--targets", default=None,
                    help="每项速率上限，形如 coal=5,copper=5。达标后不再为它占坑。")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    drill_time, size, tier = DRILLS[args.drill]
    offsets = [int(s) for s in args.sides.split(",")]
    X = args.spine_x
    y0, y1 = min(args.y0, args.y1), max(args.y0, args.y1)

    tiles = fetch_tiles(args.host, args.port, args.agent, args.token,
                        X - 8, y0 - 8, 24, (y1 - y0) + 16)
    print(f"地形 {len(tiles)} 格   矿机={args.drill}  主干 x={X}  y={y0}..{y1}")

    spine = [(X, y) for y in range(y0, y1 + 1)]
    spine_set = set(spine)

    # 主干必须是空地
    blocked = [c for c in spine if tiles.get(c, {}).get("block") != "air"]
    if blocked:
        print(f"主干被占: {blocked[:10]}", file=sys.stderr)

    only = args.only.split(",") if args.only else None
    prio = {it: i for i, it in enumerate(only)} if only else {}

    cands = []
    for y in range(y0, y1 + 1):
        for off in offsets:
            ax = X + off
            fp = footprint(ax, y, size)
            if fp & spine_set:
                continue                      # 与主干重叠
            ok = True
            counts = {}
            for c in fp:
                t = tiles.get(c)
                if t is None or t.get("block") != "air":
                    ok = False
                    break
                d = t.get("drop")
                if d:
                    h = t.get("dropHardness")
                    if h is not None and h <= tier:
                        counts[d] = counts.get(d, 0) + 1
            if not ok:
                continue
            n = counts.get(args.item, 0)
            if args.item == "any":
                if only:
                    # 只在这些矿种里挑，且按 --only 的顺序定优先级：
                    # 沙速率最高，纯按速率排会把煤和铜的坑全占掉。
                    best_item = None
                    for it_name in only:
                        if counts.get(it_name, 0) > 0:
                            best_item = it_name
                            break
                    if best_item is None:
                        continue
                else:
                    if not counts:
                        continue
                    best_item = max(counts.items(), key=lambda kv: kv[1])[0]
                n = counts[best_item]
                it = best_item
            else:
                if n == 0:
                    continue
                it = args.item
            delay = drill_time + HARDNESS_MULT * HARDNESS.get(it, 0)
            rate = n / delay * 60.0
            cands.append({"x": ax, "y": y, "n": n, "rate": rate, "item": it,
                          "prio": prio.get(it, 99),
                          "block": args.drill, "size": size})

    # 贪心去重（同侧相邻 y 的 footprint 会重叠）。
    #
    # ⚠ 排序必须是「优先级优先、速率次之」。早先只按 -rate 排，沙(0.40)会把
    # 煤(0.343)和铜(0.369)的坑全占掉 —— 沙到处都是，煤是硬约束，速率高不等于价值高。
    #
    # per-item 目标：某项达标后就不再为它占坑，把位置让给还没达标的。
    targets = {}
    if args.targets:
        for seg in args.targets.split(","):
            if not seg.strip():
                continue
            k, v = seg.split("=")
            targets[k.strip()] = float(v)

    used = set(spine_set)
    picked = []
    acc = {}
    for c in sorted(cands, key=lambda c: (c["prio"], -c["rate"], c["y"])):
        it = c["item"]
        if it in targets and acc.get(it, 0.0) >= targets[it]:
            continue
        fp = footprint(c["x"], c["y"], size)
        if fp & used:
            continue
        used |= fp
        picked.append(c)
        acc[it] = acc.get(it, 0.0) + c["rate"]

    total = sum(c["rate"] for c in picked)
    byitem = {}
    for c in picked:
        byitem[c["item"]] = byitem.get(c["item"], 0) + c["rate"]
    print(f"\n候选 {len(cands)} 台  去重后 {len(picked)} 台  合计 {total:.2f}/s"
          f"  （目标 {args.target}/s）")
    for it in sorted(byitem):
        print(f"   小计 {it:<8} {byitem[it]:5.2f}/s")
    for c in picked:
        print(f"   ({c['x']:3},{c['y']:3}) {c['item']:<7} {c['n']}格 {c['rate']:.3f}/s")

    # 主干流向：从 --y0 流向 --y1。
    # ⚠ 方向约定（实测）：+y 是**北**。y1 > y0 表示往北流 -> rot=1；
    #   y1 < y0 表示往南流 -> rot=3。写反整条线哑火，所以由参数推导而不是写死。
    flow_rot = 1 if y1 > y0 else 3
    step = 1 if y1 > y0 else -1
    ops = []
    for y in range(y0, y1 + step, step):
        ops.append({"x": X, "y": y, "block": "conveyor", "rot": flow_rot})

    if args.dry:
        flow = "北(+y)" if flow_rot == 1 else "南(-y)"
        print(f"\n主干 {len(ops)} 格，流向 {flow} rot={flow_rot}（自 y={y0} 到 y={y1}）")
        print(f"矿机 {len(picked)} 台，**零额外传送带**（直接吐进主干）")
        return 0

    if args.apply:
        ok = fail = 0
        for c in picked:
            try:
                j = api(args.host, args.port, args.agent, args.token, "place",
                        {"x": c["x"], "y": c["y"], "block": c["block"]},
                        method="POST")
                if j.get("ok"):
                    ok += 1
                else:
                    fail += 1
                    print(f"   FAIL drill ({c['x']},{c['y']}) {j.get('error')}")
            except Exception as e:
                fail += 1
                print(f"   ERR drill ({c['x']},{c['y']}) {e}")
        for o in ops:
            try:
                j = api(args.host, args.port, args.agent, args.token, "place",
                        {"x": o["x"], "y": o["y"], "block": o["block"],
                         "rot": o["rot"]}, method="POST")
                if j.get("ok"):
                    ok += 1
                else:
                    fail += 1
                    print(f"   FAIL belt ({o['x']},{o['y']}) {j.get('error')}")
            except Exception as e:
                fail += 1
                print(f"   ERR belt ({o['x']},{o['y']}) {e}")
        print(f"下单 成功={ok} 失败={fail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
