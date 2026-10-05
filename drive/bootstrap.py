#!/usr/bin/env python3
"""自动 bootstrap 硅线 —— 坐标全部现算，不写死。

顺序不可换：煤钻 → 燃煤发电机 → 硅冶炼厂。
（solar-panel 要 8 硅而硅要电，先放它就是个死循环。）

每步都靠 production.World 现查地形，所以换一地图也能跑。
"""
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\drive")
sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import ArenaError
from production import World

ROT = {(1, 0): 0, (0, 1): 1, (-1, 0): 2, (0, -1): 3}


def neighbors(p):
    return [(p[0] + dx, p[1] + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))]


def main():
    w = World("beta", R=26)
    print(f"核心 ({w.cx},{w.cy})  {w.core['items']}")

    # ── 1. 冶炼厂：贴核心，硅才好直接入库 ─────────────────────────────
    sm = w.find_site_near_core(2)
    if not sm:
        print("找不到贴核心的 2x2 空位放冶炼厂")
        return 1
    w.planned.update(w.box(sm, 2))
    try:
        w.a.post("place", x=sm[0], y=sm[1], block="silicon-smelter", rot=0)
        print(f"  冶炼厂 {sm}")
    except ArenaError as e:
        print(f"  冶炼厂失败 {e.code} {e.message[:90]}")
        return 1
    time.sleep(0.8)
    w.refresh()
    w.planned.update(w.box(sm, 2))

    sm_cells = set(w.box(sm, 2))

    def feed(target_cells, drill_site, label, end_rot):
        """从钻机旁布一条带，末格 end_rot 朝目标。"""
        # 起点：钻机脚印四邻里的空格
        starts = []
        for q in w.box(drill_site, 2):
            for n in neighbors(q):
                if n not in w.box(drill_site, 2) and w.free(n):
                    starts.append(n)
        # 终点：目标脚印四邻里的空格（且该格朝目标的那一面要真的贴着目标）
        ends = []
        for q in target_cells:
            for n in neighbors(q):
                if n in target_cells:
                    continue
                if not w.free(n):
                    continue
                # n 必须与 q 相邻，且朝向 q —— 由 end_rot 保证
                ends.append((n, ROT[(q[0] - n[0], q[1] - n[1])]))
        seen = set()
        for n, r in ends:
            seen.add(n)
        best = None
        for s in starts:
            for n, r in ends:
                if n == s:
                    continue
                p = w.route(s, n)
                if p and (best is None or len(p) < len(best[0])):
                    best = (p, r)
        if not best:
            print(f"  ✗ {label}: 布不出路径")
            return False
        path, r = best
        ok, errs = w.lay(path, "conveyor", end_rot=r)
        print(f"  {label}: {ok}/{len(path)} 格" + (f"  失败 {errs[:3]}" if errs else "  ✓"))
        return ok == len(path)

    # ── 2. 煤钻 A → 冶炼厂 ─────────────────────────────────────────────
    coal_a, na = w.find_site("coal", 2)
    if not coal_a:
        print("找不到煤")
        return 1
    print(f"  煤钻A {coal_a}（矿{na}格）")
    w.planned.update(w.box(coal_a, 2))
    try:
        w.a.post("place", x=coal_a[0], y=coal_a[1], block="mechanical-drill", rot=0)
    except ArenaError as e:
        print(f"  煤钻A失败 {e.code} {e.message[:90]}")
        return 1
    time.sleep(0.8)
    w.refresh()
    w.planned.update(w.box(coal_a, 2))
    feed(sm_cells, coal_a, "煤带A →冶炼厂", None)

    # ── 3. 沙钻 → 冶炼厂 ───────────────────────────────────────────────
    sand, ns = w.find_site("sand", 2)
    if not sand:
        print("找不到沙")
        return 1
    print(f"  沙钻 {sand}（矿{ns}格）")
    w.planned.update(w.box(sand, 2))
    try:
        w.a.post("place", x=sand[0], y=sand[1], block="mechanical-drill", rot=0)
    except ArenaError as e:
        print(f"  沙钻失败 {e.code} {e.message[:90]}")
        return 1
    time.sleep(0.8)
    w.refresh()
    w.planned.update(w.box(sand, 2))
    feed(sm_cells, sand, "沙带 →冶炼厂", None)

    # ── 4. 发电机：贴冶炼厂，自动连电力线 ──────────────────────────────
    gen = None
    for q in sm_cells:
        for n in neighbors(q):
            if n not in sm_cells and w.free(n):
                gen = n
                break
        if gen:
            break
    if not gen:
        print("找不到贴冶炼厂的发电机位")
        return 1
    w.planned.add(gen)
    try:
        w.a.post("place", x=gen[0], y=gen[1], block="combustion-generator", rot=0)
        print(f"  发电机 {gen}（贴冶炼厂）")
    except ArenaError as e:
        print(f"  发电机失败 {e.code} {e.message[:90]}")
        return 1
    time.sleep(0.8)
    w.refresh()
    w.planned.add(gen)

    # ── 5. 第二台煤钻 → 发电机 ─────────────────────────────────────────
    # 排除已用的煤点附近，找另一处
    coal_b, nb = None, 0
    saved = set(w.planned)
    for p in sorted(w.g, key=lambda z: abs(z[0] - w.cx) + abs(z[1] - w.cy)):
        if abs(p[0] - coal_a[0]) + abs(p[1] - coal_a[1]) < 4:
            continue
        if not w.site_ok(p, 2):
            continue
        n = sum(1 for q in w.box(p, 2) if w.ore(q) == "coal")
        if n >= 1:
            coal_b, nb = p, n
            break
    if coal_b:
        print(f"  煤钻B {coal_b}（矿{nb}格）")
        w.planned.update(w.box(coal_b, 2))
        try:
            w.a.post("place", x=coal_b[0], y=coal_b[1], block="mechanical-drill", rot=0)
        except ArenaError as e:
            print(f"  煤钻B失败 {e.code} {e.message[:80]}")
        time.sleep(0.8)
        w.refresh()
        w.planned.update(w.box(coal_b, 2))
        feed({gen}, coal_b, "煤带B →发电机", None)
    else:
        print("  没有第二处煤（发电机可能烧不上）")

    # ── 6. 等硅 ────────────────────────────────────────────────────────
    print("\n== 等冶炼厂供电 ==")
    t0 = time.monotonic()
    smb = None
    while time.monotonic() - t0 < 150:
        smb = next((b for b in w.a.buildings()
                    if (b["x"], b["y"]) == sm), None)
        if smb and (smb.get("powerStatus") or 0) > 0.8:
            break
        time.sleep(1)
    if smb:
        print(f"  power={smb.get('powerStatus')} eff={smb.get('efficiency')} items={smb.get('items')}")

    print("\n== 等硅进核心 ==")
    si0 = 0
    t0 = time.monotonic()
    while time.monotonic() - t0 < 240:
        c = next(b for b in w.a.buildings() if b["block"].startswith("core"))
        si = c["items"].get("silicon", 0)
        if si > si0:
            print(f"  ✓ 硅 {si}   核心={c['items']}")
            return 0
        time.sleep(2)
    c = next(b for b in w.a.buildings() if b["block"].startswith("core"))
    print(f"  ✗ 硅没增加  核心={c['items']}")
    q = w.a.queue()
    for b in (q.get("builders") or []):
        for p in (b.get("planList") or []):
            print(f"    卡住 ({p.get('x')},{p.get('y')}) {p.get('block')}: {p.get('stuckReason')}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
