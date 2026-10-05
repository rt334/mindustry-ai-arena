#!/usr/bin/env python3
"""验证建造时间：理论值 vs 实测外推。

用 scatter（85 铜 + 45 铅，本图能在开局材料内建的最贵方块）——
silicon-smelter 只建 0.54 秒，轮询根本抓不到窗口；scatter 约 1.3 秒，
配上 100ms 的采样门槛才有足够的采样点。

两个口径交叉印证才有意义：
  buildTime.seconds  理论施工时长，由方块成本与单位速度算出
  etaSeconds         从实测进度变化率外推
两者应当接近；差得远就说明公式抄错了或采样有问题。
"""
import json
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])


def load_grid(cx, cy, r=30):
    w = 2 * r + 1
    return {(t["x"], t["y"]): t for t in a.map(cx - r, cy - r, w, w)}


def free(g, x, y):
    t = g.get((x, y))
    return bool(t) and t.get("visible") and (t.get("block") or "air").strip() in ("", "air")


def main():
    core = next(b for b in a.buildings() if b["block"].startswith("core"))
    cx, cy = core["x"], core["y"]
    print(f"tick={a.state()['tick']}  核心 ({cx},{cy})  {core['items']}")

    g = load_grid(cx, cy)
    size = 2
    spot = None
    for y in range(cy - 23, cy + 24):
        for x in range(cx - 23, cx + 24):
            if all(free(g, x + dx, y + dy) for dy in range(size) for dx in range(size)):
                spot = (x, y)
                break
        if spot:
            break
    if not spot:
        print("找不到 2x2 空地")
        return 1
    tx, ty = spot

    print(f"\n== /place scatter @({tx},{ty}) ==")
    try:
        r = a.post("place", x=tx, y=ty, block="scatter", rot=0)
    except ArenaError as e:
        print(f"  ERR code={e.code} {e.message}")
        return 1
    bt = r.get("buildTime") or {}
    mats = r.get("materials") or {}
    print(f"  materials.adequate = {mats.get('adequate')}")
    print(f"  buildTime = {json.dumps(bt, ensure_ascii=False)}")

    print("\n== 跟踪 /queue（150ms 轮询）==")
    rows = []
    for i in range(30):
        q = a.queue()
        b0 = (q.get("builders") or [{}])[0]
        row = next((p for p in (b0.get("planList") or [])
                    if p.get("x") == tx and p.get("y") == ty), None)
        b = a.building_at(tx, ty)
        state = ("已建成" if (b and b["block"] == "scatter")
                 else ("施工中" if b and b.get("constructing") else "未开工"))
        if row:
            info = (f"progress={row.get('progress')} rate={row.get('progressRate')} "
                    f"eta={row.get('etaSeconds')} stuck={row.get('stuckSeconds')}")
            print(f"  #{i} {state}  {info}")
            if row.get("progressRate") is not None:
                rows.append(row)
        else:
            print(f"  #{i} {state}  （不在队列里）")
            if state == "已建成":
                break
        if state == "已建成":
            break
        time.sleep(0.15)

    print(f"\n  理论 buildTime.seconds = {bt.get('seconds')}")
    if rows:
        etas = [r_.get("etaSeconds") for r_ in rows if r_.get("etaSeconds") is not None]
        rates = [r_.get("progressRate") for r_ in rows if r_.get("progressRate") is not None]
        print(f"  实测速率采样 {rates}")
        print(f"  实测 eta 采样 {etas}")
        # 反推：1 / rate 就是总时长（速率恒定的话）
        if rates:
            implied = [round(1.0 / r_, 2) for r_ in rates if r_ > 1e-6]
            print(f"  由速率反推的总时长 = {implied}   ← 应当接近 buildTime.seconds")
    else:
        print("  没采到 progressRate（方块建得太快）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
