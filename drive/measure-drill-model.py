#!/usr/bin/env python3
"""测「脚下矿格数是否影响产率」—— 这决定「+5/s」在其他矿上可不可达。

已有一台铜钻在 矿格=4 上，产出约 0.35/s。再放一台在 矿格=2 上 (274,106)，
用**前后产率差**反推它单独的产率：

    矿格不是因素 → 差值应接近 0.35/s
    产率正比于矿格 → 差值应接近 0.17/s

为什么用差值而不是 /drill 的 lastDrillSpeed：那个字段只有两位小数
（0.01 / 0.00），1 格矿和 4 格矿会被舍入成同一档，分不出来。

选点 (274,106)：2x2 覆盖 x[274,275] y[106,107]，其中两格是铜矿。
向东沿 y=106 一路铺到 (286,106)——那格东邻就是核心 (287,106)，铜直接进核心。
实测 y=106 的 x275..286 全是空地。
"""
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])

DRILL = (274, 106)
PATH = [(x, 106) for x in range(276, 287)]        # (276,106)..(286,106)


def core():
    return next(b for b in a.buildings() if b["block"].startswith("core"))


def measure(seconds=30, tries=5):
    """取铜的 perSecond 中位数，避开瞬时抖动。"""
    vals = []
    for _ in range(tries):
        try:
            r = a.rates(window=seconds)
            v = (r.get("core") or {}).get("copper", {}).get("perSecond")
            if v is not None:
                vals.append(v)
        except ArenaError:
            pass
        time.sleep(3)
    if not vals:
        return None
    vals.sort()
    return vals[len(vals) // 2]


def main():
    c = core()
    print(f"核心 {c['items']}")
    print("\n== 基线：现在铜的产率 ==")
    base = measure()
    print(f"  铜 {base:+.3f} /s（1 台矿格=4 的钻机）")

    print(f"\n== 放第二台铜钻 {DRILL}（矿格=2）+ 12 格带子 ==")
    try:
        r = a.post("place", x=DRILL[0], y=DRILL[1], block="mechanical-drill", rot=0)
        print(f"  ✓ {str(r.get('message'))[:76]}")
    except ArenaError as e:
        print(f"  ✗ {e.code} {e.message[:120]}")
        return 1
    time.sleep(0.5)
    try:
        r = a.place_path(PATH, "conveyor")
        print(f"  ✓ {str(r.get('message'))[:76]}")
        if r.get("accepted") != r.get("requested"):
            print(f"    ⚠ accepted={r.get('accepted')} requested={r.get('requested')} —— 有格子被拒")
    except ArenaError as e:
        print(f"  ✗ {e.code} {e.message[:120]}")

    print("\n== 等建成并被挖到（判据：/drill 里出现它）==")
    t0 = time.monotonic()
    d = None
    while time.monotonic() - t0 < 120:
        try:
            for x in a.get("drill")["drills"]:
                if (x["x"], x["y"]) == DRILL:
                    d = x
                    break
        except ArenaError:
            pass
        if d:
            break
        time.sleep(1)
    if d:
        print(f"  ✓ ({d['x']},{d['y']}) 主矿={d['dominantItem']} 矿格={d['dominantItems']} "
              f"speed={d['lastDrillSpeed']} eff={d['efficiency']}")
    else:
        print("  ✗ 没等到")
        q = a.queue()
        for b in (q.get("builders") or []):
            for p in (b.get("planList") or []):
                print(f"    卡住 ({p.get('x')},{p.get('y')}) {p.get('block')}: {p.get('stuckReason')}")
        return 1

    print("\n== 加一台之后 ==")
    later = measure()
    print(f"  铜 {later:+.3f} /s（2 台，矿格 4 与 2）")
    if base is not None and later is not None:
        delta = later - base
        print(f"\n== 结论 ==")
        print(f"  差值 = {delta:+.3f} /s")
        print(f"  若矿格不影响：期望 ≈ +0.35")
        print(f"  若正比于矿格：期望 ≈ +0.17")
        if delta > 0.27:
            print("  → 矿格数**基本不影响**单台产率。可放钻机位 = 上限台数。")
        elif delta > 0.10:
            print("  → 产率**正比于矿格数**。只有多矿格的点位才划算。")
        else:
            print("  → 差值过小或采集受扰，需重测。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
