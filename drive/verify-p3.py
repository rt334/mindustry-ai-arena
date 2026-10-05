#!/usr/bin/env python3
"""验证补3（计划停滞）并回答 B4（/events 能不能替代全量拉 /buildings）。

B4 的问题：每做一步都要重拉全量 /buildings（250+ 条）来对比变化。
如果 /events 的差分补齐已经覆盖了 buildAppear / buildGone，那 B4 就已经满足，
只是文档没把「用 /events 增量」这条路指出来。

这里实测：连续建几个方块，看 /events 是否真的报出对应的建筑变化事件。
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


def find_row(g, cx, cy, n):
    for y in range(cy - 25, cy + 26):
        run = []
        for x in range(cx - 25, cx + 26):
            if free(g, x, y):
                run.append(x)
                if len(run) >= n:
                    return run[0], y
            else:
                run = []
    return None


def main():
    core = next(b for b in a.buildings() if b["block"].startswith("core"))
    cx, cy = core["x"], core["y"]
    print(f"tick={a.state()['tick']}  核心 ({cx},{cy})")

    # ---------- B4：先记录当前事件游标 ----------
    ev0 = a.get("events", since=0, limit=1)
    print(f"\n== B4 /events 的游标 ==")
    print(f"  字段: {list(ev0.keys())}")
    cur = ev0.get("nextSince") or ev0.get("since") or 0
    print(f"  当前游标 nextSince={cur}")

    g = load_grid(cx, cy)
    row = find_row(g, cx, cy, 5)
    if not row:
        print("找不到空地")
        return 1
    rx, ry = row

    # ---------- 建几个方块，触发事件 ----------
    print(f"\n== 建 5 个 conveyor 到 ({rx},{ry})..({rx+4},{ry}) ==")
    for i in range(5):
        try:
            a.place(rx + i, ry, "conveyor", rot=0)
        except ArenaError as e:
            print(f"  ({rx+i},{ry}) ERR {e.code}")

    a.poll_until(lambda: all((b := a.building_at(rx + i, ry)) for i in range(5)), timeout=150)

    # ---------- 增量拉事件 ----------
    ev = a.get("events", since=cur, limit=200)
    events = ev.get("events") or []
    print(f"\n  自游标 {cur} 起拿到 {len(events)} 条事件")
    kinds = {}
    for e in events:
        k = e.get("type")
        kinds[k] = kinds.get(k, 0) + 1
    print(f"  类型分布: {kinds}")

    build_evs = [e for e in events if e.get("type") in
                 ("buildAppear", "buildGone", "buildEnd", "buildStart", "configure")]
    print(f"  与建筑相关的事件 {len(build_evs)} 条：")
    for e in build_evs[:8]:
        print(f"    {json.dumps(e, ensure_ascii=False)[:150]}")

    # ---------- 对比：全量 /buildings 有多大 ----------
    allb = a.buildings()
    units = a.units()
    print(f"\n  对照：全量 /buildings = {len(allb)} 条 / /units = {len(units)} 条")
    print(f"  ⇒ /events 增量 {len(build_evs)} 条 vs 全量 {len(allb)} 条")

    # ---------- 补3：计划停滞字段 ----------
    print("\n== 补3 /queue 的 stuckSeconds ==")
    g2 = load_grid(cx, cy)
    row2 = find_row(g2, cx, cy, 4)
    if row2:
        rx2, ry2 = row2
        for i in range(4):
            try:
                a.place(rx2 + i, ry2, "conveyor", rot=0)
            except ArenaError:
                pass
        q = a.queue()
        b0 = (q.get("builders") or [{}])[0]
        print(f"  plans={b0.get('plans')}")
        for p in (b0.get("planList") or [])[:4]:
            print(f"    {json.dumps(p, ensure_ascii=False)[:200]}")
        print("  （stuckSeconds 只在进度连续 3 秒不动时才出现，正常建造不会带）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
