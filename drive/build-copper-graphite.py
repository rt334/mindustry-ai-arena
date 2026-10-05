#!/usr/bin/env python3
"""⚠ **已弃用** —— 它把某一局的坐标写死了，换一局地图就全线失败（矿脉位置每局重随）。改用 drive/bootstrap.py + drive/production.py，它们开跑前现查地形。保留本文件只为记录当时踩的坑。

接铜线与石墨线。

铜：矿点 (288,88)，向南沿 x=289 铺到核心上方 (289,101) 朝南直入核心。
    这条列 x=289 不经过煤钻（煤钻占 x[290,291]）。

石墨：graphite-press 放核心左侧 (285,103)，右边缘贴核心 → 石墨直接入核心。
    煤从煤钻左邻 (289,100) 向西引到 (285,100)，再南下进压机顶部 (285,102)。
"""
import json
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])

COPPER_DRILL = (288, 88)
COPPER_PATH = [(289, y) for y in range(90, 102)]      # (289,90)..(289,101) 末格朝南

GRAPHITE = (285, 103)
COAL_PATH = [(289, 100), (288, 100), (287, 100), (286, 100),
             (285, 100), (285, 101), (285, 102)]


def items():
    c = next((b for b in a.buildings() if b["block"].startswith("core")), None)
    return c["items"] if c else {}


def step(label, fn):
    try:
        r = fn()
        print(f"  ✓ {label:<28} {str(r.get('message'))[:76]}")
        return True
    except ArenaError as e:
        print(f"  ✗ {label:<28} {e.code}: {e.message[:110]}")
        return False


def wait_built(coords, timeout=120):
    want = set(coords)
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        got = {(b["x"], b["y"]) for b in a.buildings()}
        if want <= got:
            return True
        time.sleep(0.5)
    return False


def main():
    print(f"起点 核心={items()}\n")

    print("== 铜线 ==")
    step(f"铜钻 {COPPER_DRILL}", lambda: a.post("place", x=COPPER_DRILL[0],
                                              y=COPPER_DRILL[1],
                                              block="mechanical-drill", rot=0))
    time.sleep(0.3)
    step(f"铜带 {len(COPPER_PATH)} 格 x=289 y=90..101",
         lambda: a.place_path(COPPER_PATH, "conveyor"))

    print("\n== 石墨线 ==")
    time.sleep(0.3)
    step(f"压机 {GRAPHITE}", lambda: a.post("place", x=GRAPHITE[0], y=GRAPHITE[1],
                                          block="graphite-press", rot=0))
    time.sleep(0.3)
    step(f"煤带 {len(COAL_PATH)} 格 → 压机", lambda: a.place_path(COAL_PATH, "conveyor"))

    # ── 确认建成 ──────────────────────────────────────────────────────
    print("\n== 等建成 ==")
    allc = [COPPER_DRILL, GRAPHITE] + COPPER_PATH + COAL_PATH
    ok = wait_built(allc, timeout=150)
    got = {(b["x"], b["y"]) for b in a.buildings()}
    miss = sorted({c for c in allc} - got)
    print(f"  到位 {len(set(allc) & got)}/{len(set(allc))}" + (f"  缺 {miss}" if miss else "  ✓"))

    if miss:
        q = a.queue()
        for b in (q.get("builders") or []):
            for p in (b.get("planList") or []):
                print(f"    卡住 ({p.get('x')},{p.get('y')}) {p.get('block')} "
                      f"stuck={p.get('stuckSeconds')} {p.get('stuckReason')}")

    # ── 测产率（判据：perSecond）──────────────────────────────────────
    print("\n== 产率（等 25 秒窗口，判据是数值不是时长）==")
    t0 = time.monotonic()
    best = {}
    while time.monotonic() - t0 < 120:
        r = a.rates(window=25)
        core = r.get("core") or {}
        for k, v in core.items():
            ps = v.get("perSecond", 0)
            if ps > best.get(k, -99):
                best[k] = ps
        if all(best.get(k, 0) > 0 for k in ("copper", "silicon")) and \
           best.get("graphite", 0) > 0:
            break
        time.sleep(4)
    print(f"  核心净变化速率 /s：")
    for k, v in sorted(best.items()):
        print(f"      {k:<10} {v:+.3f}")
    print(f"\n  核心={items()}")
    print(f"  存储={json.dumps((a.rates(window=25) or {}).get('stored'), ensure_ascii=False)}")

    # ── 诊断 ──────────────────────────────────────────────────────────
    print("\n== 建筑 ===")
    for b in a.buildings():
        det = []
        if b.get("efficiency") is not None:
            det.append(f"eff={b['efficiency']}")
        if b.get("powerStatus") is not None:
            det.append(f"pw={b['powerStatus']}")
        if b.get("items"):
            det.append(f"items={b['items']}")
        print(f"  {b['block']:<20} ({b['x']},{b['y']}) {' '.join(det)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
