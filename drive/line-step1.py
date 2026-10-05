#!/usr/bin/env python3
"""产线第一步：一台铜钻机 + 一条带子进核心，验证通路。

用上这几轮做的接口能力：
  /place 的 materials —— 下单前就知道材料够不够
  /state 的 limits     —— 不用试探就知批量上限
  /queue 的 stuckSeconds —— 卡住了能定位
  arena.place_path()   —— 折线布线，朝向由服务端算

判据一律是状态（核心库存涨没涨），不是时长。
"""
import json
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])

R = 30
TILESIZE = 8


def load_grid(cx, cy, r=R):
    w = 2 * r + 1
    return {(t["x"], t["y"]): t for t in a.map(cx - r, cy - r, w, w)}


def ore_of(t):
    ov = (t.get("overlay") or "").strip()
    if ov and ov != "air":
        return ov[4:] if ov.startswith("ore-") else ov
    return None


def free(g, x, y):
    t = g.get((x, y))
    if not t or not t.get("visible"):
        return False
    return (t.get("block") or "air").strip() in ("", "air")


def main():
    core = next(b for b in a.buildings() if b["block"].startswith("core"))
    cx, cy = core["x"], core["y"]
    csize = 5
    print(f"核心 {core['block']} 锚点({cx},{cy}) 占 x[{cx},{cx+csize-1}] y[{cy},{cy+csize-1}]")
    print(f"库存 {core['items']}")
    st = a.state()
    print(f"limits = {json.dumps(st.get('limits'), ensure_ascii=False)}")
    print(f"vision.maxRadius = {(st.get('vision') or {}).get('maxRadius')}")

    g = load_grid(cx, cy)

    # ---- 找 2x2 全铜的锚点，优先离核心近的 ----
    #
    # 注意不能只看 overlay 是不是 copper：同一格可能压着岩石（block != air），
    # 或者落在核心自己的 footprint 里 —— 这两种引擎都会拒绝。
    # 而且不靠自己推理「哪格算被占」，直接让 /place 用 validPlace 判，
    # 用 1008 自带的 conflictAt 定位，失败就换下一个候选。
    print("\n== 找 2x2 全铜位置 ==")
    core_cells = {(cx + dx, cy + dy) for dx in range(csize) for dy in range(csize)}
    cands = []
    for y in range(cy - 26, cy + 27):
        for x in range(cx - 26, cx + 27):
            cells = [(x + dx, y + dy) for dy in range(2) for dx in range(2)]
            ts = [g.get(c) for c in cells]
            if any(t is None for t in ts):
                continue
            if any(c in core_cells for c in cells):
                continue
            if not all(ore_of(t) == "copper" for t in ts):
                continue
            if not all((t.get("block") or "air").strip() in ("", "air") for t in ts):
                continue
            cands.append((abs(x - cx) + abs(y - cy), x, y))
    cands.sort()
    if not cands:
        print("  找不到干净的 2x2 全铜")
        return 1
    print(f"  找到 {len(cands)} 个候选，按距离排序前 6：")
    for d, x, y in cands[:6]:
        print(f"    ({x},{y}) 距核心 {d}")

    # ---- 放钻机：失败就换下一个 ----
    mx = my = None
    for d, x, y in cands[:12]:
        try:
            r = a.post("place", x=x, y=y, block="mechanical-drill", rot=0)
            mx, my = x, y
            print(f"\n== /place mechanical-drill @({mx},{my}) 成功（距核心 {d}）==")
            mat = r.get("materials") or {}
            print(f"  adequate={mat.get('adequate')}")
            print(f"  buildTime={json.dumps(r.get('buildTime'), ensure_ascii=False)}")
            print(f"  mode={r.get('mode')}  builder={r.get('builder')}")
            break
        except ArenaError as e:
            print(f"  ({x},{y}) 被拒 code={e.code}: {e.message[:90]}")
    if mx is None:
        print("  12 个候选全被拒")
        return 1

    # ---- 铺带子：钻机 -> 核心 ----
    # 钻机 footprint 的下边界是 my+1，从 (mx, my+2) 起铺到核心左边缘 cx-1
    print("\n== 铺带子进核心 ==")
    start = (mx, my + 2)
    end = (cx - 1, cy + 2)      # 核心左边缘外侧
    print(f"  从 {start} 到 {end}")
    try:
        pr = a.place_path([start, (end[0], start[1]), end], "conveyor")
        print(f"  tiles={pr.get('tiles')}")
        for t in (pr.get("rotations") or []):
            print(f"    {t}")
    except ArenaError as e:
        print(f"  place_path ERR code={e.code} {e.message}")

    # ---- 用 stuckSeconds 盯进度 ----
    print("\n== 盯建造进度 ==")
    last = None
    for i in range(40):
        q = a.queue()
        b0 = (q.get("builders") or [{}])[0]
        lst = b0.get("planList") or []
        stuck = [p for p in lst if p.get("stuckSeconds")]
        if not lst:
            print(f"  #{i} 队列已清空")
            break
        p = lst[0]
        line = (f"  #{i} plans={b0.get('plans')} 首个=({p.get('x')},{p.get('y')}) "
                f"prog={p.get('progress')} eta={p.get('etaSeconds')}")
        if stuck:
            line += f"  !! 卡住 {stuck[0].get('stuckSeconds')}s"
        if line != last:
            print(line)
            last = line
        time.sleep(0.5)

    # ---- 判据：核心铜有没有涨 ----
    print("\n== 等核心铜开始涨 ==")
    start_items = next(b for b in a.buildings()
                       if b["block"].startswith("core"))["items"]
    print(f"  起始 {start_items}")

    def gained():
        b = a.building_at(cx, cy)
        if not b:
            return None
        now = b["items"].get("copper", 0)
        return now if now > start_items.get("copper", 0) else None

    got = a.poll_until(gained, timeout=120)
    if got:
        print(f"  ⇒ 核心铜涨到 {got}（+{got - start_items.get('copper', 0)}）—— 通路打通")
    else:
        print("  ⇒ 120 秒内核心铜没涨，通路没通")
        print("     查：钻机是否建成 / 带子朝向 / 钻机推货方向")
        for b in a.buildings():
            print(f"     {b['block']:<18} ({b['x']},{b['y']}) rot={b['rotation']} "
                  f"items={b.get('items')} sendsTo={b.get('sendsTo')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
