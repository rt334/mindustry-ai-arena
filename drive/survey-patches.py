#!/usr/bin/env python3
"""矿脉连通块普查：为规模化布局提供事实。

要回答的问题：
  · 每块矿脉多大、在哪、有几个**互不重叠**的 2x2 钻机位（且未被现有建筑占用）
  · 一条收集带能不能穿过这些点位

单台机械钻 ~0.35/s，+5/s 需要约 14 台 —— 所以必须知道哪里能排下 14 台。
"""
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])
core = next(b for b in a.buildings() if b["block"].startswith("core"))
cx, cy = core["x"], core["y"]
print(f"核心 ({cx},{cy})")

R = 30
ts = a.map(cx - R, cy - R, 2 * R + 1, 2 * R + 1)
g = {(t["x"], t["y"]): t for t in ts}
occupied = {(b["x"], b["y"]) for b in a.buildings()}
print(f"视野 {len(ts)} 格，现有建筑 {len(occupied)} 个\n")


def ov(t):
    o = (t.get("overlay") or "air").strip()
    return o[4:] if o.startswith("ore-") else None


def free(t):
    return (t.get("block") or "air").strip() in ("", "air")


def sites_in(tiles):
    """该矿脉里所有 2x2 全属于本块且无建筑的点位，再去掉互相重叠的。"""
    s = set(tiles)
    raw = []
    for (x, y) in tiles:
        box = [(x + dx, y + dy) for dy in range(2) for dx in range(2)]
        if all(p in s and free(g[p]) for p in box):
            raw.append((x, y))
    picked = []
    for p in sorted(raw, key=lambda q: (q[1], q[0])):
        if all(abs(p[0] - q[0]) >= 2 or abs(p[1] - q[1]) >= 2 for q in picked):
            picked.append(p)
    return picked


for kind in ("copper", "lead", "titanium", "thorium", "coal"):
    tiles = [(t["x"], t["y"]) for t in ts if ov(t) == kind]
    if not tiles:
        print(f"{kind}: 无")
        continue
    seen, comps = set(), []
    for p in tiles:
        if p in seen:
            continue
        st, comp = [p], []
        seen.add(p)
        while st:
            q = st.pop()
            comp.append(q)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (q[0] + dx, q[1] + dy)
                if n in set(tiles) and n not in seen:
                    seen.add(n)
                    st.append(n)
        comps.append(comp)
    comps.sort(key=len, reverse=True)
    tot = sum(len(sites_in(c)) for c in comps)
    print(f"{kind}: {len(tiles)} 格 / {len(comps)} 块，可放钻机共 {tot} 台")
    for i, c in enumerate(comps[:3]):
        xs = [p[0] for p in c]
        ys = [p[1] for p in c]
        sl = sites_in(c)
        d = min(abs(x - cx) + abs(y - cy) for x, y in c)
        print(f"   块{i} {len(c):>3}格 x[{min(xs)},{max(xs)}] y[{min(ys)},{max(ys)}]"
              f" 距核心{d:>3}  钻机位{len(sl):>2} → {sl[:10]}")
    print()

# 可放钻机但视野里没矿的格子不需要；反过来看铜的整片范围
print("== 铜矿脉全貌（视野内，O=矿 . =空 # =有建筑 x=核心）==")
copper = [(t["x"], t["y"]) for t in ts if ov(t) == "copper"]
if copper:
    xs = [p[0] for p in copper]
    ys = [p[1] for p in copper]
    x0, x1 = min(xs) - 2, max(xs) + 2
    y0, y1 = min(ys) - 2, max(ys) + 2
    for y in range(y0, y1 + 1):
        line = ""
        for x in range(x0, x1 + 1):
            t = g.get((x, y))
            if t is None:
                line += "?"
            elif (x, y) in occupied:
                line += "x"
            elif ov(t) == "copper":
                line += "O"
            elif free(t):
                line += "."
            else:
                line += "#"
        print(f"  y={y:>3} {line}")
    print(f"        x={x0}…{x1}")
