#!/usr/bin/env python3
"""覆盖优化：真正该问的是「能盖住多少矿格」，不是「有几个钻机位」。

引擎源码给死了公式（Drill.java:149 的放置预览就是这个）：
    每秒产率 = 60 * dominantItems / (drillTime + 50 * hardness)
`dominantItems` 是钻机脚印内的主矿格数，上限 size*size。

所以单台产率正比于它盖住的矿格数，而每个矿格只能被一台钻机盖（钻机不能重叠）。
于是上限 = 「可被覆盖的矿格总数 × 每种矿每格每秒的产出」。

做法：贪心。枚举所有 size×size 全为空地的候选位，按该位盖住的矿格数降序，
逐个放，跳过与已放重叠的。对 2/3/4 三种尺寸各算一遍。
"""
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

DRILLS = {
    # name: (size, tier, drillTime)
    "mechanical-drill": (2, 2, 600),
    "pneumatic-drill": (2, 3, 400),
    "laser-drill": (3, 4, 280),
    "blast-drill": (4, 4, 280),
}
HARD = {"copper": 1, "lead": 2, "coal": 2, "titanium": 3, "thorium": 4}


def rate_per_tile(drill, hardness):
    size, tier, dt = DRILLS[drill]
    if hardness > tier:
        return None
    return 60.0 / (dt + 50 * hardness)


def main():
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

    ore = {}
    for p, t in g.items():
        k = ov(t)
        if k:
            ore.setdefault(k, set()).add(p)

    print(f"\n{'矿':<9}{'矿格':>6}  " + "".join(f"{n[:-6]:>18}" for n in DRILLS))
    res = {}
    for kind in ("copper", "lead", "titanium", "thorium", "coal"):
        tiles = ore.get(kind, set())
        if not tiles:
            continue
        hard = HARD[kind]
        row, best = [], {}
        for dn, (size, tier, dt) in DRILLS.items():
            rpt = rate_per_tile(dn, hard)
            if rpt is None:
                row.append("—")
                best[dn] = None
                continue
            # 贪心选位
            cands = []
            for (x, y) in tiles:
                box = [(x + dx, y + dy) for dy in range(size) for dx in range(size)]
                if any(p not in g or not free(g[p]) for p in box):
                    continue
                n = sum(1 for p in box if p in tiles)
                if n:
                    cands.append((n, x, y, box))
            cands.sort(key=lambda z: (-z[0], z[1], z[2]))
            used, picked = set(), []
            for n, x, y, box in cands:
                if any(p in used for p in box):
                    continue
                used.update(box)
                picked.append(n)
            covered = sum(picked)
            total = covered * rpt
            best[dn] = (len(picked), covered, total)
            row.append(f"{covered:>4}格/{total:>5.1f}/s")
        res[kind] = best
        print(f"{kind:<9}{len(tiles):>6}  " + "".join(f"{v:>18}" for v in row))

    print("\n（每格 = 可盖矿格数 / 该方案下每秒产出上限）")
    print("\n== 最佳可达 vs 目标 +5/s ==")
    for kind in ("copper", "lead", "titanium"):
        b = res.get(kind) or {}
        ok = [(dn, v) for dn, v in b.items() if v]
        if not ok:
            continue
        dn, (cnt, cov, tot) = max(ok, key=lambda z: z[1][2])
        mark = "✓ 可达" if tot >= 5 else "✗ 不可达"
        print(f"  {kind:<9} 最佳 {dn:<17} {cnt:>2}台 盖{cov:>3}格 → {tot:>5.2f} /s   {mark}")


if __name__ == "__main__":
    sys.exit(main())
