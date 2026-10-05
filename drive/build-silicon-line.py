#!/usr/bin/env python3
"""⚠ **已弃用** —— 它把某一局的坐标写死了，换一局地图就全线失败（矿脉位置每局重随）。改用 drive/bootstrap.py + drive/production.py，它们开跑前现查地形。保留本文件只为记录当时踩的坑。

硅线引导：从零到产出硅。可重跑。

**这是唯一一条从空局建起的路径，顺序不可换。**

第一版这里放的是 6 块太阳能 —— 结果是死循环：`solar-panel` 要 8 硅，
而硅要电。必须先用**不含硅**的 `combustion-generator`（1×1，
`{copper:25, lead:15}`）烧煤供电。顺序：

    煤钻 → 燃煤发电机 → 硅冶炼厂

布局（坐标全是中心坐标，多格方块在接口里给中心）：

    煤钻A (290,100) 2x2 ──煤带 (292,101)朝南──→ 冶炼厂 (292,102) 2x2
    煤钻B (301,99)  2x2 ──y=101 西行到 (294,101)──→ 发电机 (294,102) 1x1
    沙钻  (289,108) 2x2 ──(291,108)→x=292 北上──→ 冶炼厂底部
    冶炼厂左缘贴核心(x=291) → 硅直接进核心
    发电机紧贴冶炼厂(x=293) → 自动连电力线，不需要电力节点

煤为什么用两台钻机：一台 ~0.32/s，而冶炼厂+发电机合计就要 ~0.6/s。
第一版只有一台，冶炼厂长期 eff=0。煤脉块1 放不下第二台，所以第二台
在块0（距核心 12 格）。
"""
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

COAL_A = (290, 100)
COAL_B = (301, 99)
SAND = (289, 108)
SMELTER = (292, 102)
GEN = (294, 102)

COAL_A_PATH = [(292, 101)]                                  # 朝南进冶炼厂
COAL_B_PATH = [(x, 101) for x in range(301, 293, -1)]        # (301,101)..(294,101) 朝西
SAND_PATH = [(291, 108), (292, 108), (292, 107), (292, 106),
             (292, 105), (292, 104)]                         # 朝北进冶炼厂底部


def main():
    toks, _ = load_tokens()
    a = Arena("beta", toks["beta"])

    core = None
    t0 = time.monotonic()
    while time.monotonic() - t0 < 120:
        try:
            core = next((b for b in a.buildings() if b["block"].startswith("core")), None)
        except Exception:
            core = None
        if core:
            break
        time.sleep(1)
    if not core:
        print("等不到核心")
        return 1
    print(f"核心 ({core['x']},{core['y']})  {core['items']}")

    def step(label, fn):
        try:
            r = fn()
            print(f"  ✓ {label:<32} {str(r.get('message'))[:66]}")
            return r
        except ArenaError as e:
            print(f"  ✗ {label:<32} {e.code}: {e.message[:100]}")
            return None

    print("\n== 下单 ==")
    step(f"煤钻A {COAL_A}", lambda: a.post("place", x=COAL_A[0], y=COAL_A[1],
                                          block="mechanical-drill", rot=0))
    time.sleep(0.4)
    step(f"冶炼厂 {SMELTER}", lambda: a.post("place", x=SMELTER[0], y=SMELTER[1],
                                            block="silicon-smelter", rot=0))
    time.sleep(0.4)
    step("煤带A →冶炼厂", lambda: a.place_path(COAL_A_PATH, "conveyor"))
    time.sleep(0.3)
    step(f"沙钻 {SAND}", lambda: a.post("place", x=SAND[0], y=SAND[1],
                                       block="mechanical-drill", rot=0))
    time.sleep(0.4)
    step(f"沙带 {len(SAND_PATH)}格", lambda: a.place_path(SAND_PATH, "conveyor"))
    time.sleep(0.3)
    step(f"发电机 {GEN}", lambda: a.post("place", x=GEN[0], y=GEN[1],
                                        block="combustion-generator", rot=0))
    time.sleep(0.4)
    step(f"煤钻B {COAL_B}", lambda: a.post("place", x=COAL_B[0], y=COAL_B[1],
                                          block="mechanical-drill", rot=0))
    time.sleep(0.4)
    step(f"煤带B {len(COAL_B_PATH)}格 →发电机",
         lambda: a.place_path(COAL_B_PATH, "conveyor"))

    want = {COAL_A, COAL_B, SAND, SMELTER, GEN} | set(COAL_A_PATH) | \
        set(COAL_B_PATH) | set(SAND_PATH)
    print(f"\n== 等建成（{len(want)} 个，判据是状态）==")
    t0 = time.monotonic()
    while time.monotonic() - t0 < 180:
        try:
            got = {(b["x"], b["y"]) for b in a.buildings()}
        except Exception:
            got = set()
        if want <= got:
            break
        time.sleep(0.5)
    miss = sorted(want - got)
    print(f"  到位 {len(want & got)}/{len(want)}" + (f"  缺 {miss}" if miss else "  ✓"))

    # 只看冶炼厂：power 与两样料都得有
    print("\n== 冶炼厂 ==")
    t0 = time.monotonic()
    sm = None
    while time.monotonic() - t0 < 120:
        sm = next((b for b in a.buildings()
                   if (b["x"], b["y"]) == SMELTER), None)
        if sm and (sm.get("powerStatus") or 0) > 0.8 and (sm.get("efficiency") or 0) > 0.8:
            break
        time.sleep(0.5)
    if sm:
        print(f"  power={sm.get('powerStatus')} eff={sm.get('efficiency')} "
              f"items={sm.get('items')}")

    print("\n== 等硅进核心 ==")
    si0 = core["items"].get("silicon", 0)
    t0 = time.monotonic()
    while time.monotonic() - t0 < 180:
        c = next(b for b in a.buildings() if b["block"].startswith("core"))
        if c["items"].get("silicon", 0) > si0:
            print(f"  ✓ 硅 {si0} → {c['items']['silicon']}   核心={c['items']}")
            return 0
        time.sleep(1)
    c = next(b for b in a.buildings() if b["block"].startswith("core"))
    print(f"  ✗ 硅没增加  核心={c['items']}")
    q = a.queue()
    for b in (q.get("builders") or []):
        for p in (b.get("planList") or []):
            print(f"    卡住 ({p.get('x')},{p.get('y')}) {p.get('block')}: {p.get('stuckReason')}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
