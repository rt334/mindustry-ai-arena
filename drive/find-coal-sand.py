#!/usr/bin/env python3
"""侦察：煤矿、沙地、以及适合放冶炼厂的位置。

硅冶炼厂要同时收煤和沙，所以两台钻机的位置最好能汇到一处。
这里把两类矿的实际分布找出来，算出「煤簇」和「沙簇」的最近配对。
"""
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])

core = next(b for b in a.buildings() if b["block"].startswith("core"))
cx, cy = core["x"], core["y"]
print(f"核心 ({cx},{cy})  库存 {core['items']}\n")

R = 30   # 61x61 = 3721 < 4096（/map 单次上限），也正好是核心视野半径
tiles = a.map(cx - R, cy - R, 2 * R + 1, 2 * R + 1)
g = {(t["x"], t["y"]): t for t in tiles}
print(f"拉取 {len(tiles)} 格（{2*R+1}x{2*R+1}）")


def ore_of(t):
    ov = (t.get("overlay") or "air").strip()
    return ov[4:] if ov.startswith("ore-") else None


def drop_of(t):
    d = (t.get("drop") or "").strip()
    return d or None


def mineable(t):
    """能不能放钻机：格子本身要空"""
    return (t.get("block") or "air").strip() in ("", "air")


coal = [(x, y) for (x, y), t in g.items() if ore_of(t) == "coal"]
sand = [(x, y) for (x, y), t in g.items() if drop_of(t) == "sand"]
copper = [(x, y) for (x, y), t in g.items() if ore_of(t) == "copper"]

print(f"煤 {len(coal)} 格  沙 {len(sand)} 格  铜 {len(copper)} 格\n")

# 2x2 候选（4 格同类且都可建）
def candidates(cells, kind, want):
    out = []
    for (x, y) in cells:
        box = [(x + dx, y + dy) for dy in range(2) for dx in range(2)]
        ts = [g.get(c) for c in box]
        if any(t is None for t in ts):
            continue
        if not all(mineable(t) for t in ts):
            continue
        if kind == "ore":
            if not all(ore_of(t) == want for t in ts):
                continue
        else:
            if not all(drop_of(t) == want for t in ts):
                continue
        out.append((abs(x - cx) + abs(y - cy), x, y))
    return sorted(out)


coal_c = candidates(coal, "ore", "coal")
sand_c = candidates(sand, "drop", "sand")
print(f"== 2x2 全煤候选 {len(coal_c)} 个 ==")
for d, x, y in coal_c[:5]:
    print(f"  ({x},{y}) 距核心 {d}")
print(f"\n== 2x2 全沙候选 {len(sand_c)} 个 ==")
for d, x, y in sand_c[:5]:
    print(f"  ({x},{y}) 距核心 {d}")

# 煤沙配对：两者尽量近，且都别离核心太远
print("\n== 煤/沙配对（曼哈顿距离最近的几组）==")
pairs = []
for dc, xc, yc in coal_c[:40]:
    for ds, xs, ys in sand_c[:40]:
        gap = abs(xc - xs) + abs(yc - ys)
        pairs.append((gap + dc + ds, gap, (xc, yc, dc), (xs, ys, ds)))
pairs.sort()
for total, gap, c, s in pairs[:5]:
    print(f"  煤({c[0]},{c[1]}) 距核{c[2]:>3}  ↔  沙({s[0]},{s[1]}) 距核{s[2]:>3}"
          f"   煤沙间距 {gap}  合计 {total}")
