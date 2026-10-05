#!/usr/bin/env python3
"""收集干线：一条线带 N 台钻机，而不是 N 条专线。

上一轮的教训：每台钻机单独拉一条回核心的线，6 台就占了 211 格，
把剩下的矿点围死，第二轮 7 个候选全部「布不出线」。

干线设计：
  · 沿矿脉找一条**直的**空格行当干线，钻机紧贴它上下排列
  · 2x2 钻机向**所有四邻**输出 —— 只要有一格挨着干线，料就自动上线，
    所以**不需要任何支线**
  · 干线末端只接**一条**回核心的 BFS 路径

所以 N 台钻机只占 1 条回程线，而不是 N 条。

选点因此变成：在候选行上，挑一组互不重叠、紧贴干线、盖住最多矿格的 2x2 位置。
"""
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\drive")
sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import ArenaError
from production import World

ROT = {(1, 0): 0, (0, 1): 1, (-1, 0): 2, (0, -1): 3}
NEI = ((1, 0), (-1, 0), (0, 1), (0, -1))


def neighbors(p):
    return [(p[0] + dx, p[1] + dy) for dx, dy in NEI]


def free_runs(w, y, x_lo, x_hi):
    """该行上所有长度 ≥6 的连续空格段。"""
    runs, cur = [], None
    for x in range(x_lo, x_hi + 1):
        if w.free((x, y)):
            cur = [x, x] if cur is None else [cur[0], x]
        else:
            if cur and cur[1] - cur[0] + 1 >= 6:
                runs.append(tuple(cur))
            cur = None
    if cur and cur[1] - cur[0] + 1 >= 6:
        runs.append(tuple(cur))
    return runs


def plan_row(w, y, x0, x1, kind="copper"):
    """在干线 [x0,x1]@y 两侧贪心放钻机，返回 (drills, covered_ore)。"""
    slots = []
    for x in range(x0, x1 + 1):
        for dy, box_y in ((-2, y - 2), (1, y + 1)):
            p = (x, box_y)
            box = w.box(p, 2)
            if not w.site_ok(p, 2):
                continue
            # 必须紧贴干线：box 有一行就是 y±1
            if not any(q[1] == y - 1 or q[1] == y + 1 for q in box):
                continue
            n = sum(1 for q in box if w.ore(q) == kind)
            if n >= 1:
                slots.append((-n, p, box, n))
    slots.sort(key=lambda z: (z[0], z[1][0]))
    picked, used, cov = [], set(), 0
    for _, p, box, n in slots:
        if any(q in used for q in box):
            continue
        used.update(box)
        picked.append((p, n))
        cov += n
    return picked, cov


