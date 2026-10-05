#!/usr/bin/env python3
"""产线选址：在己方视野内找矿机与空地。

**踩过的坑（第一版）**：候选判定写成了
    hit = all((ore(c) == want) if kind == 'ore' else (drp(c) == want) ...)
而 kind 的取值是 'coal'/'sand'/'copper'，`kind == 'ore'` 永远不成立 ——
于是对煤矿也在比 drop，结果「0 个候选」。地形没问题，是判据写错了。
教训：条件表达式里的字面量要和实际取值对齐，别用想当然的别名。
"""
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])

core = next(b for b in a.buildings() if b["block"].startswith("core"))
cx, cy = core["x"], core["y"]
print(f"核心 ({cx},{cy})  {core['items']}")
print(f"  占 x[{cx-2},{cx+2}] y[{cy-2},{cy+2}]")


def fetch(R):
    return a.map(cx - R, cy - R, 2 * R + 1, 2 * R + 1)


ts = fetch(30)
xs = [t["x"] for t in ts]
ys = [t["y"] for t in ts]
print(f"\n请求 61x61，实得 {len(ts)} 格   x[{min(xs)},{max(xs)}] y[{min(ys)},{max(ys)}]")

g = {(t["x"], t["y"]): t for t in ts}
vis = [t for t in ts if t.get("visible")]
print(f"visible {len(vis)}")


def overlay(t):
    o = (t.get("overlay") or "air").strip()
    return o[4:] if o.startswith("ore-") else None


def drop(t):
    return (t.get("drop") or "").strip() or None


def free(t):
    return (t.get("block") or "air").strip() in ("", "air")


counts = {}
for t in vis:
    for k in (overlay(t), drop(t)):
        if k:
            counts[k] = counts.get(k, 0) + 1
print("可挖统计:", counts)

print("\n== 2x2 矿机候选（遍历实得格）==")
for kind in ("coal", "sand", "copper", "lead", "titanium"):
    field = "overlay" if kind in ("coal", "copper", "lead", "titanium", "thorium") else "drop"
    get = overlay if field == "overlay" else drop
    cands = []
    for (x, y) in g:
        box = [(x + dx, y + dy) for dy in range(2) for dx in range(2)]
        cs = [g.get(c) for c in box]
        if any(c is None or not c.get("visible") for c in cs):
            continue
        if not all(free(c) for c in cs):
            continue
        if all(get(c) == kind for c in cs):
            cands.append((abs(x - cx) + abs(y - cy), x, y))
    cands.sort()
    print(f"  {kind:<9} {len(cands):>3} 个 → {cands[:3]}")

print("\n== 核心右侧的空地（放冶炼厂/太阳能）==")
for (x, y) in sorted(g, key=lambda p: (abs(p[0] - cx) + abs(p[1] - cy))):
    if cx + 1 <= x <= cx + 10 and cy - 3 <= y <= cy + 5 and free(g[(x, y)]):
        pass
row = []
for y in range(cy - 3, cy + 6):
    line = ""
    for x in range(cx - 8, cx + 12):
        t = g.get((x, y))
        line += "?" if (t is None or not t.get("visible")) else ("." if free(t) else "#")
    row.append(f"  y={y:>3} {line}")
print(f"       x={cx-8}…{cx+11}   （. 空  # 占  ? 不可见）")
for r in row:
    print(r)
