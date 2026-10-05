#!/usr/bin/env python3
"""复测限流（加大强度）+ 核对 gamma 的 UnitType.speed。

上一轮打 320 次没触发：桶初始 200，3 秒里又补 3×60=180，总容量 380 —— 320 根本没打满。
这次打到 900 次，并记录触发点。
"""
import json
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])


def main():
    # ---- gamma 的速度 ----
    print("== gamma 的 UnitType 属性 ==")
    ct = a.get("content")
    units = ct.get("units") or []
    g = next((u for u in units if u.get("name") == "gamma"), None)
    print(f"  /content.units 里的 gamma: {json.dumps(g, ensure_ascii=False)}")
    u0 = (a.units() or [None])[0]
    print(f"  /units 当前单位: type={u0.get('type')} 字段={list(u0.keys())}")

    # ---- 限流：打到触发为止 ----
    print("\n== rateLimit 复测（目标 > 380 次）==")
    url = a.base + "/state"
    ok = limited = 0
    first_limit_at = None
    other = None
    t0 = time.monotonic()
    for i in range(900):
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {a.token}")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read()
            ok += 1
        except urllib.error.HTTPError as e:
            if e.code == 429:
                limited += 1
                if first_limit_at is None:
                    first_limit_at = i
                    try:
                        body = e.read().decode("utf-8")
                    except Exception:
                        body = ""
                    print(f"  首次限流在第 {i} 次：HTTP 429")
                    print(f"    body = {body[:160]}")
            else:
                other = e.code
                break
        except Exception as e:
            print(f"  {type(e).__name__}: {e}")
            break
    dt = time.monotonic() - t0

    print(f"\n  连打 {ok + limited} 次，耗时 {dt:.1f}s（约 {(ok+limited)/max(dt,0.001):.0f} 次/秒）")
    print(f"  放行 {ok}   限流 {limited}" + (f"   其它错误 {other}" if other else ""))
    if first_limit_at is not None:
        print(f"  ⇒ 限流生效。首次触发点与「桶容量 + 补充速率」吻合：")
        print(f"     桶 200 + 补充 {dt:.1f}s × 60/s ≈ {200 + dt*60:.0f}，实测首次触发于第 {first_limit_at} 次")
    else:
        print("  ⇒ 仍未触发，需要查 takeToken 是否被调用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
