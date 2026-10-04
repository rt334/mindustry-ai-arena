#!/usr/bin/env python3
"""验证 A1 / A2 / A4 / A3。

A1/A2   /buildings 里 conveyor 给 acceptsFrom / sendsTo，钻机给实测的 sendsTo
A4      /queue 里每个计划带坐标、目标方块与施工进度
A3      /place 把「队列满 / footprint 被占 / 位置不合法」分成三个码

判据是状态不是时长：建成与否一律 poll_until。
"""
import json
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])


def free(x, y):
    t = a.map(x, y, 1, 1)
    if not t:
        return False
    t = t[0]
    blk = (t.get("block") or "").strip()
    return (not blk or blk == "air") and t.get("visible", False)


def try_place(x, y, block, rot=None):
    """返回一行可读结果；失败不抛，把 code / status / message 都摊开。"""
    try:
        r = a.place(x, y, block, rot=rot)
        return "OK   " + json.dumps(r, ensure_ascii=False)[:170]
    except ArenaError as e:
        return f"ERR  code={e.code} status={e.status}  {e.message}"


def main():
    st = a.state()
    print(f"tick={st['tick']} playing={st['playing']}")

    core = next(b for b in a.buildings() if b["block"].startswith("core"))
    cx, cy = core["x"], core["y"]
    print(f"核心 锚点({cx},{cy}) 5x5 → 占 x[{cx},{cx+4}] y[{cy},{cy+4}]  {core['items']}")

    print("\n== A3 /place 的失败分类 ==")
    print(f"  建在核心格上 (291,106)  -> {try_place(cx + 2, cy + 2, 'conveyor', rot=0)}")
    print(f"  建在岩壁   (288,103)    -> {try_place(cx - 1, cy - 1, 'conveyor', rot=0)}")
    print(f"  越界坐标   (999,999)    -> {try_place(999, 999, 'conveyor', rot=0)}")
    print(f"  未知方块                -> {try_place(cx, cy + 6, 'no-such-block')}")

    # 找核心下方一行连续空地
    row, y0, xs = None, None, None
    for y in range(cy + 5, cy + 14):
        best, cur = [], []
        for x in range(cx - 8, cx + 13):
            if free(x, y):
                cur.append(x)
                if len(cur) > len(best):
                    best = list(cur)
            else:
                cur = []
        if len(best) >= 3:
            row, y0, xs = True, y, best
            break

    if not row:
        print("\n!! 找不到 3 格连续空地，后面跳过")
        return 1

    x0 = xs[0]
    print(f"\n== 建 3 格向皮带（y={y0}, x={x0}..{x0+2}, rot=0 即朝东）==")
    for i in range(3):
        print(f"  ({x0+i},{y0}) -> {try_place(x0 + i, y0, 'conveyor', rot=0)}")

    ok = a.poll_until(
        lambda: all(a.building_at(x0 + i, y0) for i in range(3)), timeout=90)
    print(f"  三格全部落地: {bool(ok)}")

    print("\n== A4 /queue ==")
    print(json.dumps(a.queue(), ensure_ascii=False, indent=1)[:800])

    print("\n== A1/A2 /buildings 的物流字段 ==")
    for b in a.buildings():
        af, st_ = b.get("acceptsFrom"), b.get("sendsTo")
        if af is None and st_ is None:
            continue
        print(f"  {b['block']:<14} ({b['x']},{b['y']}) rot={b['rotation']}  "
              f"acceptsFrom={af}  sendsTo={st_}")

    print("\n-- 解读 --")
    print(f"  3 格带子朝向 rot=0（东）。中间那格 ({x0+1},{y0}) 的 acceptsFrom")
    print(f"  应当只含西侧 ({x0},{y0})（背面，宽收），不含东侧（正面，拒收）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
