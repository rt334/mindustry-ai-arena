#!/usr/bin/env python3
"""验证 cursor_expired（1006 / HTTP 410）契约。

服务端以 -Darena.eventlog.capacity=16 启动，所以攒 20 来条事件缓冲就绕圈了，
firstSeq 前进之后 since=1 就该被判过期。

顺带核对两件契约上的事：
  · since=0 永远不过期（错误信息里让人「resync with since=0」，它必须真的能用）
  · 过期时返回 410 + code 1006，且消息里指出该从哪重新同步
"""
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])


def wait_ready(timeout=120):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            if any(b["block"].startswith("core") for b in a.buildings()):
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def water():
    r = a.get("events", since=0, limit=1)
    return r.get("nextSince")


def main():
    if not wait_ready():
        print("等不到核心")
        return 1
    core = next(b for b in a.buildings() if b["block"].startswith("core"))
    cx, cy = core["x"], core["y"]
    n0 = water()
    print(f"核心 ({cx},{cy})   起始事件水位 nextSince={n0}")
    print("（容量 16，攒够就绕圈）\n")

    # ── 制造事件：放置 + 拆除，直到缓冲绕圈 ────────────────────────────
    print("== 制造事件 ==")
    for cycle in range(6):
        for (shape, extra) in (("place", {"block": "conveyor"}), ("break", {})):
            params = dict(shape="rect", x1=cx - 14, y1=cy - 6, x2=cx + 5, y2=cy - 2)
            params.update(extra)
            try:
                a.post(shape, **params)
            except ArenaError as e:
                print(f"  cycle {cycle} {shape} → {e.code} {e.message[:70]}")
            time.sleep(0.8)
        n = water()
        print(f"  cycle {cycle}: nextSince={n}")
        if n and n > 40:
            break

    n1 = water()
    print(f"\n  水位 {n0} → {n1}")

    # ── 判定 ───────────────────────────────────────────────────────────
    ok = {}
    print("\n== 1. since=0 应当永远可用（错误信息让人 resync 到它）==")
    try:
        r = a.get("events", since=0, limit=3)
        evs = r.get("events") or []
        ok["since0"] = True
        print(f"  ✓ since=0 → nextSince={r.get('nextSince')}  拿到 {len(evs)} 条")
    except ArenaError as e:
        ok["since0"] = False
        print(f"  ✗ since=0 竟然失败 code={e.code} {e.message[:120]}")

    print("\n== 2. 陈旧游标 since=1 应当 1006 / 410 ==")
    try:
        r = a.get("events", since=1, limit=3)
        ok["expired"] = False
        print(f"  ✗ 没报过期，返回了 nextSince={r.get('nextSince')} —— "
              f"缓冲可能还没绕圈（水位 {n1}）")
    except ArenaError as e:
        print(f"  code={e.code}  status={getattr(e, 'status', None)}")
        print(f"  message = {e.message[:180]}")
        ok["expired"] = (e.code == 1006 and getattr(e, "status", None) == 410)

    print("\n== 3. 边界：since = firstSeq-1 与 firstSeq-2 ==")
    # 从错误信息里拿不到 firstSeq，用二分找临界点
    lo, hi = 1, n1 or 40
    for probe in (1, 2, 3, 5, 9, 17):
        try:
            a.get("events", since=probe, limit=1)
            print(f"  since={probe:<4} 可用")
        except ArenaError as e:
            print(f"  since={probe:<4} 过期（code={e.code}）")

    print("\n== 小结 ==")
    for k, v in ok.items():
        print(f"  {k:<12} {'✓' if v else '✗'}")
    return 0 if all(ok.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
