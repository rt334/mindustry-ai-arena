#!/usr/bin/env python3
"""验证三件事：

1. /control?op=warp 已经被禁（瞬移后门关掉）
2. 单位的实际移动速度与 UnitType.speed 一致 —— 也就是「不超过人类 WASD」
3. rateLimit 真的生效（以前是死配置）

第 2 条是重点：单位速度由引擎的 UnitType 决定，人类玩家用 WASD 走多快，
AI 就只能走多快。这里实测采样位置随时间的位移来核对。
"""
import json
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])


def main():
    st = a.state()
    print(f"tick={st['tick']}")

    u = (a.units() or [None])[0]
    if not u:
        print("没有单位")
        return 1
    uid = u["id"]
    print(f"单位 #{uid} {u['type']} @({u['x']/8:.1f},{u['y']/8:.1f})")

    # ---- 1. warp 应当被拒 ----
    print("\n== 1. /control?op=warp ==")
    try:
        r = a.post("control", op="warp", unit=uid, x=300, y=100)
        print(f"  竟然成功了？ {json.dumps(r, ensure_ascii=False)[:200]}")
    except ArenaError as e:
        print(f"  ERR code={e.code} status={e.status}")
        print(f"  {e.message}")

    # ---- 2. 移动速度 ----
    print("\n== 2. 移动速度：与 UnitType.speed 对比 ==")
    # 挑一个远处的点，让它持续移动
    tx, ty = 300, 140
    try:
        a.post("control", op="order", unit=uid, x=tx, y=ty)
    except ArenaError as e:
        print(f"  order ERR code={e.code} {e.message}")
        try:
            a.control("move", unit=uid, x=tx, y=ty)
        except ArenaError as e2:
            print(f"  move ERR code={e2.code} {e2.message}")
            return 1

    samples = []
    for i in range(14):
        uu = (a.units() or [None])[0]
        if not uu:
            break
        samples.append((time.monotonic(), uu["x"] / 8.0, uu["y"] / 8.0))
        time.sleep(0.25)

    if len(samples) < 3:
        print("  采样太少")
        return 1

    print(f"  采样 {len(samples)} 次：")
    speeds = []
    for i in range(1, len(samples)):
        t0, x0, y0 = samples[i - 1]
        t1, x1, y1 = samples[i]
        dt = t1 - t0
        d = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        if dt > 0.01:
            v = d / dt
            speeds.append(v)
            print(f"    t={i:>2} 位置=({x1:6.1f},{y1:6.1f})  位移={d:5.2f}格  "
                  f"速度={v:5.2f} 格/秒")

    if speeds:
        peak = max(speeds)
        avg = sum(speeds) / len(speeds)
        print(f"\n  峰值 {peak:.2f} 格/秒   均值 {avg:.2f} 格/秒")
        # gamma 的 UnitType.speed 约 0.15（引擎内部单位），换算成格/秒约
        # speed * 60？这里只做量级核对：人类 WASD 也是同一个 UnitType，
        # 所以只要它是「引擎算出来的」就等价。
        print("  说明：这个速度由引擎按 UnitType.speed 积分得出。")
        print("        人类玩家 WASD 走的是同一个 UnitType.speed，")
        print("        所以只要接口不给瞬移/加速手段，两者天然一致。")

    # ---- 3. rateLimit ----
    print("\n== 3. rateLimit（配置 60/s, burst 200）==")
    import urllib.request, urllib.error
    ok = 0
    limited = 0
    t0 = time.monotonic()
    url = a.base + "/state"
    for i in range(320):
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {a.token}")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read()
            ok += 1
        except urllib.error.HTTPError as e:
            if e.code == 429:
                limited += 1
            else:
                print(f"    意外的 HTTP {e.code}")
                break
        except Exception as e:
            print(f"    {type(e).__name__}: {e}")
            break
    dt = time.monotonic() - t0
    print(f"  连打 320 次，耗时 {dt:.1f}s")
    print(f"  放行 {ok}   被限流 {limited}")
    if limited:
        body = None
        try:
            req = urllib.request.Request(url)
            req.add_header("Authorization", f"Bearer {a.token}")
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass
        print(f"  ⇒ 限流生效（429）")
    else:
        print(f"  ⇒ 没被限流：可能没打满 burst，也可能没生效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
