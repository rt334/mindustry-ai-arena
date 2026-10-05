#!/usr/bin/env python3
"""验证 stuckReason 的最后一个取值：tileOccupied。

语义（Operations.whyStuck）：计划所在格**已经有实体建筑**了。
难点是时序 —— `/place` 在提交时会拒「已有实体建筑」的格（1008），
所以在正常流程里造不出来。

**绕法**：`validPlace` 只看**建筑**与地形，不看**计划**。所以

    1. 先排一个 2x2 大方块的计划（它的脚印盖住目标格 T），排在队首
    2. 紧接着在 T 排一个 1x1 —— 此时 T 只有计划、没有建筑，**能下单**
    3. 建造按队列顺序走，2x2 先建成，把 T 占掉
    4. T 上的 1x1 计划 → 卡住，原因就是 tileOccupied

这不是钻空子：它正是「下完单之后那格才被占掉」这种真实时序，
也就是 whyStuck 注释里写的那一类。
"""
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

BIG = "graphite-press"      # 2x2，不需要矿，成本 copper 75 + lead 30


def main():
    toks, _ = load_tokens()
    a = Arena("beta", toks["beta"])

    core = None
    t0 = time.monotonic()
    while time.monotonic() - t0 < 120:
        try:
            core = next((b for b in a.buildings() if b["block"].startswith("core")), None)
        except Exception:
            core = None
        if core:
            break
        time.sleep(1)
    if not core:
        print("等不到核心")
        return 1
    cx, cy = core["x"], core["y"]
    print(f"核心 ({cx},{cy})  {core['items']}")

    # ── 找一块 4x4 空地 ──────────────────────────────────────────────
    bs = {(b["x"], b["y"]) for b in a.buildings()}
    ts = a.map(cx - 20, cy - 20, 41, 41)
    g = {(t["x"], t["y"]): t for t in ts}

    def free(x, y, w=4, h=4):
        for dy in range(h):
            for dx in range(w):
                t = g.get((x + dx, y + dy))
                if not t or (t.get("block") or "air").strip() not in ("", "air"):
                    return False
                if (x + dx, y + dy) in bs:
                    return False
        return True

    spot = None
    for y in range(cy - 20, cy + 21):
        for x in range(cx - 20, cx + 21):
            if free(x, y):
                spot = (x, y)
                break
        if spot:
            break
    if not spot:
        print("找不到 4x4 空地")
        return 1
    sx, sy = spot
    # 2x2 放在 (sx,sy)，目标格 T 取它的右下角 —— 保证 T 被脚印盖住
    T = (sx + 1, sy + 1)
    print(f"空地 ({sx},{sy})；大块放 ({sx},{sy})，1x1 放它的右下角 T={T}")

    # ── 1. 先排 2x2（队首）────────────────────────────────────────────
    print(f"\n== 1. 先排 {BIG} 2x2 于 ({sx},{sy}) ==")
    try:
        r = a.post("place", x=sx, y=sy, block=BIG, rot=0)
        print(f"  ✓ pendingPlans={r.get('pendingPlans')} mode={r.get('mode')}")
    except ArenaError as e:
        print(f"  ✗ {e.code} {e.message[:120]}")
        return 1
    time.sleep(0.4)

    # ── 2. 紧接着在 T 排 1x1（此时 T 只有计划，没有建筑）────────────
    print(f"\n== 2. 紧接着在 T={T} 排 1x1（关键：此刻 T 只有计划、没有建筑）==")
    try:
        r = a.post("place", x=T[0], y=T[1], block="conveyor", rot=0)
        print(f"  ✓ pendingPlans={r.get('pendingPlans')} mode={r.get('mode')}")
    except ArenaError as e:
        print(f"  ✗ {e.code} {e.message[:160]}")
        print("     —— 如果这里是 1008，说明 validPlace 也看计划，这个绕法不成立")
        return 1

    # ── 3. 等 2x2 建成、T 被占 ───────────────────────────────────────
    print("\n== 3. 等 2x2 建成（判据是 /buildings 里出现它）==")
    t0 = time.monotonic()
    while time.monotonic() - t0 < 120:
        try:
            got = {(b["x"], b["y"]): b["block"] for b in a.buildings()}
        except Exception:
            got = {}
        if (sx, sy) in got:
            print(f"  ✓ ({sx},{sy}) {got[(sx,sy)]} 已建成")
            break
        time.sleep(1)
    else:
        print("  超时")

    # ── 4. 看 T 上的计划报什么 ───────────────────────────────────────
    print("\n== 4. T 上的计划现在报什么 ==")
    t0 = time.monotonic()
    found = None
    while time.monotonic() - t0 < 60:
        q = a.queue()
        for b in (q.get("builders") or []):
            for p in (b.get("planList") or []):
                if (p.get("x"), p.get("y")) == T:
                    found = p
                    break
            if found:
                break
        if found and found.get("stuckReason"):
            break
        time.sleep(2)

    if not found:
        print("  T 上的计划已不在队列里 —— 它可能被建成或已被丢弃")
        return 1
    print(f"  ({found.get('x')},{found.get('y')}) {found.get('block')}")
    print(f"    stuckSeconds = {found.get('stuckSeconds')}")
    print(f"    stuckReason  = {found.get('stuckReason')}")
    print(f"    hint         = {found.get('hint')}")
    print()
    if str(found.get("stuckReason", "")).startswith("tileOccupied"):
        print("  **tileOccupied：通过** —— stuckReason 四种取值全部实测到位")
        return 0
    print(f"  **没拿到 tileOccupied** —— 实际是 {found.get('stuckReason')!r}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
