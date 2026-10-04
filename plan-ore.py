#!/usr/bin/env python3
"""矿脉规划器。

回答：**在哪些格子放矿机，能拿到最多的目标资源？**

为什么需要它：`/ore` 每次只算一个格子的 footprint，而选址要看周围几十格。
逐格调接口在 350x200 的图上要上万次请求；`/map` 一次给出全图地形，
footprint 分析在本地做。

产出正比于 footprint 内的矿格数（Drill.java:303）：

    lastDrillSpeed = speed * dominantItems / getDrillTime(item)

所以 3x3 的 laser-drill 在满矿上能到 mechanical-drill 的 5 倍 —— 选址和选型
比堆数量重要得多。

**互不重叠**：相邻 anchor 的 footprint 大量重叠（一块 4 格矿最多有 9 个合法
anchor，但只能放 1 台）。所以按产出降序贪心挑，跳过与已选重叠的。

用法：
    python plan-ore.py --token TOKEN --layout laser-drill
    python plan-ore.py --token TOKEN --all
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request

# ---- 与 Blocks.java 对齐（实测，别改错）----
DRILLS = {
    #                drillTime  size  tier  造价
    "mechanical-drill": (600, 2, 2),
    "pneumatic-drill":  (400, 2, 3),
    "laser-drill":      (280, 3, 4),
    "blast-drill":      (280, 4, 5),
}
HARDNESS_MULT = 50
HARDNESS = {"sand": 0, "copper": 1, "lead": 1, "coal": 2,
            "titanium": 3, "thorium": 4, "tungsten": 5}


def fetch_map(host, port, agent, token, x0, y0, w, h, step=40):
    tiles = {}
    for bx in range(x0, x0 + w, step):
        for by in range(y0, y0 + h, step):
            url = (f"http://{host}:{port}/v1/{agent}/map?"
                   + urllib.parse.urlencode({"x": bx, "y": by,
                                             "w": step, "h": step}))
            req = urllib.request.Request(url, method="GET")
            req.add_header("Authorization", f"Bearer {token}")
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                print(f"  区块 ({bx},{by}) 失败: {e}", file=sys.stderr)
                continue
            if not body.get("ok"):
                continue
            for t in body["data"]["tiles"]:
                tiles[(t["x"], t["y"])] = t
    return tiles


def candidates(tiles, drill, core, want=None):
    """列出所有合法 anchor 及其产出。"""
    drill_time, size, tier = DRILLS[drill]
    out = []
    for (x, y), t in tiles.items():
        if t.get("block") != "air":
            continue
        counts = {}
        ok = True
        for dx in range(size):
            for dy in range(size):
                n = tiles.get((x + dx, y + dy))
                if n is None or n.get("block") != "air":
                    ok = False
                    break
                d = n.get("drop")
                if d:
                    h = n.get("dropHardness")
                    if h is not None and h <= tier:
                        counts[d] = counts.get(d, 0) + 1
            if not ok:
                break
        if not ok or not counts:
            continue
        item = max(counts.items(), key=lambda kv: kv[1])[0]
        if want and item != want:
            continue
        n = counts[item]
        delay = drill_time + HARDNESS_MULT * HARDNESS.get(item, 0)
        rate = n / delay * 60.0
        dist = ((x - core[0]) ** 2 + (y - core[1]) ** 2) ** 0.5
        out.append((x, y, item, n, rate, dist, counts))
    return out


def greedy_nonoverlap(cands, drill):
    """按产出降序贪心，跳过与已选重叠的。"""
    _, size, _ = DRILLS[drill]
    used = set()
    picked = []
    for c in sorted(cands, key=lambda c: (-c[4], c[5])):
        x, y = c[0], c[1]
        cells = {(x + dx, y + dy) for dx in range(size) for dy in range(size)}
        if cells & used:
            continue
        used |= cells
        picked.append(c)
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7199)
    ap.add_argument("--agent", default="alpha")
    ap.add_argument("--token", required=True)
    ap.add_argument("--drill", default="mechanical-drill")
    ap.add_argument("--item", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--layout", action="store_true",
                    help="输出互不重叠的具体选址清单")
    ap.add_argument("--target", type=float, default=5.0,
                    help="每项资源目标速率 /s")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--json-out", default=None,
                    help="把「够目标所需」的选址写成 JSON，供 build-line.py 消费")
    ap.add_argument("--only", default=None,
                    help="只导出这些资源，逗号分隔（默认全部）")
    ap.add_argument("--x0", type=int, default=0)
    ap.add_argument("--y0", type=int, default=0)
    ap.add_argument("--w", type=int, default=350)
    ap.add_argument("--h", type=int, default=200)
    ap.add_argument("--core-x", type=int, default=61)
    ap.add_argument("--core-y", type=int, default=104)
    args = ap.parse_args()

    core = (args.core_x, args.core_y)
    tiles = fetch_map(args.host, args.port, args.agent, args.token,
                      args.x0, args.y0, args.w, args.h)
    print(f"地形 {len(tiles)} 格   矿机={args.drill}  {DRILLS[args.drill]}")

    all_c = candidates(tiles, args.drill, core)
    by_item = {}
    for c in all_c:
        by_item.setdefault(c[2], []).append(c)

    print(f"\n{'资源':<10}{'候选':>6}{'可选(不重叠)':>14}{'单台上限':>10}{'总产出':>10}{'需台数':>8}")
    for item in sorted(by_item):
        picked = greedy_nonoverlap(by_item[item], args.drill)
        _, size, tier = DRILLS[args.drill]
        best = max(c[4] for c in by_item[item])
        total = sum(c[4] for c in picked)
        need = (args.target / best) if best > 0 else 0
        print(f"{item:<10}{len(by_item[item]):>6}{len(picked):>14}"
              f"{best:>10.2f}{total:>10.2f}{need:>8.1f}")

    if args.layout:
        print("\n=== 具体选址（互不重叠）===")
        for item in sorted(by_item):
            if args.item and not args.all and item != args.item:
                continue
            picked = sorted(greedy_nonoverlap(by_item[item], args.drill),
                            key=lambda c: c[5])
            need = args.target / max(c[4] for c in by_item[item])
            take = int(need) + (1 if need % 1 else 0)
            print(f"\n--- {item}  目标 {args.target}/s  需 {take} 台 ---")
            acc = 0.0
            for i, c in enumerate(picked[:max(take, args.top)]):
                acc += c[4]
                mark = "★" if i < take else " "
                print(f"  {mark} ({c[0]:3},{c[1]:3}) {c[3]}格 {c[4]:.2f}/s "
                      f"距{c[5]:5.1f} 累计{acc:5.2f}")

    if args.json_out:
        _, size, _ = DRILLS[args.drill]
        only = set(args.only.split(",")) if args.only else None
        out = []
        summary = []
        for item in sorted(by_item):
            if only and item not in only:
                continue
            picked = sorted(greedy_nonoverlap(by_item[item], args.drill),
                            key=lambda c: c[5])
            best = max(c[4] for c in by_item[item])
            need = args.target / best
            take = int(need) + (1 if need % 1 else 0)
            got = 0.0
            for i, c in enumerate(picked):
                if i >= take:
                    break
                out.append({"x": c[0], "y": c[1], "block": args.drill,
                            "size": size, "item": item, "rate": round(c[4], 3)})
                got += c[4]
            summary.append((item, take, got, best, len(picked)))
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"\n=== 导出 {args.json_out}  共 {len(out)} 台 ===")
        for item, take, got, best, avail in summary:
            # 用 ASCII 标记：Windows 控制台是 GBK，✓/✗ 会 UnicodeEncodeError
            ok = "OK" if got >= args.target else "--"
            print(f"   [{ok}] {item:<9} 需 {take:>3} 台  实际可达 {got:5.2f}/s "
                  f"（单台 {best:.2f}，可选 {avail}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
