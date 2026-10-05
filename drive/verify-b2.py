#!/usr/bin/env python3
"""B2 专项：buildingAt 是不是只在快照刷新后才会出现。

/units 读的是快照（Snapshot.State），不是实时读引擎 —— 上一版脚本下完计划
立刻查，读到的可能是刷新前的旧快照。这里下足量计划并轮询，把「快照延迟」
和「字段根本没填」区分开。
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
    if not t or not t.get("visible"):
        return False
    return (t.get("block") or "air").strip() in ("", "air")


def main():
    core = next(b for b in a.buildings() if b["block"].startswith("core"))
    cx, cy = core["x"], core["y"]
    g = load_grid(cx, cy)
    print(f"tick={a.state()['tick']}  核心 ({cx},{cy})  {core['items']}")

    # 挑离核心最远的空地，逼单位走路，队列才会持续存在
    cands = [(x, y) for y in range(cy - 26, cy + 27) for x in range(cx - 26, cx + 27)
             if free(g, x, y)]
    cands.sort(key=lambda p: -((p[0] - cx) ** 2 + (p[1] - cy) ** 2))
    print(f"可用空地 {len(cands)} 格")
    if not cands:
        return 1

    placed, errs = 0, {}
    for (x, y) in cands[:25]:
        try:
            a.place(x, y, "conveyor", rot=0)
            placed += 1
        except ArenaError as e:
            errs[e.code] = errs.get(e.code, 0) + 1
    print(f"下了 {placed} 个计划  错误分布={errs}")

    q = a.queue()
    print(f"/queue plans = {(q.get('builders') or [{}])[0].get('plans')}")

    # 轮询 /units 直到 buildingAt 出现
    print("\n轮询 /units.buildingAt：")
    seen = False
    for i in range(14):
        u = (a.units() or [{}])[0]
        ba = u.get("buildingAt")
        st = a.state()
        if ba:
            seen = True
            print(f"  #{i} snapshotFresh={st.get('snapshotFresh')} "
                  f"→ buildingAt={json.dumps(ba, ensure_ascii=False)}")
            if i > 2:
                break
        else:
            print(f"  #{i} snapshotFresh={st.get('snapshotFresh')} → buildingAt=null")
        if not seen:
            import time
            time.sleep(0.5)

    print(f"\n结论：{'字段能读到' if seen else '始终读不到 —— 需要查快照刷新逻辑'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
