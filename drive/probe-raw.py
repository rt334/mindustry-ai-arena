#!/usr/bin/env python3
"""用裸 HTTP 探清三件事 —— 客户端库会把细节吞掉，这里直接看原始响应。

  1. /place 对 shock-mine 返回 400 但 arena.py 只拿到 "HTTP 400"。
     服务端到底有没有写 body？状态码是多少？
  2. 哪些 1x1 方块在这个局面上真的可建 —— 用来造 missingMaterials。
  3. 限流端点：/ping 不在 /v1/<agent>/ 下（返回 1002 unknown action），
     确认哪个端点才是有效的，以及打多少次才触发 1429。
"""
import json
import sys
import urllib.error
import urllib.request

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])
TOK = toks["beta"]
BASE = a.base


def raw(path, method="GET", params=None):
    url = BASE + path
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {TOK}")
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"


core = next(b for b in a.buildings() if b["block"].startswith("core"))
cx, cy = core["x"], core["y"]
print(f"核心 ({cx},{cy})  {core['items']}")
print(f"a.base = {a.base}（已含 /v1/beta，所以路径只写动作名）\n")

# ── 1. 逐块试建，看原始响应 ────────────────────────────────────────────
print("== 1. /place 原始响应（核心正下方 (289,107)，1x1）==")
for blk in ("conveyor", "router", "shock-mine", "plastanium-conveyor",
            "phase-conveyor", "door", "sorter", "unloader"):
    st, body = raw("/place", "POST",
                   {"x": cx, "y": cy + 3, "block": blk, "rot": 0})
    b = body if len(body) <= 170 else body[:170] + "…"
    print(f"  {blk:<22} HTTP {st}  {b}")

st, body = raw("/queue", "POST", {"clear": "true"})
print(f"\n  清理 → HTTP {st} {body}")

# ── 2. 端点核对 ────────────────────────────────────────────────────────
print("\n== 2. 端点核对 ==")
for p in ("/state", "/ping", "/diag", "/buildings"):
    st, body = raw(p)
    print(f"  GET {a.base + p:<44} HTTP {st}  {body[:70]}")
st, body = raw("/ping")   # 注意：这是 /v1/beta/ping
root = a.base.rsplit("/v1/", 1)[0] + "/ping"
try:
    with urllib.request.urlopen(urllib.request.Request(root), timeout=8) as r:
        print(f"  GET {root:<44} HTTP {r.status}  {r.read().decode()[:70]}")
except Exception as e:
    print(f"  GET {root:<44} → {type(e).__name__}: {e}")

# ── 3. 打多少次才触发限流（burst 200 + 60/s）───────────────────────────
print("\n== 3. 限流触发点（burst=200, refill=60/s）==")
import time
n_ok = n_429 = 0
first_429 = None
other = None
t0 = time.monotonic()
for i in range(700):
    st, body = raw("/state")
    if st == 200:
        n_ok += 1
    elif st == 429:
        n_429 += 1
        if first_429 is None:
            first_429 = i
            print(f"  首次 429 在第 {i} 次：{body[:160]}")
    else:
        other = (i, st, body[:100])
        print(f"  第 {i} 次意外 HTTP {st}: {body[:100]}")
        break
dt = time.monotonic() - t0
print(f"  共 {n_ok + n_429} 次，耗时 {dt:.1f}s，放行 {n_ok}，限流 {n_429}")
if first_429 is not None:
    print(f"  理论容量 = 200 + {dt:.1f}s × 60 ≈ {200 + dt*60:.0f}")
