#!/usr/bin/env python3
"""规模化铺铜：多台钻机 + 各自回核心的收集带。

产率公式（引擎 Drill.java:303，已在 docs/PRODUCTION.md 里记录）：
    每秒 = 60 × 矿格数 ÷ (drillTime + 50×硬度) × warmup
机械钻挖铜（硬度 1、drillTime 600）→ 每格 60/650 = 0.0923 /s。
所以 +5/s 需要盖住约 54 格铜，即 ~14 台「4 格矿」的钻机。

本脚本不追求最优覆盖，只求**能跑起来并测准**：按 (矿格数降序, 距离升序) 贪心
选点，每台钻机单独布一条回核心的带子。route() 会绕开已计划格，所以后布的
带子会自己找别的路。

用法：python scale-copper.py [台数]
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


def main():
    n_target = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    w = World("beta", R=40)
    print(f"核心 ({w.cx},{w.cy})  {w.core['items']}")

    core_cells = {(x, y) for x in range(w.cx - 2, w.cx + 3)
                  for y in range(w.cy - 2, w.cy + 3)}

    def core_feeds():
        """核心四邻的空格 + 该格朝核心的朝向。"""
        out = []
        for q in core_cells:
            for n in neighbors(q):
                if n in core_cells:
                    continue
                if w.free(n):
                    out.append((n, ROT[(q[0] - n[0], q[1] - n[1])]))
        return out

    # ── 选点 ──────────────────────────────────────────────────────────
    cands = []
    for p in w.g:
        d = abs(p[0] - w.cx) + abs(p[1] - w.cy)
        if d > 38 or not w.site_ok(p, 2):
            continue
        box = w.box(p, 2)
        n = sum(1 for q in box if w.ore(q) == "copper")
        if n >= 2:
            cands.append((-n, d, p))
    cands.sort()
    picked = []
    for _, _, p in cands:
        if all(abs(p[0] - q[0]) >= 2 or abs(p[1] - q[1]) >= 2 for q in picked):
            picked.append(p)
        if len(picked) >= n_target:
            break
    print(f"候选 {len(cands)} 个，选中 {len(picked)} 个钻位")

    # ── 逐台建：钻机 + 带子 ───────────────────────────────────────────
    built, failed = [], []
    for i, p in enumerate(picked):
        box = w.box(p, 2)
        n_ore = sum(1 for q in box if w.ore(q) == "copper")
        w.planned.update(box)
        try:
            w.a.post("place", x=p[0], y=p[1], block="mechanical-drill", rot=0)
        except ArenaError as e:
            failed.append(f"钻机{i} ({p[0]},{p[1]}) {e.code}")
            continue
        time.sleep(0.7)
        w.refresh()
        w.planned.update(box)

        # 起点：钻机四邻的空格；终点：贴核心的空格
        starts = [n for q in box for n in neighbors(q)
                  if n not in box and w.free(n)]
        ends = core_feeds()
        best = None
        for s in starts:
            for n, r in ends:
                if n == s:
                    continue
                path = w.route(s, n)
                if path and (best is None or len(path) < len(best[0])):
                    best = (path, r)
        if not best:
            failed.append(f"钻机{i} ({p[0]},{p[1]}) 布不出线")
            continue
        path, r = best
        ok, errs = w.lay(path, "conveyor", end_rot=r)
        if ok != len(path):
            failed.append(f"钻机{i} 带子 {ok}/{len(path)}")
        built.append((p, n_ore, len(path)))
        print(f"  钻机{i:>2} ({p[0]:>3},{p[1]:>3}) 矿{n_ore}格  带{len(path):>2}格"
              f"  {'' if ok == len(path) else '⚠ ' + str(errs[:2])}")

    print(f"\n建成 {len(built)} 台" + (f"，失败 {len(failed)}" if failed else ""))
    for f in failed:
        print(f"  ✗ {f}")

    # ── 等建成并测产率 ────────────────────────────────────────────────
    allc = [p for p, _, _ in built]
    print("\n== 等钻机到位 ==")
    t0 = time.monotonic()
    while time.monotonic() - t0 < 240:
        try:
            got = {(b["x"], b["y"]) for b in w.a.buildings()}
        except Exception:
            got = set()
        if set(allc) <= got:
            break
        time.sleep(1)
    try:
        got = {(b["x"], b["y"]) for b in w.a.buildings()}
    except Exception:
        got = set()
    print(f"  到位 {len(set(allc) & got)}/{len(allc)}")

    print("\n== 等预热并测产率（判据是数值，不睡死）==")
    pred = sum(n for _, n, _ in built) * 60 / 650
    print(f"  模型预测（全部预热后）≈ {pred:.2f} /s")
    best = 0.0
    t0 = time.monotonic()
    while time.monotonic() - t0 < 180:
        try:
            r = w.a.rates(window=25)
            v = ((r.get("core") or {}).get("copper") or {}).get("perSecond")
            if v is not None:
                best = max(best, v)
        except Exception:
            pass
        if best > pred * 0.8:
            break
        time.sleep(5)
    print(f"  实测最高 ≈ {best:+.3f} /s")
    try:
        d = w.a.get("drill")["drills"]
        warm = [x for x in d if (x.get("warmup") or 0) > 0.95]
        tot = sum((x.get("itemsPerSecond") or 0) for x in d
                  if x.get("dominantItem") == "copper")
        print(f"  钻机 {len(d)} 台，预热完成 {len(warm)} 台")
        print(f"  /drill 汇总的铜产出 = {tot:.2f} /s")
    except Exception as e:
        print(f"  /drill 读取失败 {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
