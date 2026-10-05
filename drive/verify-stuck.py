#!/usr/bin/env python3
"""验证修正后的停滞判据：正常建造**不应**出现 stuckSeconds。

上一版判据只看 progress 不变，会把「单位还在赶路」（progress 恒为 0）误报成停滞。
现在的判据是「进度不变 **且** 单位位置也不动」。

这里下一个远一点的计划，观察一段时间里的每一条 plan：
只要单位在走，就不该带 stuckSeconds。
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


def main():
    core = next(b for b in a.buildings() if b["block"].startswith("core"))
    cx, cy = core["x"], core["y"]
    g = load_grid(cx, cy)
    print(f"tick={a.state()['tick']}  核心 ({cx},{cy})")

    # 挑离核心最远的空地，逼单位走一段路
    cands = [(x, y) for y in range(cy - 26, cy + 27) for x in range(cx - 26, cx + 27)
             if free(g, x, y)]
    cands.sort(key=lambda p: -((p[0] - cx) ** 2 + (p[1] - cy) ** 2))
    if not cands:
        print("无空地")
        return 1

    target = cands[0]
    print(f"在最远处 {target} 下一个计划（距离核心约 "
          f"{((target[0]-cx)**2 + (target[1]-cy)**2) ** 0.5:.0f} 格，单位要走过去）")
    try:
        a.place(target[0], target[1], "conveyor", rot=0)
    except ArenaError as e:
        print(f"  ERR {e.code} {e.message}")
        return 1

    print("\n采样 /queue（单位赶路期间 progress 恒为 0，但不应报停滞）：")
    seen_stuck = 0
    for i in range(10):
        q = a.queue()
        b0 = (q.get("builders") or [{}])[0]
        lst = b0.get("planList") or []
        u = (a.units() or [{}])[0]
        if not lst:
            print(f"  #{i} 队列已空（建完了）")
            break
        p = lst[0]
        stuck = p.get("stuckSeconds")
        if stuck is not None:
            seen_stuck += 1
        print(f"  #{i} plans={b0.get('plans')} 首个计划=({p.get('x')},{p.get('y')}) "
              f"progress={p.get('progress')} stuckSeconds={stuck}  "
              f"单位@({u.get('x')/8:.1f},{u.get('y')/8:.1f})")
        import time
        time.sleep(1.0)

    print(f"\n结论：采样中出现 stuckSeconds 的次数 = {seen_stuck}")
    print("      单位在赶路时应当是 0 次；只有真的卡住才会出现")
    return 0


if __name__ == "__main__":
    sys.exit(main())
