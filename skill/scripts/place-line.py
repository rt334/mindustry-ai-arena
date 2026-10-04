#!/usr/bin/env python3
"""按坐标表批量下单并逐格轮询确认。

JSON 输入格式（数组，每项一个方块）：
    [
      {"x": 66, "y": 104, "block": "conveyor", "rot": 2},
      {"x": 66, "y": 105, "block": "conveyor", "rot": 3},
      {"x": 61, "y": 108, "block": "mechanical-drill"}
    ]

也可用 `--line x=66,y0=113,y1=104,rot=3` 直接生成一条直线。

**禁止等待**：所有确认都走 `poll_until`，命中即退。
`--no-confirm` 只下单不确认（快速铺长线时用，之后统一查一遍）。

用法：
    python place-line.py --token T --json line.json --apply
    python place-line.py --token T --line 66,113,104,3 --block conveyor --apply
"""
import argparse
import json
import sys

from arena import Arena


def parse_line(spec, block):
    """x,y0,y1,rot -> 说明表。"""
    parts = [p.strip() for p in spec.split(",")]
    if len(parts) != 4:
        raise SystemExit("--line 需要 x,y0,y1,rot")
    x, y0, y1, rot = (int(p) for p in parts)
    step = 1 if y1 >= y0 else -1
    return [{"x": x, "y": y, "block": block, "rot": rot}
            for y in range(y0, y1 + step, step)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="alpha")
    ap.add_argument("--token", required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7199)
    ap.add_argument("--json", help="坐标表 JSON 文件")
    ap.add_argument("--line", help="x,y0,y1,rot 直线")
    ap.add_argument("--block", default="conveyor", help="--line 用的方块")
    ap.add_argument("--no-confirm", action="store_true")
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if args.json:
        with open(args.json, encoding="utf-8") as f:
            items = json.load(f)
    elif args.line:
        items = parse_line(args.line, args.block)
    else:
        raise SystemExit("需要 --json 或 --line")

    print(f"待下单 {len(items)} 个")
    if not args.apply:
        for it in items[:60]:
            print(f"   ({it['x']},{it['y']}) {it['block']} rot={it.get('rot')}")
        return 0

    a = Arena(args.agent, args.token, args.host, args.port)
    if not a.ping():
        print("服务端离线", file=sys.stderr)
        return 1

    ok = fail = 0
    for it in items:
        try:
            a.place(it["x"], it["y"], it["block"], it.get("rot"))
            ok += 1
        except Exception as e:
            fail += 1
            print(f"   FAIL ({it['x']},{it['y']}) {e}")

    print(f"下单 ok={ok} fail={fail}")

    if args.no_confirm:
        return 0

    # 逐格轮询确认（提前退出，不睡固定时长）
    done = 0
    for it in items:
        b = a.poll_until(lambda: a.building_at(it["x"], it["y"]),
                         timeout=args.timeout)
        if b:
            done += 1
        else:
            print(f"   未建成 ({it['x']},{it['y']}) {it['block']}")
    print(f"确认建成 {done}/{len(items)}")
    return 0 if done == len(items) else 1


if __name__ == "__main__":
    sys.exit(main())
