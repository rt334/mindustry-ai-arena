#!/usr/bin/env python3
"""全图普查：把某一区域的地表与矿脉信息拉下来做汇总。

⚠ 视野决定结果。用队伍 token 只能拿到自己视野内的一小块，
据此推算的任何「上限」都会严重偏低，而且错得很安静 ——
数字看起来完全合理，只是偏小。

所以**做容量评估前先看覆盖比例**：脚本会打印
`可见 / 查询`，低于全图就别对「能到多少」下结论。
admin token 加 `--view-all` 才能看全图。

用法：
    python survey.py --token <admin> --view-all
    python survey.py --token <team>              # 只看己方视野
"""
import argparse
import collections
import sys

from arena import Arena


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="referee")
    ap.add_argument("--token", required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7199)
    ap.add_argument("--view-all", action="store_true",
                    help="用 view=all 看全图（仅 admin token 有效）")
    ap.add_argument("--x0", type=int, default=0)
    ap.add_argument("--y0", type=int, default=0)
    ap.add_argument("--w", type=int, default=350)
    ap.add_argument("--h", type=int, default=200)
    ap.add_argument("--step", type=int, default=40)
    args = ap.parse_args()

    a = Arena(args.agent, args.token, args.host, args.port)
    if not a.ping():
        print("服务端离线", file=sys.stderr)
        return 1

    ore = collections.defaultdict(list)
    floors = collections.Counter()
    visible = total = 0

    for bx in range(args.x0, args.x0 + args.w, args.step):
        for by in range(args.y0, args.y0 + args.h, args.step):
            params = {"x": bx, "y": by, "w": args.step, "h": args.step}
            if args.view_all:
                params["view"] = "all"
            try:
                tiles = a.get("map", **params).get("tiles", [])
            except Exception:
                continue
            for t in tiles:
                total += 1
                if not t.get("visible"):
                    continue
                visible += 1
                f = t.get("floor")
                if f:
                    floors[f] += 1
                d = t.get("drop")
                if d:
                    ore[d].append((t["x"], t["y"]))

    print(f"查询 {total} 格，可见 {visible} 格")
    print()
    print("=== 矿脉 ===")
    if not ore:
        print("   （无）")
    for k, v in sorted(ore.items(), key=lambda kv: -len(kv[1])):
        xs = [p[0] for p in v]
        ys = [p[1] for p in v]
        print(f"   {k:<10} {len(v):5d} 格   x={min(xs)}..{max(xs)}  y={min(ys)}..{max(ys)}")
    print()
    print("=== 地板 ===")
    if not floors:
        print("   （无）")
    for k, v in floors.most_common(24):
        print(f"   {k:<18} {v:5d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
