#!/usr/bin/env python3
"""诊断：把带子网络按连通性分组，找出没接到核心的那一段，然后补桥。

上一轮把「58/72」当成了「干线缺格」，其实干线 39/39 全在 ——
缺的是回程。这个诊断就是为了别再靠肉眼猜哪一段断。
"""
import collections
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\drive")
sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import ArenaError
from production import World

NEI = ((1, 0), (-1, 0), (0, 1), (0, -1))


def main():
    w = World("beta", R=40)
    core_cells = {(x, y) for x in range(w.cx - 2, w.cx + 3)
                  for y in range(w.cy - 2, w.cy + 3)}
    belts = {p for p, t in w.g.items()
             if (t.get("block") or "").strip() == "conveyor"}
    if not belts:
        print("没有带子")
        return 1
    print(f"带子 {len(belts)} 格")

    # 从「贴着核心的带子」出发，沿带子图（含朝向）扩散
    seeds = [p for p in belts
             if any((p[0] + dx, p[1] + dy) in core_cells for dx, dy in NEI)]
    print(f"贴核心的带子 {len(seeds)} 格: {seeds[:6]}")
    if not seeds:
        print("没有任何带子直接贴着核心")
        return 1

    def belt_next(p):
        t = w.g.get(p)
        if not t:
            return None
        r = t.get("rotation")
        d = {0: (1, 0), 1: (0, 1), 2: (-1, 0), 3: (0, -1)}.get(r)
        return None if d is None else (p[0] + d[0], p[1] + d[1])

    # 沿朝向正向 + 反向（别人指向它）扩散
    comp = set(seeds)
    q = collections.deque(seeds)
    while q:
        cur = q.popleft()
        nxt = belt_next(cur)
        cands = [nxt] if nxt in belts else []
        for dx, dy in NEI:
            n = (cur[0] + dx, cur[1] + dy)
            if n in belts and belt_next(n) == cur:
                cands.append(n)
        for n in cands:
            if n and n not in comp:
                comp.add(n)
                q.append(n)

    orphan = belts - comp
    print(f"接到核心的 {len(comp)} 格；孤立 {len(orphan)} 格")
    if not orphan:
        print("✓ 整张网络都已接到核心")
        return 0

    ys = sorted({p[1] for p in orphan})
    xs = sorted({p[0] for p in orphan})
    print(f"孤立段范围 x[{xs[0]},{xs[-1]}] y[{ys[0]},{ys[-1]}]")

    # 找一个孤立格与一个连通格，把它们连起来。
    # **不能拿已有带子的格子当 route 的端点** —— route 要求端点是空格，
    # 拿占用格去调它永远返回 None（第一版就是这么「布不出桥」的）。
    # 正确做法：连到它们**旁边的空格**，末格朝向指向那条已有带子。
    w.planned = set()

    def free_neighbors(cells):
        out = []
        for p in cells:
            for dx, dy in NEI:
                n = (p[0] + dx, p[1] + dy)
                if w.free(n):
                    out.append((n, p))
        return out

    on_free = free_neighbors(orphan)
    oc_free = free_neighbors(comp)
    print(f"孤立段旁空位 {len(on_free)}，连通段旁空位 {len(oc_free)}")
    best = None
    for a, ao in on_free:
        for b, bc in oc_free:
            if a == b:
                continue
            p = w.route(a, b)
            if p and (best is None or len(p) < len(best[0])):
                best = (p, a, b, bc)
    if not best:
        print("布不出桥")
        return 1
    path, a, b, bc = best
    print(f"桥: {a} → {b}，{len(path)} 格（末格朝向已有的 {bc}）")

    d = (bc[0] - b[0], bc[1] - b[1])
    end_rot = {(1, 0): 0, (0, 1): 1, (-1, 0): 2, (0, -1): 3}[d]
    ok, errs = w.lay(path, "conveyor", end_rot=end_rot)
    print(f"下桥 {ok}/{len(path)}" + (f"  失败 {errs[:4]}" if errs else "  ✓"))

    print("\n== 复查连通性 ==")
    time.sleep(3)
    w.refresh()
    belts2 = {p for p, t in w.g.items()
              if (t.get("block") or "").strip() == "conveyor"}
    print(f"带子 {len(belts)} → {len(belts2)}")

    print("\n== 等铜进核心（判据是数值）==")
    t0 = time.monotonic()
    c0 = w.core["items"].get("copper", 0)
    while time.monotonic() - t0 < 150:
        try:
            c = next(b for b in w.a.buildings() if b["block"].startswith("core"))
            now = c["items"].get("copper", 0)
            if now > c0:
                print(f"  ✓ 铜 {c0} → {now}   核心={c['items']}")
                return 0
        except Exception:
            pass
        time.sleep(3)
    c = next(b for b in w.a.buildings() if b["block"].startswith("core"))
    print(f"  ✗ 铜没涨  核心={c['items']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
