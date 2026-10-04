#!/usr/bin/env python3
"""一键铺产线。

把「扫描矿脉 -> 选主干 -> 梳状布矿机 -> 汇入核心」整条流程串起来，
重启服务端之后一条命令重建全部产能。

为什么需要它：这条产线有几十台矿机 + 上百条传送带，分散在南北两个矿区。
手工下坐标不可能，而且**朝向错一格整条线就哑火**（实测踩过三次：
东行写成 rot=2、南行写成 rot=1、南主干 y0/y1 传反）。

朝向约定（实测，见 LESSONS §1.1）：
    rotation = **出料方向**，nearby 约定  0=东(+x) 1=北(+y) 2=西(-x) 3=南(-y)

主干规格在这里集中声明，避免散落在命令行里传错参数。

用法：
    python build-all.py --token T --dry
    python build-all.py --token T --apply
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


def api(host, port, agent, token, path, params=None, method="GET", timeout=30):
    url = f"http://{host}:{port}/v1/{agent}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
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


# ---------------------------------------------------------------------------
# 主干规格
#
# flow 表示物品流向：'n' = +y（rot=1），'s' = -y（rot=3）。
# y0/y1 是主干覆盖的 y 区间；**流动方向由 flow 决定，不由 y0/y1 的大小决定** ——
# 早先把两者混在一起，南主干传成 y0<y1 就自动判成北流，整条线反着堵。
# ---------------------------------------------------------------------------
TRUNKS = [
    # 本局矿脉实测（**每局都会变，必须重扫**）：
    #   coal    47 格  x=15..41  y=103..110  ← 核心正西，一条横向带
    #   copper 274 格  x=8..119  y=61..159
    #   lead   295 格  x=5..123  y=53..153
    #   titanium 95 格 x=34..105 y=62..148
    #   sand  4951 格  遍地
    #
    # 煤只有 47 格，是稀缺项，而且决定石墨/硅能不能开线 —— 主干围绕它排。
    # 煤带是**横向**的，所以这里用横向主干（flow='e'），从西往东流进核心西边界。
    dict(name="煤矿主干(西->东)", flow="e", spine_y=106, x0=20, x1=58,
         sides=[-1, +1], only=["coal", "copper", "lead", "sand"],
         targets={"coal": 5.0}),
    # 铜铅带在核心正南，竖直主干自南向北
    dict(name="南区主干(南->北)", flow="n", spine_x=56, y0=102, y1=122,
         sides=[-2, +1], only=["copper", "lead", "titanium", "sand"],
         targets={}),
    # 沙是本地特产，单开一条供硅线
    dict(name="北区主干(南->北)", flow="n", spine_x=58, y0=74, y1=101,
         sides=[-2, +1], only=["copper", "lead", "titanium", "sand"],
         targets={}),
]

# 核心汇入段：主干末端拐进核心
CORE_ENTRIES = [
    # 南主干末端 (56,102) 拐东，把货送进核心西边界
    (57, 102, 0),
    (58, 102, 0),
]


def build_trunk(tiles, spec, drill, target_default):
    """一条主干 + 挂在它两侧的矿机。

    主干可以是竖直（flow 'n'/'s'，用 spine_x + y0/y1）或横向
    （flow 'e'/'w'，用 spine_y + x0/x1）。矿机沿主干的**垂直方向**偏移，
    所以两种朝向共用同一套摆放逻辑。
    """
    drill_time, size, tier = DRILLS[drill]
    flow = spec["flow"]
    only = spec.get("only") or []
    targets = spec.get("targets") or {}
    prio = {it: i for i, it in enumerate(only)}

    if flow in ("n", "s"):
        X = spec["spine_x"]
        y0, y1 = min(spec["y0"], spec["y1"]), max(spec["y0"], spec["y1"])
        spine = [(X, y) for y in range(y0, y1 + 1)]
        vertical = True
    else:
        Y = spec["spine_y"]
        x0, x1 = min(spec["x0"], spec["x1"]), max(spec["x0"], spec["x1"])
        spine = [(x, Y) for x in range(x0, x1 + 1)]
        vertical = False

    spine_set = set(spine)

    cands = []
    for (sx, sy) in spine:
        for off in spec["sides"]:
            ax, ay = (sx + off, sy) if vertical else (sx, sy + off)
            fp = footprint(ax, ay, size)
            if fp & spine_set:
                continue
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
            it = None
            for name in only:
                if counts.get(name, 0) > 0:
                    it = name
                    break
            if it is None:
                continue
            n = counts[it]
            delay = drill_time + HARDNESS_MULT * HARDNESS.get(it, 0)
            cands.append({"x": ax, "y": ay, "item": it, "n": n,
                          "rate": n / delay * 60.0,
                          "prio": prio.get(it, 99),
                          "block": drill, "size": size})

    used = set(spine_set)
    picked = []
    acc = {}
    # 优先级优先、速率次之。只按速率排的话沙(0.40)会把煤(0.343)的坑全占掉。
    for c in sorted(cands, key=lambda c: (c["prio"], -c["rate"], c["y"], c["x"])):
        it = c["item"]
        if it in targets and acc.get(it, 0.0) >= targets[it]:
            continue
        fp = footprint(c["x"], c["y"], size)
        if fp & used:
            continue
        used |= fp
        picked.append(c)
        acc[it] = acc.get(it, 0.0) + c["rate"]

    # 主干朝向 = 出料方向。实测约定：0=东 1=北 2=西 3=南
    rot = {"e": 0, "n": 1, "w": 2, "s": 3}[flow]
    ops = [{"x": x, "y": y, "block": "conveyor", "rot": rot} for (x, y) in spine]
    return picked, ops, acc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7199)
    ap.add_argument("--agent", default="alpha")
    ap.add_argument("--token", required=True)
    ap.add_argument("--drill", default="mechanical-drill")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--x0", type=int, default=30)
    ap.add_argument("--y0", type=int, default=60)
    ap.add_argument("--w", type=int, default=60)
    ap.add_argument("--h", type=int, default=70)
    args = ap.parse_args()

    tiles = fetch_tiles(args.host, args.port, args.agent, args.token,
                        args.x0, args.y0, args.w, args.h)
    print(f"地形 {len(tiles)} 格")

    all_drills, all_ops = [], []
    for spec in TRUNKS:
        picked, ops, acc = build_trunk(tiles, spec, args.drill, 5.0)
        total = sum(c["rate"] for c in picked)
        # 主干可以是竖直（spine_x + y0/y1）或横向（spine_y + x0/x1），分别打印
        if spec["flow"] in ("n", "s"):
            where = f"x={spec['spine_x']} y={spec['y0']}..{spec['y1']}"
        else:
            where = f"y={spec['spine_y']} x={spec['x0']}..{spec['x1']}"
        print(f"\n=== {spec['name']}  {where} flow={spec['flow']} ===")
        print(f"   矿机 {len(picked)} 台  合计 {total:.2f}/s")
        for it in sorted(acc):
            print(f"      {it:<8} {acc[it]:5.2f}/s")
        all_drills += picked
        all_ops += ops

    for (x, y, rot) in CORE_ENTRIES:
        all_ops.append({"x": x, "y": y, "block": "conveyor", "rot": rot})

    print(f"\n总计 矿机 {len(all_drills)} 台，主干 {len(all_ops)} 格")

    if args.dry:
        return 0

    if args.apply:
        ok = fail = 0
        # 先铺主干（矿机直接吐主干，主干不存在会堵）
        for o in all_ops:
            try:
                j = api(args.host, args.port, args.agent, args.token, "place",
                        {"x": o["x"], "y": o["y"], "block": o["block"],
                         "rot": o["rot"]}, method="POST")
                ok += 1 if j.get("ok") else 0
                if not j.get("ok"):
                    fail += 1
                    print(f"   FAIL belt ({o['x']},{o['y']}) {j.get('error')}")
            except Exception as e:
                fail += 1
        for c in all_drills:
            try:
                j = api(args.host, args.port, args.agent, args.token, "place",
                        {"x": c["x"], "y": c["y"], "block": c["block"]},
                        method="POST")
                ok += 1 if j.get("ok") else 0
                if not j.get("ok"):
                    fail += 1
                    print(f"   FAIL drill ({c['x']},{c['y']}) {j.get('error')}")
            except Exception as e:
                fail += 1
        print(f"\n下单 成功={ok} 失败={fail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
