#!/usr/bin/env python3
"""向东扩煤矿：主干东延 -> 竖脊 -> 挂矿机。

用接口直接操控，不做任何固定等待（全部 poll_until / 命中即退）。
"""
import argparse
import sys
import time
import urllib.parse
import urllib.request


class A:
    def __init__(self, agent, token, host="127.0.0.1", port=7199):
        self.agent, self.token = agent, token
        self.base = f"http://{host}:{port}/v1/{agent}"

    def _call(self, path, params=None, method="GET"):
        url = f"{self.base}/{path}"
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        req = urllib.request.Request(url, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(req, timeout=20) as r:
            import json
            b = json.loads(r.read().decode())
        return b.get("data") if b.get("ok") else None

    def get(self, p, **q):  return self._call(p, q or None, "GET")
    def post(self, p, **q): return self._call(p, q or None, "POST")
    def place(self, x, y, block, rot=None):
        return self.post("place", x=int(x), y=int(y), block=block, rot=rot)
    def brk(self, x, y): return self.post("break", x=int(x), y=int(y))
    def buildings(self): return self.get("buildings")["buildings"]

    def poll(self, pred, timeout=90.0, interval=0.2):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                v = pred()
            except Exception:
                v = None
            if v:
                return v
            time.sleep(interval)
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="beta")
    ap.add_argument("--token", required=True)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--trunk-y", type=int, default=113)
    ap.add_argument("--trunk-x0", type=int, default=295)
    ap.add_argument("--spine-x", type=int, default=311)
    ap.add_argument("--spine-y0", type=int, default=98)
    ap.add_argument("--spine-y1", type=int, default=112)
    args = ap.parse_args()

    a = A(args.agent, args.token)
    if a.get("state") is None:
        print("服务端无响应", file=sys.stderr)
        return 1

    # 1) 主干东延：y=113, x=295..spine_x，全部 r0（东）
    trunk = [(x, args.trunk_y) for x in range(args.trunk_x0, args.spine_x + 1)]
    # 2) 竖脊：x=spine_x, spine_y0..spine_y1，全部 r1（北 = +y）
    #    从 y=98 一路向南接回 y=113 的主干，方向是 +y，所以 r1
    spine = [(args.spine_x, y) for y in range(args.spine_y0, args.spine_y1 + 1)]

    print(f"主干 {len(trunk)} 格  x={args.trunk_x0}..{args.spine_x} @ y={args.trunk_y}")
    print(f"竖脊 {len(spine)} 格  y={args.spine_y0}..{args.spine_y1} @ x={args.spine_x}")
    print(f"合计 {len(trunk)+len(spine)} 格传送带")

    if args.dry or not args.apply:
        for (x, y) in trunk[:6]:
            print(f"   trunk ({x},{y}) r0")
        print("   ...")
        for (x, y) in spine[:4]:
            print(f"   spine ({x},{y}) r1")
        return 0

    # 西端：把 (294,113) 换成 router 分流 —— 原样是 r3 朝北，不会往东送，
    # 新主干挂上去也没有煤源。
    tap = (args.trunk_x0 - 1, args.trunk_y)
    try:
        a.brk(*tap)
        time.sleep(0.4)
    except Exception as e:
        print(f"   tap break {e}")

    placed = failed = 0
    try:
        r = a.place(tap[0], tap[1], "router")
        print(f"   tap router ({tap[0]},{tap[1]}) -> {'OK' if r else 'FAIL'}")
    except Exception as e:
        failed += 1
        print(f"   FAIL tap {e}")
    for (x, y) in trunk:
        try:
            r = a.place(x, y, "conveyor", 0)
            placed += 1 if r else 0
        except Exception as e:
            failed += 1
            print(f"   FAIL trunk ({x},{y}) {e}")
    for (x, y) in spine:
        try:
            r = a.place(x, y, "conveyor", 1)
            placed += 1 if r else 0
        except Exception as e:
            failed += 1
            print(f"   FAIL spine ({x},{y}) {e}")
    print(f"下单 {placed} 成功 / {failed} 失败")

    # 轮询确认（命中即退）
    want = trunk + spine
    t0 = time.time()
    while time.time() - t0 < 120:
        have = {(b["x"], b["y"]) for b in a.buildings()}
        n = sum(1 for p in want if p in have)
        if n == len(want):
            print(f"✓ 全部 {n} 格建成")
            return 0
        time.sleep(0.3)
    have = {(b["x"], b["y"]) for b in a.buildings()}
    miss = [p for p in want if p not in have]
    print(f"超时：{len(want)-len(miss)}/{len(want)} 建成，缺 {miss[:8]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
