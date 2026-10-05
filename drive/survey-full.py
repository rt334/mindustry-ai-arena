#!/usr/bin/env python3
"""分块普查（正确版）。

两个失败的尝试，记下来免得再犯：
  · R=30 单窗口 —— 窗口把结论截断了，得出「铅封顶 1.75/s」这种被窗口造出来的结论。
  · /map 全图 cursor 模式 —— 返回的是**精简 schema，没有 overlay 字段**，
    而且 41 页只覆盖到 y[0,40] 就没了 cursor_next。用它查矿脉必然得 0。

正确做法：把大区域切成多个 61x61（3721 格，在 4096 上限内）分别请求，
每块都用带 overlay 的 schema。
"""
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])
core = next(b for b in a.buildings() if b["block"].startswith("core"))
cx, cy = core["x"], core["y"]
print(f"核心 ({cx},{cy})")

W = 61
R = 90                     # 覆盖 ±90 格
g = {}
step = W - 1
n_ok = 0
for oy in range(-R, R + 1, step):
    for ox in range(-R, R + 1, step):
        x0, y0 = cx + ox, cy + oy
        if x0 < 0 or y0 < 0:
            continue
        try:
            ts = a.map(x0, y0, W, W)
            n_ok += 1
        except ArenaError as e:
            print(f"  块 ({x0},{y0}) 失败 {e.code} {e.message[:70]}")
            continue
        for t in ts:
            g[(t["x"], t["y"])] = t

xs = [p[0] for p in g]
ys = [p[1] for p in g]
print(f"取到 {n_ok} 块 / {len(g)} 格   x[{min(xs)},{max(xs)}] y[{min(ys)},{max(ys)}]")

withov = sum(1 for t in g.values() if t.get("overlay") is not None)
print(f"带 overlay 字段的格: {withov}")
occupied = {(b["x"], b["y"]) for b in a.buildings()}


def ov(t):
    o = (t.get("overlay") or "air").strip()
    return o[4:] if o.startswith("ore-") else None


def free(t):
    return (t.get("block") or "air").strip() in ("", "air")


def sites(tiles):
    s = set(tiles)
    raw = []
    for (x, y) in tiles:
        box = [(x + dx, y + dy) for dy in range(2) for dx in range(2)]
        if all(p in s and free(g.get(p, {})) for p in box):
            raw.append((x, y))
    picked = []
    for p in sorted(raw, key=lambda q: (q[1], q[0])):
        if all(abs(p[0] - q[0]) >= 2 or abs(p[1] - q[1]) >= 2 for q in picked):
            picked.append(p)
    return picked


print(f"\n{'矿':<10}{'格数':>7}{'块数':>6}{'钻机位':>8}   最近几块（钻机位/距核心）")
tot = {}
for kind in ("copper", "lead", "titanium", "thorium", "coal"):
    tiles = [p for p, t in g.items() if ov(t) == kind]
    if not tiles:
        print(f"{kind:<10}{0:>7}")
        tot[kind] = 0
        continue
    seen, comps = set(), []
    for p in tiles:
        if p in seen:
            continue
        stk, comp = [p], []
        seen.add(p)
        while stk:
            q = stk.pop()
            comp.append(q)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (q[0] + dx, q[1] + dy)
                if n in set(tiles) and n not in seen:
                    seen.add(n)
                    stk.append(n)
        comps.append(comp)
    comps.sort(key=len, reverse=True)
    n = sum(len(sites(c)) for c in comps)
    tot[kind] = n
    big = sorted(((len(sites(c)),
                   min(abs(x - cx) + abs(y - cy) for x, y in c)) for c in comps),
                 key=lambda z: (-z[0], z[1]))
    desc = ", ".join(f"{s_}台/距{d}" for s_, d in big[:5])
    print(f"{kind:<10}{len(tiles):>7}{len(comps):>6}{n:>8}   {desc}")

print("\n== 「+5/s」可行性（单台 ~0.35/s，需约 14 台）==")
for k in ("copper", "lead", "titanium", "thorium", "coal"):
    n = tot.get(k, 0)
    print(f"  {k:<10} 上限 {n:>3} 台 → 最高约 {n * 0.35:>5.2f} /s"
          f"   {'✓ 够' if n >= 14 else ('~ 接近' if n >= 8 else '✗ 不够')}")
