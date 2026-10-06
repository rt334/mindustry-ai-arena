#!/usr/bin/env python3
"""建硅产线：煤钻机 + 沙钻机 → 硅冶炼厂 → 核心，附带发电机供电。

布局（核心占 x[287,291] y[102,106]）：
    煤钻机 (288,95)  2x2 = x[288,289] y[95,96]
        │ 向西到 x=292? 不 —— 向东无路，向北绕
        ↓
    冶炼厂 (292,100) 2x2 = x[292,293] y[100,101]   ← 紧贴核心右侧，出货直接进核心
    沙钻机 (288,108) 2x2 = x[288,289] y[108,109]

带子走法：
    煤  (288,97) → (288,98) → (289,98) … 需要绕开核心，从上方走到 x=292 再向南
    沙  (288,110) → (289,110) … 从下方走到 x=292 再向北

硅冶炼厂要电。发电机烧煤，所以煤钻机要同时喂冶炼厂和发电机 ——
钻机向所有相邻接收方推货，所以从它下面拉两条独立带子即可。
"""
import json
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])

COAL = (288, 95)      # 2x2 全煤
SAND = (288, 108)     # 2x2 全沙
SMELTER = (292, 100)  # 2x2，紧贴核心右侧
GEN = (293, 97)       # 1x1 发电机
NODE = (294, 99)      # 1x1 电力节点


def stock():
    c = next((b for b in a.buildings() if b["block"].startswith("core")), None)
    return c["items"] if c else {}


def place(x, y, blk, rot=0, quiet=False):
    try:
        r = a.post("place", x=x, y=y, block=blk, rot=rot)
        if not quiet:
            m = r.get("materials") or {}
            print(f"  ✓ {blk:<20} ({x},{y}) rot={rot}  材料够={m.get('adequate')}")
        return True
    except ArenaError as e:
        if not quiet:
            print(f"  ✗ {blk:<20} ({x},{y}) {e.code}: {e.message[:80]}")
        return False


def path(points, blk="conveyor", quiet=False):
    try:
        r = a.place_path(points, blk)
        if not quiet:
            # tiles 是数量（int），不是数组
            print(f"  ✓ path {r.get('tiles')} 格  {points[0]}→{points[-1]}")
        return True
    except ArenaError as e:
        if not quiet:
            print(f"  ✗ path {points[0]}→{points[-1]}  {e.code}: {e.message[:100]}")
        return False


def wait_queue(timeout=90):
    """等建造队列清空 —— 判据是状态，不是时长"""
    def empty():
        q = a.queue()
        b0 = (q.get("builders") or [{}])[0]
        return (b0.get("plans") or 0) == 0
    return a.poll_until(lambda: True if empty() else None, timeout=timeout)


def main():
    print(f"核心库存 {stock()}\n")

    print("== 1. 放三台机器 ==")
    place(*COAL, "mechanical-drill")
    place(*SAND, "mechanical-drill")
    place(*SMELTER, "silicon-smelter")

    print("\n== 2. 拉煤带：钻机 → 冶炼厂 ==")
    # 钻机下边 y=97；先向南一格，再向东到 x=291，再从冶炼厂上方 y=99 进入
    path([(289, 97), (289, 99), (291, 99), (292, 99)], quiet=False)
    path([(292, 99), (292, 99)], quiet=True)

    print("\n== 3. 拉沙带：钻机 → 冶炼厂 ==")
    # 沙钻机下边 y=110，向东到 x=293 再向北到 y=102（冶炼厂下沿）
    path([(289, 110), (291, 110), (293, 110), (293, 102)], quiet=False)

    print("\n== 4. 供电：发电机 + 节点 ==")
    place(*GEN, "combustion-generator")
    place(*NODE, "power-node")

    print("\n== 5. 等队列清空 ==")
    if wait_queue(120):
        print("  队列已空")
    else:
        q = a.queue()
        b0 = (q.get("builders") or [{}])[0]
        print(f"  队列未空，剩余 {b0.get('plans')}，看前几条：")
        for p in (b0.get("planList") or [])[:3]:
            print(f"    ({p.get('x')},{p.get('y')}) {p.get('block')} "
                  f"stuck={p.get('stuckSeconds')} reason={p.get('stuckReason')}")

    print("\n== 6. 现状 ==")
    for b in a.buildings():
        print(f"  {b['block']:<20} ({b['x']},{b['y']}) rot={b['rotation']} "
              f"power={b.get('powerStatus')} items={b.get('items')}")
    print(f"\n核心库存 {stock()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
