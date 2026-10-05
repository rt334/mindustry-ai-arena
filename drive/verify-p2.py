#!/usr/bin/env python3
"""验证 A6（limits）与 补4（vision / fogRadius）。

关键在于**交叉印证**：不能只看 /state 报了个数就信。
这里把 vision.maxRadius 与 /map 的 visible 边界做实测比对 ——
若两者吻合，说明这个半径确实就是决定「能不能看到」的那个值。
"""
import json
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])


def main():
    st = a.state()
    print(f"tick={st['tick']}")

    # ---- A6 ----
    print("\n== A6 /state.limits ==")
    print(f"  {json.dumps(st.get('limits'), ensure_ascii=False)}")

    # ---- 补4：/state.vision ----
    print("\n== 补4 /state.vision ==")
    v = st.get("vision") or {}
    print(f"  maxRadius = {v.get('maxRadius')}")
    for src in (v.get("sources") or [])[:6]:
        print(f"    {json.dumps(src, ensure_ascii=False)}")
    if len(v.get("sources") or []) > 6:
        print(f"    ...（共 {len(v['sources'])} 个视野源）")

    # ---- fogRadius 也挂在实体上 ----
    print("\n== 实体上的 fogRadius ==")
    for b in a.buildings():
        print(f"  building {b['block']:<16} ({b['x']},{b['y']}) fogRadius={b.get('fogRadius')}")
    for u in a.units():
        print(f"  unit     {u['type']:<16} #{u['id']} fogRadius={u.get('fogRadius')}")

    # ---- 实测可见边界，与 maxRadius 比对 ----
    print("\n== 交叉印证：/map 的 visible 边界 ==")
    core = next(b for b in a.buildings() if b["block"].startswith("core"))
    cx, cy = core["x"], core["y"]
    size = core.get("size", 5)
    # 核心中心（锚点在左下/左上角，5x5 的中心是 +2）
    ccx, ccy = cx + size // 2, cy + size // 2

    # /map 单次上限 4096 格，拉不了 81x81 —— 改用四条正交线，各 61 格
    span = 61
    results = {}
    for name, (dx, dy) in (("东", (1, 0)), ("南", (0, 1)), ("西", (-1, 0)), ("北", (0, -1))):
        if dx > 0:
            tiles = a.map(ccx, ccy, span, 1)
        elif dx < 0:
            tiles = a.map(ccx - span + 1, ccy, span, 1)
        elif dy > 0:
            tiles = a.map(ccx, ccy, 1, span)
        else:
            tiles = a.map(ccx, ccy - span + 1, 1, span)
        vis = [t for t in tiles if t.get("visible")]
        far = 0
        for t in vis:
            d = abs(t["x"] - ccx) + abs(t["y"] - ccy)
            if d > far:
                far = d
        results[name] = far
        print(f"    {name} 向：可见到 {far} 格（拉取 {len(tiles)} 格，可见 {len(vis)} 格）")

    mr = v.get("maxRadius")
    print(f"\n  /state.vision.maxRadius = {mr}")
    print(f"  实测四向最远 = {max(results.values())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
