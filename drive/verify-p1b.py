#!/usr/bin/env python3
"""补验 A7 / B2 / 补2。

上一版三处失败都是脚本自己的问题：
  A7  poll 只等「该格有建筑」，命中的是原本那条 conveyor，sorter 还没替换完成
  B2  挑的空地用的是几分钟前的地图快照，下的计划全撞在已建好的带子上，队列是空的
  补2  没造出堵点

这一次：重新拉图、按方块名确认、并且造一个真实的缺料场景。
"""
import json
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])
R = 30


def load_grid(cx, cy, r=R):
    w = 2 * r + 1
    return {(t["x"], t["y"]): t for t in a.map(cx - r, cy - r, w, w)}


def free(g, x, y):
    t = g.get((x, y))
    if not t or not t.get("visible"):
        return False
    return (t.get("block") or "air").strip() in ("", "air")


def find_rect(g, cx, cy, w, h):
    for y in range(cy - 26, cy + 27 - h):
        for x in range(cx - 26, cx + 27 - w):
            if all(free(g, x + dx, y + dy) for dy in range(h) for dx in range(w)):
                return x, y
    return None


def bidx():
    return {(b["x"], b["y"]): b for b in a.buildings()}


def main():
    core = next(b for b in a.buildings() if b["block"].startswith("core"))
    cx, cy = core["x"], core["y"]
    print(f"tick={a.state()['tick']}  核心 ({cx},{cy})  {core['items']}")

    g = load_grid(cx, cy)

    # ================= A7 · 真·空地放 sorter =================
    print("\n== A7 /place 的 config ==")
    spot = find_rect(g, cx, cy, 1, 1)
    if not spot:
        print("  找不到空地")
        return 1
    tx, ty = spot
    print(f"  空地 ({tx},{ty})，放 sorter config=coal")
    try:
        r = a.post("place", x=tx, y=ty, block="sorter", config="coal")
        print(f"  完整响应: {json.dumps(r, ensure_ascii=False)}")
    except ArenaError as e:
        print(f"  ERR code={e.code} status={e.status} {e.message}")
        r = None

    # 对照：给一个不支持该配置的方块传 config，看警告
    spot2 = find_rect(g, cx, cy, 1, 1)
    if spot2 and spot2 != spot:
        try:
            r2 = a.post("place", x=spot2[0], y=spot2[1], block="conveyor", config="coal")
            print(f"  对照(conveyor+config): {json.dumps(r2, ensure_ascii=False)}")
        except ArenaError as e:
            print(f"  对照 ERR code={e.code} {e.message}")

    got = a.poll_until(
        lambda: (bidx().get((tx, ty)) or {}).get("block") == "sorter", timeout=150)
    if got:
        b = bidx().get((tx, ty))
        print(f"  sorter 建成  config = {b.get('config')!r}   ← 期望 'coal' 或 item 名")
    else:
        print(f"  sorter 未建成，当前该格 = {(bidx().get((tx,ty)) or {}).get('block')}")

    # ================= B2 · 下计划后立刻查 =================
    print("\n== B2 /units 的 buildingAt ==")
    g2 = load_grid(cx, cy)  # 重新拉，别用旧快照
    row = find_rect(g2, cx, cy, 6, 1)
    if row:
        rx, ry = row
        placed = 0
        for i in range(6):
            try:
                a.place(rx + i, ry, "conveyor", rot=0)
                placed += 1
            except ArenaError as e:
                print(f"    ({rx+i},{ry}) ERR code={e.code}")
        u = (a.units() or [{}])[0]
        print(f"  下了 {placed} 个计划到 ({rx},{ry})..({rx+5},{ry})")
        print(f"  unit {u.get('id')} {u.get('type')}  buildingAt = "
              f"{json.dumps(u.get('buildingAt'), ensure_ascii=False)}")

        # 再轮询看 progress 会不会动
        prev = None
        for _ in range(6):
            u2 = (a.units() or [{}])[0]
            ba = u2.get("buildingAt")
            if ba:
                print(f"    progress={ba.get('progress'):.3f} block={ba.get('block')} "
                      f"@({ba.get('x')},{ba.get('y')})")
                if prev is not None and ba.get("progress") == prev:
                    break
                prev = ba.get("progress")
            else:
                print("    buildingAt 消失（队列已清空）")
                break
    else:
        print("  找不到 6x1 空地")

    # ================= 补2 · 造一个缺料场景 =================
    print("\n== 补2 /stalls 的 cause ==")
    g3 = load_grid(cx, cy)
    spot3 = find_rect(g3, cx, cy, 3, 3)
    if spot3:
        sx, sy = spot3
        print(f"  在 ({sx},{sy}) 放孤立 silicon-smelter（不给煤和沙）")
        try:
            a.post("place", x=sx, y=sy, block="silicon-smelter", rot=0)
        except ArenaError as e:
            print(f"  place ERR code={e.code} {e.message}")
        ok = a.poll_until(
            lambda: (bidx().get((sx, sy)) or {}).get("block") == "silicon-smelter",
            timeout=150)
        print(f"  建成: {ok}")
        if ok:
            # 等它被 StallWatch 采样到
            st = a.poll_until(lambda: [s for s in a.stalls() if s["x"] == sx
                                       and s["y"] == sy], timeout=90)
            if st:
                s = st[0]
                print(f"  stall: kind={s.get('kind')} cause={s.get('cause')} "
                      f"eff={s.get('efficiency')} outputAccepts={s.get('outputAccepts')}")
                print(f"  missing={json.dumps(s.get('missing'), ensure_ascii=False)}")
                print(f"  ⇒ cause 期望 'starved'（上游没来货）")
            else:
                print("  StallWatch 还没采样到它")

    all_st = a.stalls()
    print(f"\n  当前全部 stall ({len(all_st)} 条):")
    for s in all_st[:8]:
        print(f"    ({s['x']},{s['y']}) {s['block']:<18} kind={s.get('kind'):<14} "
              f"cause={s.get('cause')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
