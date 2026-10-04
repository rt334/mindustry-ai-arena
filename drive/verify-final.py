#!/usr/bin/env python3
"""最终验证：结构判定稳定性 / 1008 状态码 / 队列非空样本。"""
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
        return f"ERR", e


def find_free_line(start_y, need):
    core = next(b for b in a.buildings() if b["block"].startswith("core"))
    cx, cy = core["x"], core["y"]
    for y in range(start_y, start_y + 30):
        run = []
        for x in range(cx - 20, cx + 30):
            t = a.map(x, y, 1, 1)
            if t and t[0].get("visible") and (t[0].get("block") or "air").strip() in ("", "air"):
                run.append(x)
                if len(run) >= need:
                    return run[0]
            else:
                run = []
    return None


def main():
    core = next(b for b in a.buildings() if b["block"].startswith("core"))
    cx, cy = core["x"], core["y"]
    print(f"tick={a.state()['tick']}  核心锚点 ({cx},{cy})  {core['items']}")

    # ---- 1008 的 HTTP 状态码 ----
    print("\n== 1008 应当映射到 409 Conflict ==")
    st, e = try_place(cx + 2, cy + 2, "conveyor", rot=0)
    print(f"  建在核心格上 -> code={e.code} status={e.status}  {e.message[:80]}")

    # ---- 结构判定：钻机挨着谁 ----
    print("\n== 钻机 sendsTo 是否为结构事实 ==")
    mine = None
    for y in range(cy - 45, cy + 46):
        for x in range(cx - 45, cx + 46):
            t = a.map(x, y, 1, 1)
            if not t or not t[0].get("visible"):
                continue
            if t[0].get("drop") == "copper" and (t[0].get("block") or "air").strip() in ("", "air"):
                t2 = a.map(x + 1, y, 1, 1)
                if t2 and (t2[0].get("block") or "air").strip() in ("", "air"):
                    mine = (x, y)
                    break
        if mine:
            break
    if not mine:
        print("  视野内没有可放钻机的铜矿格")
        return 1

    mx, my = mine
    try_place(mx, my, "mechanical-drill", rot=0)
    got = a.poll_until(lambda: a.building_at(mx, my), timeout=120)
    print(f"  钻机 ({mx},{my}) 建成={bool(got)}  2x2 → footprint x[{mx},{mx+1}] y[{my},{my+1}]")
    d = a.building_at(mx, my)
    print(f"  建成时 sendsTo = {d.get('sendsTo')}（周围还没东西，应为 None）")

    # 在钻机正下方放带子
    bx, by = mx, my + 2
    print(f"\n  在 ({bx},{by}) 放带子（钻机正下方，属侧面）")
    try_place(bx, by, "conveyor", rot=0)
    a.poll_until(lambda: a.building_at(bx, by), timeout=90)

    d2 = a.building_at(mx, my)
    belt = a.building_at(bx, by)
    print(f"  钻机 sendsTo     = {d2.get('sendsTo')}   ← 应含 [{bx},{by}]")
    print(f"  带子 acceptsFrom = {belt.get('acceptsFrom')}   ← 应含 [{mx},{my+1}]（钻机下半，在带子北侧）")
    print(f"  带子 sendsTo     = {belt.get('sendsTo')}")

    # 等带子上有货，再看钻机 sendsTo 是否随 minitem 抖动
    a.poll_until(lambda: (a.building_at(bx, by) or {}).get("items"), timeout=120)
    b3 = a.building_at(bx, by)
    d3 = a.building_at(mx, my)
    print(f"\n  带子上出现货后：items={b3.get('items')}")
    print(f"  钻机 sendsTo = {d3.get('sendsTo')}   ← 结构判定，不应变空")

    # ---- 队列非空 ----
    print("\n== 队列积压时的 planList ==")
    x0 = find_free_line(cy + 30, 40)
    if x0 is None:
        print("  找不到足够长的空地行")
        return 0
    placed = 0
    for i in range(40):
        st, _v = try_place(x0 + i, cy + 30 + (i // 20), "conveyor", rot=0)
        if st == "OK":
            placed += 1
    q = a.queue()
    b0 = (q.get("builders") or [{}])[0]
    print(f"  连下 {placed} 个后立刻查：plans={b0.get('plans')}")
    for p in (b0.get("planList") or [])[:5]:
        print(f"    {json.dumps(p, ensure_ascii=False)}")
    lst = b0.get("planList") or []
    if len(lst) > 5:
        print(f"    ...（共 {len(lst)} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