def main():
    kind = sys.argv[1] if len(sys.argv) > 1 else "copper"
    w = World("beta", R=40)
    print(f"核心 ({w.cx},{w.cy})  {w.core['items']}")

    core_cells = {(x, y) for x in range(w.cx - 2, w.cx + 3)
                  for y in range(w.cy - 2, w.cy + 3)}

    def core_feeds():
        out = []
        for q in core_cells:
            for n in neighbors(q):
                if n in core_cells or not w.free(n):
                    continue
                out.append((n, ROT[(q[0] - n[0], q[1] - n[1])]))
        return out

    # ── 1. 候选干线：按覆盖降序，逐个试到「能通回核心」为止 ─────────────
    # 第一版只按覆盖选行，结果选中的 y=76 地形挡死、布不出回程，
    # 白白浪费一次构建。可通性必须和覆盖一起当判据。
    print("\n== 找最佳干线（覆盖优先，但必须能通回核心）==")
    cands = []
    for y in range(w.cy - 32, w.cy + 33):
        for (x0, x1) in free_runs(w, y, w.cx - 38, w.cx + 38):
            if (x0, y) in core_cells or (x1, y) in core_cells:
                continue
            drills, cov = plan_row(w, y, x0, x1, kind)
            if not drills:
                continue
            cands.append((-cov, y, x0, x1, drills))
    cands.sort(key=lambda z: z[0])
    print(f"  候选行 {len(cands)} 条")
    if not cands:
        print("  找不到可用干线")
        return 1

    feeds = core_feeds()
    if not feeds:
        print("  核心四邻没有空位接受带子")
        return 1

    best = None
    tried = 0
    for _, y, x0, x1, drills in cands:
        trunk = [(x, y) for x in range(x0, x1 + 1)]
        far_end = trunk[0] if abs(trunk[0][0] - w.cx) > abs(trunk[-1][0] - w.cx) else trunk[-1]
        near_end = trunk[-1] if far_end is trunk[0] else trunk[0]
        ret = None
        for n, r in feeds:
            p = w.route(near_end, n)
            if p and (ret is None or len(p) < len(ret[0])):
                ret = (p, r)
        tried += 1
        if ret:
            best = (y, x0, x1, drills, ret, trunk, far_end, near_end)
            break
        if tried >= 25:
            break
    if not best:
        print(f"  试了 {tried} 条候选行，没有一条能通回核心")
        return 1

    y, x0, x1, drills, (ret, end_rot), trunk, far_end, near_end = best
    cov = sum(n for _, n in drills)
    rate = cov * 60 / 650
    print(f"  选中干线 y={y}  x[{x0},{x1}]（{x1-x0+1} 格），试了 {tried} 条")
    print(f"  钻机 {len(drills)} 台，盖 {cov} 格 {kind} → 模型预测 {rate:.2f} /s")
    print(f"  回程 {len(ret)} 格")

    # ── 3. 占位，然后下单 ─────────────────────────────────────────────
    drill_boxes = [w.box(p, 2) for p, _ in drills]
    for b in drill_boxes:
        w.planned.update(b)
    w.planned.update(trunk)

    # trunk 本身已经包含 far_end，不能再前置一次 —— 前置会让首格与次格相同，
    # lay() 算位移时得到 (0,0) 直接 KeyError。
    full = trunk if near_end is trunk[-1] else list(reversed(trunk))
    full += ret[1:]                       # ret[0] 就是 near_end，别重复

    print("\n== 下单 ==")
    ok, errs = w.lay(full, "conveyor", end_rot=end_rot)
    print(f"  干线+回程 {ok}/{len(full)} 格" + (f"  失败 {errs[:3]}" if errs else "  ✓"))

    placed = 0
    for p, n in drills:
        try:
            w.a.post("place", x=p[0], y=p[1], block="mechanical-drill", rot=0)
            placed += 1
        except ArenaError as e:
            print(f"  钻机 ({p[0]},{p[1]}) 失败 {e.code}")
        time.sleep(0.15)
    print(f"  钻机 {placed}/{len(drills)} 台")

    # ── 4. 等建成预热，测产率 ─────────────────────────────────────────
    want = set(full) | {p for p, _ in drills}
    print("\n== 等建成 ==")
    t0 = time.monotonic()
    while time.monotonic() - t0 < 300:
        try:
            got = {(b["x"], b["y"]) for b in w.a.buildings()}
        except Exception:
            got = set()
        if want <= got:
            break
        time.sleep(1)
    print(f"  到位 {len(want & got)}/{len(want)}")

    print(f"\n== 等预热并测 {kind} 产率（模型预测 {rate:.2f} /s）==")
    top = 0.0
    t0 = time.monotonic()
    while time.monotonic() - t0 < 240:
        try:
            r = w.a.rates(window=25)
            v = ((r.get("core") or {}).get(kind) or {}).get("perSecond")
            if v is not None:
                top = max(top, v)
        except Exception:
            pass
        if top > rate * 0.85:
            break
        time.sleep(5)
    print(f"  实测最高 ≈ {top:+.3f} /s")
    try:
        d = w.a.get("drill")["drills"]
        tot = sum((x.get("itemsPerSecond") or 0) for x in d
                  if x.get("dominantItem") == kind)
        warm = sum(1 for x in d if (x.get("warmup") or 0) > 0.95)
        print(f"  钻机 {len(d)} 台（预热完成 {warm}），/drill 汇总 {kind} = {tot:.2f} /s")
    except Exception as e:
        print(f"  /drill 读取失败 {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
