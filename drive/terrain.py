#!/usr/bin/env python3
"""地形侦察：核心周围有什么矿、哪块空着。

用法：
    python terrain.py                      # beta 核心周围 30 格
    python terrain.py --r 60 --ascii 41    # 拉大范围并画图
    python terrain.py --dump 3             # 看原始格结构
"""
import argparse
import collections
import json
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, load_tokens

ORE_CHARS = {
    "copper": "C", "lead": "L", "coal": "K", "titanium": "T",
    "thorium": "H", "sand": "S", "scrap": "X", "beryllium": "B",
    "tungsten": "W", "graphite": "G", "silicon": "I", "metaglass": "M",
    "water": "~", "oil": "o", "slag": "#", "arkycite": "a",
}


def cell_of(t):
    """把一格压成 (kind, name)。

    决定「能不能挖、挖出什么」的是 overlay / drop，不是 block：
        overlay != "air"  →  矿格（"ore-copper" 之类）
        block   != "air"  →  有实体（自然岩壁 / 树 / 玩家建筑）
        否则              →  普通地板

    注意 `block` 字段在空地上是字符串 "air" 而不是 null，直接 `t.get("block")`
    会把整张图都判成方块 —— 这是踩过的坑。
    """
    ov = (t.get("overlay") or "").strip()
    if ov and ov != "air":
        return "ore", (ov[4:] if ov.startswith("ore-") else ov)
    blk = (t.get("block") or "").strip()
    if blk and blk != "air":
        return "block", blk
    return "floor", (t.get("floor") or "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="beta")
    ap.add_argument("--cx", type=int, default=None)
    ap.add_argument("--cy", type=int, default=None)
    ap.add_argument("--r", type=int, default=30)
    ap.add_argument("--ascii", type=int, default=0, help="画以核心为中心的正方形边长")
    ap.add_argument("--dump", type=int, default=0, help="dump 前 N 格原始 JSON")
    ap.add_argument("--top", type=int, default=12, help="列最大的 N 块矿簇")
    args = ap.parse_args()

    toks, _ = load_tokens()
    a = Arena(args.agent, toks[args.agent])

    if args.cx is None or args.cy is None:
        core = next((b for b in a.buildings() if b["block"].startswith("core")), None)
        if not core:
            print("找不到核心")
            return 1
        args.cx, args.cy = core["x"], core["y"]

    r = args.r
    x0, y0 = args.cx - r, args.cy - r
    w = h = r * 2 + 1
    tiles = a.map(x0, y0, w, h)
    print(f"核心 ({args.cx},{args.cy})  拉取 ({x0},{y0}) {w}x{h} = {len(tiles)} 格")
    if args.dump:
        for t in tiles[: args.dump]:
            print("   ", json.dumps(t, ensure_ascii=False))

    if tiles and "x" not in tiles[0]:
        print("!! tile 里没有 x/y 字段，按行优先索引推算")
        fixed = []
        for i, t in enumerate(tiles):
            t = dict(t)
            t.setdefault("x", x0 + i % w)
            t.setdefault("y", y0 + i // w)
            fixed.append(t)
        tiles = fixed

    kinds = collections.Counter()
    ores = collections.Counter()
    drops = collections.Counter()
    invis = 0
    for t in tiles:
        if not t.get("visible", True):
            invis += 1
        k, n = cell_of(t)
        kinds[k] += 1
        if k == "ore":
            ores[n] += 1
        d = t.get("drop") or ""
        if d:
            drops[(d, t.get("dropHardness"))] += 1
    print("kind 分布:", dict(kinds))
    print("矿格分布:", dict(ores))
    print("可挖物:", {f"{k[0]}(h{k[1]})": v for k, v in drops.most_common()})
    if invis:
        print(f"不可见格 {invis} —— 迷雾下这些格子的数据未经确认，不要据此建造")

    for name, _n in ores.most_common():
        pts = [(t["x"], t["y"]) for t in tiles if t.get("ore") == name]
        mx = sum(p[0] for p in pts) / len(pts)
        my = sum(p[1] for p in pts) / len(pts)
        near = min(abs(p[0] - args.cx) + abs(p[1] - args.cy) for p in pts)
        far = max(abs(p[0] - args.cx) + abs(p[1] - args.cy) for p in pts)
        print(f"  {name:<10} {len(pts):>4} 格  质心({mx:.0f},{my:.0f})  距核心 {near}~{far} 曼哈顿")

    if args.ascii:
        n, half = args.ascii, args.ascii // 2
        g = {(t["x"], t["y"]): cell_of(t) for t in tiles}
        print(f"---- ASCII {n}x{n}  (核心=O 建筑=@ 空=空格 地板=, 矿=字母) ----")
        for y in range(args.cy - half, args.cy + half + 1):
            row = []
            for x in range(args.cx - half, args.cx + half + 1):
                if (x, y) == (args.cx, args.cy):
                    row.append("O")
                    continue
                k, nm = g.get((x, y), ("?", "?"))
                if k == "ore":
                    row.append(ORE_CHARS.get(nm, "?"))
                elif k == "block":
                    row.append("@")
                elif k == "empty":
                    row.append(" ")
                elif k == "floor":
                    row.append(",")
                else:
                    row.append("?")
            print(f"{y:>4} |" + "".join(row) + "|")
    return 0


if __name__ == "__main__":
    sys.exit(main())
