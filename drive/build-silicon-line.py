#!/usr/bin/env python3
"""硅产线：煤钻 + 沙钻 + 硅冶炼厂 + 太阳能。

选点来自 survey-veins.py（都在核心边上，一根绕行线都不用）：

    煤钻 (290,100) 2x2  x[290,291] y[100,101]
    沙钻 (289,108) 2x2  x[289,290] y[108,109]
    冶炼厂 (292,102) 2x2 x[292,293] y[102,103]   ← 左边缘贴核心(x=291)，硅直接进核心
    煤→冶炼厂：(292,101) 朝南 —— 这格同时贴着煤钻和冶炼厂，一根就够
    沙→冶炼厂：(291,108)→(292,108)→(292,107..104) 朝北

**上一轮就是死在忘了供电**：冶炼厂 powerStatus=0 所以只进料不出货。
这次在冶炼厂右侧 (294..296, 102..103) 放 6 块太阳能，相邻自动连线，不需要电力节点。
"""
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])

COAL_DRILL = (290, 100)
SAND_DRILL = (289, 108)
SMELTER = (292, 102)
SOLARS = [(294, 102), (295, 102), (296, 102),
          (294, 103), (295, 103), (296, 103)]
SAND_PATH = [(291, 108), (292, 108), (292, 107), (292, 106), (292, 105), (292, 104)]


def core_items():
    c = next((b for b in a.buildings() if b["block"].startswith("core")), None)
    return c["items"] if c else {}


def step(label, fn):
    try:
        r = fn()
        msg = r.get("message") if isinstance(r, dict) else r
        print(f"  ✓ {label:<34} {str(msg)[:80]}")
        return True
    except ArenaError as e:
        print(f"  ✗ {label:<34} {e.code}: {e.message[:110]}")
        return False


def main():
    core = next((b for b in a.buildings() if b["block"].startswith("core")), None)
    if not core:
        print("没有核心")
        return 1
    print(f"核心 ({core['x']},{core['y']})  {core['items']}")

    before = core_items()
    print(f"\n== 下单 ==")
    step(f"煤钻 {COAL_DRILL}", lambda: a.post("place", x=COAL_DRILL[0], y=COAL_DRILL[1],
                                            block="mechanical-drill", rot=0))
    time.sleep(0.4)
    step(f"沙钻 {SAND_DRILL}", lambda: a.post("place", x=SAND_DRILL[0], y=SAND_DRILL[1],
                                            block="mechanical-drill", rot=0))
    time.sleep(0.4)
    step(f"冶炼厂 {SMELTER}", lambda: a.post("place", x=SMELTER[0], y=SMELTER[1],
                                           block="silicon-smelter", rot=0))
    time.sleep(0.4)
    step("煤带 (292,101) 朝南", lambda: a.post("place", x=292, y=101, block="conveyor", rot=1))
    time.sleep(0.3)
    step(f"沙带 {len(SAND_PATH)} 格", lambda: a.place_path(SAND_PATH, "conveyor"))
    time.sleep(0.3)
    for i, (x, y) in enumerate(SOLARS):
        step(f"太阳能 #{i+1} ({x},{y})", lambda x=x, y=y: a.post("place", x=x, y=y,
                                                              block="solar-panel", rot=0))
        time.sleep(0.25)

    # ── 确认都建起来了 ────────────────────────────────────────────────
    print(f"\n== 等建造完成（判据是状态，不是时长）==")
    want = {(COAL_DRILL[0], COAL_DRILL[1]), (SAND_DRILL[0], SAND_DRILL[1]),
            (SMELTER[0], SMELTER[1]), (292, 101)} | set(SAND_PATH) | set(SOLARS)
    got = set()
    t0 = time.monotonic()
    while time.monotonic() - t0 < 120:
        bs = a.buildings()
        got = {(b["x"], b["y"]) for b in bs
               if b["block"] in ("mechanical-drill", "silicon-smelter",
                                 "conveyor", "solar-panel")}
        if want <= got:
            break
        time.sleep(0.5)
    missing = want - got
    print(f"  已建 {len(want & got)}/{len(want)}" + (f"  缺 {sorted(missing)}" if missing else "  ✓ 全部到位"))

    # ── 冶炼厂供电与运行状态 ──────────────────────────────────────────
    print(f"\n== 冶炼厂状态 ==")
    t0 = time.monotonic()
    last = None
    for _ in range(60):
        b = next((x for x in a.buildings()
                  if x["x"] == SMELTER[0] and x["y"] == SMELTER[1]), None)
        if b:
            ps = b.get("powerStatus")
            last = (ps, b.get("efficiency"), b.get("items"))
            if ps is not None and ps > 0.9 and (b.get("items") or {}).get("silicon"):
                break
        time.sleep(0.5)
    if last:
        print(f"  powerStatus={last[0]}  efficiency={last[1]}  items={last[2]}")

    # ── 核心里的硅 ────────────────────────────────────────────────────
    print(f"\n== 核心里的硅（判据：硅数量增加）==")
    t0 = time.monotonic()
    si0 = (before or {}).get("silicon", 0)
    while time.monotonic() - t0 < 150:
        it = core_items()
        si = it.get("silicon", 0)
        if si > si0:
            print(f"  ✓ 硅 {si0} → {si}   核心={it}")
            return 0
        time.sleep(1)
    it = core_items()
    print(f"  ✗ 150 秒内硅没增加  核心={it}")

    # 诊断
    print("\n== 诊断 ==")
    try:
        for d in a.drill():
            print(f"  钻机 {d.get('block')} ({d.get('x')},{d.get('y')}) "
                  f"items={d.get('items')} efficiency={d.get('efficiency')} "
                  f"power={d.get('powerStatus')}")
    except ArenaError as e:
        print(f"  /drill {e.code}")
    try:
        for s in a.stalls():
            print(f"  警报 {s}")
    except ArenaError as e:
        print(f"  /stalls {e.code}")
    try:
        print(f"  速率 {a.rates(window=10)}")
    except ArenaError as e:
        print(f"  /rates {e.code}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
