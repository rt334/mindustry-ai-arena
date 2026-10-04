#!/usr/bin/env python3
"""补验证：A4 队列非空时的 planList，以及钻机的实测 sendsTo。

钻机那条是 A2/补1 的核心 —— 「同样 rot=2，输出格还不一样」这个困扰了
整轮攻坚的现象，现在应该能直接读出来。
"""
import json
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])


def try_place(x, y, block, rot=None):
    try:
        return "OK", a.place(x, y, block, rot=rot)
    except ArenaError as e:
        return f"ERR code={e.code}", e.message


def main():
    core = next(b for b in a.buildings() if b["block"].startswith("core"))
    cx, cy = core["x"], core["y"]

    # ---- A4：一次性下 8 个计划，立刻查队列 ----
    print("== A4 队列非空时的 planList ==")
    row = None
    for y in range(cy + 6, cy + 20):
        cand = [x for x in range(cx - 12, cx + 16)
                if (lambda t: t and t[0].get("visible")
                    and ((t[0].get("block") or "air").strip() in ("", "air"))
                    )(a.map(x, y, 1, 1))]
        if len(cand) >= 8:
            row = (y, cand[0])
            break
    if row:
        y0, x0 = row
        for i in range(8):
            try_place(x0 + i, y0, "conveyor", rot=0)
        q = a.queue()
        b0 = (q.get("builders") or [{}])[0]
        print(f"  下了 8 个计划 → plans={b0.get('plans')}")
        for p in (b0.get("planList") or [])[:8]:
            print(f"    {json.dumps(p, ensure_ascii=False)}")
    else:
        print("  找不到 8 格连续空地")

    # ---- A2/补1：建一台钻机，看它实际往哪推 ----
    print("\n== A2/补1 钻机的实测 sendsTo ==")
    mine = None
    for y in range(cy - 40, cy + 41):
        for x in range(cx - 40, cx + 41):
            t = a.map(x, y, 1, 1)
            if not t:
                continue
            t = t[0]
            if not t.get("visible"):
                continue
            if t.get("drop") == "copper" and (t.get("block") or "air").strip() in ("", "air"):
                # 2x2 钻机需要该格右上方向也空
                t2 = a.map(x + 1, y, 1, 1)
                if t2 and (t2[0].get("block") or "air").strip() in ("", "air"):
                    mine = (x, y)
                    break
        if mine:
            break

    if not mine:
        print("  视野内没找到可放 mechanical-drill 的铜矿格")
        return 0

    mx, my = mine
    print(f"  铜矿格 ({mx},{my})  drop={a.map(mx,my,1,1)[0].get('drop')}  "
          f"hardness={a.map(mx,my,1,1)[0].get('dropHardness')}")
    r = try_place(mx, my, "mechanical-drill", rot=0)
    print(f"  place -> {str(r)[:150]}")

    got = a.poll_until(lambda: a.building_at(mx, my), timeout=120)
    if not got:
        print("  钻机没建起来（材料或路径问题）")
        return 0

    d = a.get("drill").get("drills", [])
    for one in d:
        if one.get("x") == mx and one.get("y") == my:
            print(f"  drill 明细: dominantItem={one.get('dominantItem')} "
                  f"dominantItems={one.get('dominantItems')} tier={one.get('tier')}")

    b = a.building_at(mx, my)
    print(f"  /buildings 回读: rot={b['rotation']}  "
          f"acceptsFrom={b.get('acceptsFrom')}  sendsTo={b.get('sendsTo')}")
    print("\n  解读：钻机输出不受 rotation 控制，sendsTo 是逐个邻格调 acceptItem")
    print("        实测出来的 —— 空着的方位不会出现，有带子接货的才列。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
