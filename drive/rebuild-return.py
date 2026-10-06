#!/usr/bin/env python3
"""重建回程：拆掉断掉的那一段，按**朝向链**重新铺，逐格校验。

上一轮的结论：干线 39/39 完好且满载，断的是回程；而「空间相邻」不等于
「流向相接」—— 带子必须首尾指向一致才能传动。所以这次的判据是朝向链。

做法：
  1. 认干线 = y=124 那一行（它完好）
  2. 拆掉其余所有带子（回程整段作废重建）
  3. 从干线靠核心的那一端，BFS 一条到核心旁的路
  4. 按顺序铺，逐格朝向指向下一格；失败的格子拆掉重铺一次
  5. **按朝向链复核**：从核心口往里走，看能不能走到干线
  6. 测铜有没有进核心
"""
import collections
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\drive")
sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import ArenaError
from production import World

NEI = ((1, 0), (-1, 0), (0, 1), (0, -1))
D2R = {(1, 0): 0, (0, 1): 1, (-1, 0): 2, (0, -1): 3}


def main():
    w = World("beta", R=40)
    ROW = 124
    core_cells = {(x, y) for x in range(w.cx - 2, w.cx + 3)
                  for y in range(w.cy - 2, w.cy + 3)}

    belts = {p for p, t in w.g.items()
             if (t.get("block") or "").strip() == "conveyor"}
    trunk = {p for p in belts if p[1] == ROW}
    print(f"带子 {len(belts)} 格，其中干线(y={ROW}) {len(trunk)} 格，其余 {len(belts)-len(trunk)} 格")

    # ── 1. 拆掉非干线的带子（回程整段作废）────────────────────────────
    others = sorted(belts - trunk)
    print(f"\n== 拆 {len(others)} 格回程 ==")
    nd = 0
    for p in others:
        try:
            w.a.post("break", x=p[0], y=p[1])
            nd += 1
        except ArenaError as e:
            print(f"  ({p[0]},{p[1]}) {e.code}")
        time.sleep(0.06)
    print(f"  已拆 {nd}")
    time.sleep(3)

    # ── 2. 重新拉一张干净地图 ────────────────────────────────────────
    w.refresh()
    belts = {p for p, t in w.g.items()
             if (t.get("block") or "").strip() == "conveyor"}
    trunk = {p for p in belts if p[1] == ROW}
    print(f"  复查：带子剩 {len(belts)} 格（干线 {len(trunk)}）")

    # ── 3. 找干线靠核心的那一端 ──────────────────────────────────────
    xs = sorted(p[0] for p in trunk)
    print(f"  干线 x[{xs[0]},{xs[-1]}] at y={ROW}")

    feeds = []
    for q in core_cells:
        for dx, dy in NEI:
            n = (q[0] + dx, q[1] + dy)
            if n in core_cells or not w.free(n):
                continue
            feeds.append((n, D2R[(q[0] - n[0], q[1] - n[1])]))
    print(f"  核心旁可接的空位 {len(feeds)} 个")

    # ── 4. BFS 一条从干线到核心旁的路 ─────────────────────────────────
    # **陷阱（我犯了两次）**：route() 要求端点是空格，而干线上的格子是带子，
    # 直接拿它当起点会永远返回 None —— 看起来像「布不出路」，其实是端点非法。
    # 必须从干线格的**空邻居**出发，末格朝向再指回干线。
    best = None
    tried = 0
    for end in sorted(trunk, key=lambda p: abs(p[0] - w.cx) + abs(p[1] - w.cy)):
        for dx, dy in NEI:
            s = (end[0] + dx, end[1] + dy)
            if not w.free(s):
                continue
            tried += 1
            for n, r in feeds:
                if n == s:
                    continue
                p = w.route(s, n)
                if p and (best is None or len(p) < len(best[0])):
                    best = (p, r, s, end)
        if best and tried >= 20:
            break
    if not best:
        print(f"试了 {tried} 个起点，布不出回程")
        return 1
    path, end_rot, start, trunk_at = best
    print(f"  回程 {start}（干线 {trunk_at} 旁）→ {path[-1]}，{len(path)} 格（试了 {tried} 个起点）")

    # ── 5. 铺，失败的格子重铺一次 ────────────────────────────────────
    # path[0] 是干线端点（已有带子），从 path[1] 开始铺
    body = path[1:]
    ok, errs = w.lay(body, "conveyor", end_rot=end_rot)
    if errs:
        print(f"  首次 {ok}/{len(body)}，失败的：{errs[:4]}")
        bad = set()
        for f in errs:
            xy = f.split()[0].strip("()").split(",")
            bad.add((int(xy[0]), int(xy[1])))
        time.sleep(4)
        w.refresh()
        for p in body:
            if p in bad and w.free(p):
                try:
                    i = body.index(p)
                    nxt = body[i + 1] if i + 1 < len(body) else None
                    rot = end_rot if nxt is None else D2R[(nxt[0] - p[0], nxt[1] - p[1])]
                    w.a.post("place", x=p[0], y=p[1], block="conveyor", rot=rot)
                    print(f"    补 ({p[0]},{p[1]}) ✓")
                except ArenaError as e:
                    print(f"    补 ({p[0]},{p[1]}) 仍失败 {e.code}")
                time.sleep(0.2)
    else:
        print(f"  ✓ {ok}/{len(body)} 全部下单成功")

    time.sleep(5)

    # ── 6. 按**朝向链**复核 ──────────────────────────────────────────
    print("\n== 朝向链复核（这才是判据，不是空间相邻）==")
    w.refresh()
    belts = {p: w.g[p].get("rotation") for p, t in w.g.items()
             if (t.get("block") or "").strip() == "conveyor"}

    def steps(p, n=40):
        """沿朝向走 n 步，返回走过的格。"""
        seen, cur = [], p
        for _ in range(n):
            r = belts.get(cur)
            if r is None:
                break
            seen.append(cur)
            d = [(1, 0), (0, 1), (-1, 0), (0, -1)][r]
            cur = (cur[0] + d[0], cur[1] + d[1])
        return seen

    # 从干线里挑离核心最近的一格，沿朝向走到不动为止
    near = min(trunk, key=lambda p: abs(p[0] - w.cx) + abs(p[1] - w.cy))
    walked = steps(near, 60)
    print(f"  从干线最近的格 {near} 沿朝向走了 {len(walked)} 步")
    print(f"  终点 {walked[-1] if walked else near}，下一步指向 "
          f"{next(iter([ (walked[-1][0]+[(1,0),(0,1),(-1,0),(0,-1)][belts[walked[-1]]][0], walked[-1][1]+[(1,0),(0,1),(-1,0),(0,-1)][belts[walked[-1]]][1]) ])) if walked and walked[-1] in belts else None}")
    reached = any((q[0] + dx, q[1] + dy) in core_cells
                  for q in walked[-3:] for dx, dy in NEI) if walked else False
    print(f"  路径是否触达核心：{'✓' if reached else '✗'}")

    # ── 7. 测铜 ──────────────────────────────────────────────────────
    print("\n== 等铜进核心 ==")
    c0 = next(b for b in w.a.buildings() if b["block"].startswith("core"))["items"].get("copper", 0)
    t0 = time.monotonic()
    while time.monotonic() - t0 < 180:
        c = next(b for b in w.a.buildings() if b["block"].startswith("core"))
        now = c["items"].get("copper", 0)
        if now > c0:
            print(f"  ✓ 铜 {c0} → {now}   核心={c['items']}")
            return 0
        time.sleep(3)
    c = next(b for b in w.a.buildings() if b["block"].startswith("core"))
    print(f"  ✗ 铜没涨（{c0} → {c['items'].get('copper')}）  核心={c['items']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
