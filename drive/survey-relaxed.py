#!/usr/bin/env python3
"""放宽判据重算钻机位。

上一版要求 2x2 四格**全是**同种矿 —— 太严。Mindustry 的钻机只要脚下有该矿
就能挖（`dominantItem` 取覆盖范围内最多的那种）。所以真正的限制是
「有矿格 + 四邻可通行」，不是「四格同矿」。

同时统计「含矿格数」分布，因为一台钻机脚下矿越多、产率是否越高需要实测确认
（先按含矿格数分档，后面用实测数据回填）。
"""
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])
core = next(b for b in a.buildings() if b["block"].startswith("core"))
cx, cy = core["x"], core["y"]

W, R, step = 61, 90, 60
g = {}
for oy in range(-R, R + 1, step):
    for ox in range(-R, R + 1, step):
        x0, y0 = cx + ox, cy + oy
        if x0 < 0 or y0 < 0:
            continue
        try:
            for t in a.map(x0, y0, W, W):
                g[(t["x"], t["y"])] = t
        except ArenaError:
            pass
print(f"覆盖 {len(g)} 格")


def ov(t):
    o = (t.get("overlay") or "air").strip()
    return o[4:] if o.startswith("ore-") else None


def free(t):
    return (t.get("block") or "air").strip() in ("", "air")


def pick(sites_raw):
    picked = []
    for p in sorted(sites_raw, key=lambda q: (q[1], q[0])):
        if all(abs(p[0] - q[0]) >= 2 or abs(p[1] - q[1]) >= 2 for q in picked):
            picked.append(p)
    return picked


print(f"\n{'矿':<10}{'矿格':>6}{'全同矿位':>9}{'含矿位(≥1)':>11}{'含矿位(≥2)':>11}")
data = {}
for kind in ("copper", "lead", "titanium", "thorium", "coal"):
    tiles = {p for p, t in g.items() if ov(t) == kind}
    allt, any1, any2 = [], [], []
    for (x, y) in tiles:
        box = [(x + dx, y + dy) for dy in range(2) for dx in range(2)]
        if any(p not in g or not free(g[p]) for p in box):
            continue
        n = sum(1 for p in box if p in tiles)
        if n == 4:
            allt.append((x, y))
        if n >= 1:
            any1.append((x, y))
        if n >= 2:
            any2.append((x, y))
    a_, b_, c_ = pick(allt), pick(any1), pick(any2)
    data[kind] = (len(tiles), len(a_), len(b_), len(c_))
    print(f"{kind:<10}{len(tiles):>6}{len(a_):>9}{len(b_):>11}{len(c_):>11}")

print("\n== 单台 ~0.35/s 外推的上限 ==")
for k, (n, s4, s1, s2) in data.items():
    print(f"  {k:<10} 矿格{n:>4}  按含矿位 {s1:>3} 台 → 上限 {s1*0.35:>5.2f} /s"
          f"   {'✓' if s1*0.35 >= 5 else '✗'}")

print("\n注：含矿位互不重叠，但同一格可被多台钻机共享边——已去重叠。")
print("真正产率还取决于「脚下几格矿」，需要实测回填。")

# 列出离核心最近的几个含矿位，供下一步布局
print("\n== 最近的可放钻机位（含矿 ≥1）==")
for kind in ("lead", "titanium", "coal", "copper"):
    tiles = {p for p, t in g.items() if ov(t) == kind}
    cands = []
    for (x, y) in tiles:
        box = [(x + dx, y + dy) for dy in range(2) for dx in range(2)]
        if any(p not in g or not free(g[p]) for p in box):
            continue
        n = sum(1 for p in box if p in tiles)
        if n >= 1:
            cands.append((abs(x - cx) + abs(y - cy), n, x, y))
    cands.sort()
    print(f"  {kind:<9}: " + ", ".join(f"({x},{y})距{d}/矿{n}" for d, n, x, y in cands[:6]))
