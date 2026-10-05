#!/usr/bin/env python3
"""直击两处上限：队列满（1004）与限流（1429）。

上一版两处都测歪了：
  · 批量上限：70 格里 31 格因地形无效，只接受 39 —— 根本没到 60 的坎。
    改成先找一行真正空的地，再逐格下单，看第几条开始被 1004 拒。
  · 限流：走 arena.py 会带退避重试，每次退避期间桶都在回血，永远打不满。
    改成裸 HTTP 不间隔地打，直接观测服务端行为。
"""
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])


def wait_ready(timeout=90):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            if any(b["block"].startswith("core") for b in a.buildings()):
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def main():
    if not wait_ready():
        print("等不到核心")
        return 1
    core = next(b for b in a.buildings() if b["block"].startswith("core"))
    cx, cy = core["x"], core["y"]
    print(f"核心 ({cx},{cy})\n")

    # ── 1. 找一行真正空的地 ────────────────────────────────────────────
    print("== 1. 找一行空地在哪（用 /map 的 block 字段，不看墙以外的判据）==")
    R = 30
    tiles = a.map(cx - R, cy - R, 2 * R + 1, 2 * R + 1)
    g = {(t["x"], t["y"]): t for t in tiles}

    def free(x, y):
        t = g.get((x, y))
        if t is None or not t.get("visible"):
            return False
        return (t.get("block") or "air").strip() in ("", "air")

    best, best_y = None, None
    for y in range(cy - R, cy + R + 1):
        run = 0
        for x in range(cx - R, 2 * R + 1 + cx - R):
            run = run + 1 if free(x, y) else 0
            if best is None or run > best:
                best, best_y = run, y
    print(f"  最长连续空地：{best} 格，在 y={best_y}")
    if best < 70:
        print("  不够 70 格，改成用这一段")

    y = best_y
    xs = []
    run = 0
    for x in range(cx - R, cx + R + 1):
        if free(x, y):
            if not xs or x == xs[-1] + 1:
                xs.append(x)
            else:
                if len(xs) >= 70:
                    break
                xs = [x]
        else:
            if len(xs) >= 70:
                break
            xs = []
    xs = xs[:80]
    print(f"  取 x {xs[0]}..{xs[-1]}（{len(xs)} 格）\n")

    # ── 2. 逐格下单，看第几条被 1004 拒 ────────────────────────────────
    print("== 2. 队列满（Actor.java:95 的 plans.size >= 60 → 1004）==")
    accepted = 0
    first_1004 = None
    for i, x in enumerate(xs):
        try:
            a.post("place", x=x, y=y, block="mechanical-drill" if False else "conveyor", rot=0)
            accepted += 1
        except ArenaError as e:
            if e.code == 1004:
                first_1004 = i
                print(f"  第 {i} 次下单被拒：code=1004  {e.message[:150]}")
                break
            print(f"  第 {i} 次 {x} 其它拒绝 {e.code}: {e.message[:90]}")
        time.sleep(0.02)          # 比建造速度略快，把队列堆起来
    print(f"  接受 {accepted} 条")

    if first_1004 is None:
        print("  没撞到 1004 —— 建造速度跟得上，队列堆不起来")
        cap_ok = None
    else:
        q = a.queue()
        plans = sum(b.get("plans", 0) for b in (q.get("builders") or []))
        print(f"  此刻队列 = {plans} 条")
        cap_ok = (first_1004 >= 55)      # 应接近 60
    try:
        r = a.post("queue", clear="true")
        print(f"  清队列 → {r}")
    except ArenaError as e:
        print(f"  清队列失败 {e.code}")

    # ── 3. 裸 HTTP 打限流 ─────────────────────────────────────────────
    print("\n== 3. 限流（裸 HTTP，不间隔，不走客户端退避）==")
    base = a.base
    tok = toks["beta"]

    def raw(path):
        req = urllib.request.Request(base + path)
        req.add_header("Authorization", f"Bearer {tok}")
        try:
            with urllib.request.urlopen(req, timeout=6) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")
        except Exception as e:
            return -1, f"{type(e).__name__}: {e}"

    n_ok = n_429 = 0
    first = None
    t0 = time.monotonic()
    for i in range(800):
        st, body = raw("/state")
        if st == 200:
            n_ok += 1
        elif st == 429:
            n_429 += 1
            if first is None:
                first = i
                print(f"  首次 429 在第 {i} 次：{body[:120]}")
        else:
            print(f"  第 {i} 次意外 {st}: {body[:100]}")
            break
    dt = time.monotonic() - t0
    print(f"  共 {n_ok + n_429} 次 / {dt:.1f}s：放行 {n_ok}，限流 {n_429}")
    rate_ok = n_429 > 0
    if first is not None:
        print(f"  理论容量 = 200 + {dt:.1f}×60 ≈ {200 + dt*60:.0f}")

    print("\n== 小结 ==")
    print(f"  队列上限 1004    {'✓' if cap_ok else ('--' if cap_ok is None else '✗')}")
    print(f"  限流 1429        {'✓' if rate_ok else '✗'}")
    return 0 if (cap_ok is not False and rate_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
