#!/usr/bin/env python3
"""验证电力断开报警。

按红线：人类肉眼能看到的（电力条空、连线断）就该报；减速瓶颈不该报。

这里建一个需要电的方块且完全不接线 —— 屏幕上它的电力条就是空的 ——
/stalls 应当报 powerUnconnected，cause=unpowered。

顺带确认没有引入任何「减速」类输出：clogHeat 阈值仍是「堵死」而非「变慢」。
"""
import json
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])


def load_grid(cx, cy, r=30):
    w = 2 * r + 1
    return {(t["x"], t["y"]): t for t in a.map(cx - r, cy - r, w, w)}


def free(g, x, y):
    t = g.get((x, y))
    return bool(t) and t.get("visible") and (t.get("block") or "air").strip() in ("", "air")


def bidx():
    return {(b["x"], b["y"]): b for b in a.buildings()}


def main():
    core = next(b for b in a.buildings() if b["block"].startswith("core"))
    cx, cy = core["x"], core["y"]
    print(f"tick={a.state()['tick']}  核心 ({cx},{cy})  {core['items']}")

    # 需要电的方块清单（从 /content 里找带 power 消耗的）
    ct = a.get("content").get("blocks", [])
    print(f"\n/content 共 {len(ct)} 个方块")
    cand = [b["name"] for b in ct
            if b.get("name") in ("silicon-smelter", "laser-drill", "graphite-press",
                                 "kiln", "battery", "power-node")]
    print(f"  其中可用作验证的: {cand}")

    g = load_grid(cx, cy)
    # silicon-smelter 是 2x2，需要 2x2 空地
    spot = None
    for y in range(cy - 24, cy + 25):
        for x in range(cx - 24, cx + 25):
            if all(free(g, x + dx, y + dy) for dy in range(2) for dx in range(2)):
                spot = (x, y)
                break
        if spot:
            break
    if not spot:
        print("找不到 2x2 空地")
        return 1

    sx, sy = spot
    print(f"\n在 ({sx},{sy}) 放一个 silicon-smelter，**不接任何电线**")
    try:
        r = a.post("place", x=sx, y=sy, block="silicon-smelter", rot=0)
        print(f"  {json.dumps(r, ensure_ascii=False)[:200]}")
    except ArenaError as e:
        print(f"  ERR code={e.code} {e.message}")
        return 1

    ok = a.poll_until(lambda: (bidx().get((sx, sy)) or {}).get("block") == "silicon-smelter",
                      timeout=150)
    print(f"  建成: {ok}")
    if not ok:
        return 1

    b = bidx().get((sx, sy))
    print(f"  /buildings 回读: powerStatus={b.get('powerStatus')} "
          f"powerLinks={b.get('powerLinks')} items={b.get('items')}")

    print("\n等 StallWatch 采样到它：")
    st = a.poll_until(lambda: [s for s in a.stalls() if s["x"] == sx and s["y"] == sy],
                      timeout=90)
    if st:
        s = st[0]
        print(f"  kind={s.get('kind')}")
        print(f"  cause={s.get('cause')}")
        print(f"  eff={s.get('efficiency')}  outputAccepts={s.get('outputAccepts')}")
        print(f"  missing={json.dumps(s.get('missing'), ensure_ascii=False)}")
        print(f"\n  ⇒ 期望 kind=powerUnconnected / cause=unpowered")
        print(f"     （方块没接任何线，屏幕上电力条是空的 —— 肉眼可见）")
    else:
        print("  没采到")

    print("\n当前全部 stall：")
    for s in a.stalls():
        print(f"  ({s['x']},{s['y']}) {s['block']:<18} kind={s.get('kind'):<18} "
              f"cause={s.get('cause')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
