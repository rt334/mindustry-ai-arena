#!/usr/bin/env python3
"""⚠ **已弃用** —— 它把某一局的坐标写死了，换一局地图就全线失败（矿脉位置每局重随）。改用 drive/bootstrap.py + drive/production.py，它们开跑前现查地形。保留本文件只为记录当时踩的坑。

给发电机换一个独立的煤源，把老钻机让给冶炼厂。

上一版诊断（都是实测出来的，不是猜的）：
  · 一台煤钻 ~0.45/s，却有四个消费者：核心 / 冶炼厂 / 发电机 / 压机，合计 ~1.0/s
    → 冶炼厂 eff=0.0（没煤）、压机 eff=0.0
  · 煤脉块1（在用的那处 x[290,292] y[98,102]，11 格）**放不下第二台 2x2**
  · 煤脉块0 x[300,303] y[99,103]（16 格，距核心 12）能放两台

本步：块0 放一台钻机 (301,99)，向西沿 y=101 铺到 (294,101)——那格正好朝南
喂发电机 (294,102)。同时拆掉老钻机通往发电机的那两格，把它还给冶炼厂。

y=101 从 x=301 到 x=294 不经过 x=292（冶炼厂进口）也不经过 x=289（铜带列），无冲突。
"""
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])

NEW_DRILL = (301, 99)
GEN_PATH = [(x, 101) for x in range(300, 293, -1)]     # (300,101)..(294,101)
DROP = [(292, 100), (293, 100), (294, 100)]            # 老钻机→发电机的旧链路


def step(label, fn):
    try:
        r = fn()
        print(f"  ✓ {label:<30} {str(r.get('message'))[:74]}")
        return True
    except ArenaError as e:
        print(f"  ✗ {label:<30} {e.code}: {e.message[:110]}")
        return False


def main():
    core = next(b for b in a.buildings() if b["block"].startswith("core"))
    print(f"核心 {core['items']}\n")

    print("== 1. 拆掉老钻机通往发电机的旧链路（把煤还给冶炼厂）==")
    for (x, y) in DROP:
        step(f"拆 ({x},{y})", lambda x=x, y=y: a.post("break", x=x, y=y))
        time.sleep(0.25)

    print("\n== 2. 块0 新煤钻 + 向西的煤带 ==")
    step(f"煤钻B {NEW_DRILL}", lambda: a.post("place", x=NEW_DRILL[0], y=NEW_DRILL[1],
                                             block="mechanical-drill", rot=0))
    time.sleep(0.4)
    step(f"煤带 {len(GEN_PATH)} 格 →(294,101)", lambda: a.place_path(GEN_PATH, "conveyor"))

    # ── 等建成 ────────────────────────────────────────────────────────
    print("\n== 等建成 ==")
    want = {NEW_DRILL} | set(GEN_PATH)
    t0 = time.monotonic()
    while time.monotonic() - t0 < 150:
        got = {(b["x"], b["y"]) for b in a.buildings()}
        if want <= got:
            break
        time.sleep(0.5)
    miss = sorted(want - got)
    print(f"  到位 {len(want & got)}/{len(want)}" + (f"  缺 {miss}" if miss else "  ✓"))

    # ── 看冶炼厂有没有吃饱煤 ──────────────────────────────────────────
    print("\n== 冶炼厂（判据：eff 与 items 里有没有 coal）==")
    t0 = time.monotonic()
    last = None
    while time.monotonic() - t0 < 90:
        sm = next((b for b in a.buildings()
                   if b["x"] == 292 and b["y"] == 102), None)
        if sm:
            last = sm
            it = sm.get("items") or {}
            if sm.get("efficiency", 0) > 0.8 and it.get("coal", 0) > 0:
                break
        time.sleep(0.5)
    if last:
        print(f"  eff={last.get('efficiency')} power={last.get('powerStatus')} "
              f"items={last.get('items')}")

    # ── 产率 ──────────────────────────────────────────────────────────
    print("\n== 产率（25 秒窗口）==")
    best = {}
    t0 = time.monotonic()
    while time.monotonic() - t0 < 100:
        r = a.rates(window=25)
        for k, v in (r.get("core") or {}).items():
            best[k] = max(best.get(k, -99), v.get("perSecond", 0))
        if best.get("silicon", 0) > 0.25 and not miss:
            break
        time.sleep(4)
    for k, v in sorted(best.items()):
        print(f"      {k:<10} {v:+.3f} /s")
    print(f"\n  核心={next(b for b in a.buildings() if b['block'].startswith('core'))['items']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
