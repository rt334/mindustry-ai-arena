#!/usr/bin/env python3
"""arena.place_path() 的端到端测试（封装是否真的绕开了参数名冲突）。"""
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])

core = next(b for b in a.buildings() if b["block"].startswith("core"))
cx, cy = core["x"], core["y"]

w = 61
g = {(t["x"], t["y"]): t for t in a.map(cx - 30, cy - 30, w, w)}


def free(x, y):
    t = g.get((x, y))
    return bool(t) and t.get("visible") and (t.get("block") or "air").strip() in ("", "air")


spot = None
for y in range(cy - 24, cy + 25):
    for x in range(cx - 24, cx + 25):
        if all(free(x + dx, y + dy) for dy in range(4) for dx in range(5)):
            spot = (x, y)
            break
    if spot:
        break

if not spot:
    print("找不到空地")
    sys.exit(1)

x0, y0 = spot
path = [(x0, y0), (x0 + 4, y0), (x0 + 4, y0 + 3)]
print(f"place_path({path}, 'conveyor')")
r = a.place_path(path, "conveyor")
print(f"  tiles={r.get('tiles')}")
for triple in (r.get("rotations") or []):
    print(f"    {triple}")
