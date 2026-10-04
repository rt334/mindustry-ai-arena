#!/usr/bin/env python3
"""产线布线器。

给一条主干（spine）+ 一组矿机位置，自动生成把每台矿机接进主干的传送带，
并算出每条的朝向。

为什么需要它：+5/s 每项资源要几十台矿机，每台至少要一条传送带接到主干。
手点几百个坐标不可能，而且**朝向错一格整条线就哑火**（实测踩过两次）。

朝向约定（实测，见 ENGINE-NOTES §13）：
    rotation = **出料方向**。Mindustry 的旋转按坐标增量定义，与屏幕方位对不上：

        0 = right  (+1, 0)  →  屏幕东
        1 = top    ( 0,+1)  →  **屏幕南**
        2 = left   (-1, 0)  →  屏幕西
        3 = bottom ( 0,-1)  →  **屏幕北**

    地图 y 向下增长，所以枚举里的 `top` 指向屏幕**下方**。别按名字理解。
入料来自对面那一侧。

主干从 spine[0] 流向 spine[-1]（终点 = 核心一侧）。

用法：
    python build-line.py --token T --plan layout.json --spine "57,113;57,112;..." --dry
    python build-line.py --token T --plan layout.json --spine "..." --apply
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request

# 方向 -> rotation（出料方向，nearby 约定）
DIR_ROT = {(1, 0): 0, (0, 1): 1, (-1, 0): 2, (0, -1): 3}


def step_toward(a, b, used, allow):
    """从 a 朝 b 走一步。优先消掉较大的那个轴差。"""
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    cands = []
    if abs(dx) >= abs(dy):
        if dx:
            cands.append((a[0] + (1 if dx > 0 else -1), a[1]))
        if dy:
            cands.append((a[0], a[1] + (1 if dy > 0 else -1)))
    else:
        if dy:
            cands.append((a[0], a[1] + (1 if dy > 0 else -1)))
        if dx:
            cands.append((a[0] + (1 if dx > 0 else -1), a[1]))
    for c in cands:
        if c in used or c not in allow:
            continue
        return c
    return None


def route(start, goal, used, allow, max_steps=400):
    """从 start 走到 goal，返回途经格（不含 goal）。Manhattan L 形。"""
    path = []
    cur = start
    for _ in range(max_steps):
        if cur == goal:
            return path
        nxt = step_toward(cur, goal, used, allow)
        if nxt is None:
            return None
        path.append(nxt)
        cur = nxt
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7199)
    ap.add_argument("--agent", default="alpha")
    ap.add_argument("--token", required=True)
    ap.add_argument("--plan", required=True,
                    help="矿机清单 JSON: [{\"x\":..,\"y\":..,\"block\":..,\"size\":..}, ...]")
    ap.add_argument("--spine", required=True,
                    help="主干格，分号分隔，形如 '57,113;57,112;57,111'（末尾=终点）")
    ap.add_argument("--size", type=int, default=2)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    spine = []
    for seg in args.spine.split(";"):
        seg = seg.strip()
        if not seg:
            continue
        x, y = seg.split(",")
        spine.append((int(x), int(y)))
    if len(spine) < 2:
        print("主干至少 2 格", file=sys.stderr)
        return 1

    plan = json.load(open(args.plan, encoding="utf-8"))

    used = set()
    for d in plan:
        s = d.get("size", args.size)
        for dx in range(s):
            for dy in range(s):
                used.add((d["x"] + dx, d["y"] + dy))

    # 主干自身占位，且主干内部朝向已定
    spine_set = set(spine)

    ops = []
    # 主干：每格朝下一格
    for i in range(len(spine) - 1):
        a, b = spine[i], spine[i + 1]
        rot = DIR_ROT.get((b[0] - a[0], b[1] - a[1]))
        if rot is None:
            print(f"主干 {a}->{b} 不相邻", file=sys.stderr)
            return 1
        ops.append({"x": a[0], "y": a[1], "block": "conveyor", "rot": rot})
    ops.append({"x": spine[-1][0], "y": spine[-1][1], "block": "conveyor",
                "rot": DIR_ROT.get((spine[-1][0] - spine[-2][0],
                                    spine[-1][1] - spine[-2][1]))})

    allow = set()   # 允许经过的格：主干 + 未来填的传送带，先不限制
    for d in plan:
        s = d.get("size", args.size)
        x, y = d["x"], d["y"]
        # 找矿机 footprint 的一个空邻格作为接入口
        nbrs = []
        for dx in range(s):
            nbrs.append((x + dx, y - 1))
            nbrs.append((x + dx, y + s))
        for dy in range(s):
            nbrs.append((x - 1, y + dy))
            nbrs.append((x + s, y + dy))
        # 选离主干最近的
        best = None
        for n in nbrs:
            if n in used or n in spine_set:
                continue
            # 只考虑能连到主干的
            dists = [abs(n[0] - sp[0]) + abs(n[1] - sp[1]) for sp in spine]
            k = min(range(len(spine)), key=lambda i: dists[i])
            if best is None or dists[k] < best[0]:
                best = (dists[k], n, spine[k])
        if best is None:
            print(f"  矿机 ({x},{y}) 无可用接入口", file=sys.stderr)
            continue
        _, entry, target = best

        path = route(entry, target, used, allow)
        if path is None:
            print(f"  矿机 ({x},{y}) 布线失败（entry={entry} target={target}）",
                  file=sys.stderr)
            continue

        chain = [entry] + path + [target]
        # 每条传送带朝链上的下一格
        for i in range(len(chain) - 1):
            a, b = chain[i], chain[i + 1]
            rot = DIR_ROT.get((b[0] - a[0], b[1] - a[1]))
            if rot is None:
                continue
            if a in spine_set:
                # 主干格朝向已定，不覆盖
                continue
            ops.append({"x": a[0], "y": a[1], "block": "conveyor", "rot": rot})
            used.add(a)

    # 去重（同一格可能被重复规划）
    seen = {}
    for o in ops:
        seen[(o["x"], o["y"])] = o
    ops = list(seen.values())

    print(f"主干 {len(spine)} 格，矿机 {len(plan)} 台，共 {len(ops)} 个方块")

    if args.dry:
        for o in ops[:60]:
            print(f"   ({o['x']:3},{o['y']:3}) {o['block']:<10} rot={o['rot']}")
        if len(ops) > 60:
            print(f"   … 还有 {len(ops) - 60} 个")
        return 0

    if args.apply:
        base = f"http://{args.host}:{args.port}/v1/{args.agent}/place"
        ok = fail = 0
        for o in ops:
            q = urllib.parse.urlencode({"x": o["x"], "y": o["y"],
                                        "block": o["block"], "rot": o["rot"]})
            req = urllib.request.Request(base + "?" + q, method="POST")
            req.add_header("Authorization", f"Bearer {args.token}")
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    j = json.loads(resp.read().decode("utf-8"))
                if j.get("ok"):
                    ok += 1
                else:
                    fail += 1
                    print(f"   FAIL ({o['x']},{o['y']}) {j.get('error')}")
            except Exception as e:
                fail += 1
                print(f"   ERR ({o['x']},{o['y']}) {e}")
        print(f"下单 成功={ok} 失败={fail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
