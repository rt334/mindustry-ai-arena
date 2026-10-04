#!/usr/bin/env python3
"""正面案例：钻机旁边放带子，双向印证 sendsTo / acceptsFrom。

钻机是 2x2，锚点 (286,64) → footprint x[286,287] y[64,65]。
在它正下方 (286,66) 放一条 rot=0（朝东）的带子：
  钻机的 sendsTo     应当出现 [286,66]
  带子的 acceptsFrom 应当出现 [286,65]（钻机的下半格，位于带子北侧 = 侧面）
两边互相印证，才是真的通了、不是各自凑出来的数。
"""
import json
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])

DR_X, DR_Y = 286, 64          # 上一轮建成的钻机
BELT = (286, 66)              # 打算放带子的位置


def try_place(x, y, block, rot=None):
    try:
        return "OK", a.place(x, y, block, rot=rot)
    except ArenaError as e:
        return f"ERR code={e.code}", e.message


def main():
    d = a.building_at(DR_X, DR_Y)
    if not d or not d["block"].endswith("drill"):
        print(f"钻机 ({DR_X},{DR_Y}) 不在了：{d and d['block']}")
        return 1
    print(f"钻机 {d['block']} ({DR_X},{DR_Y})  items={d['items']}  "
          f"sendsTo(未放带子前)={d.get('sendsTo')}")

    # ---- 放带子 ----
    print(f"\n== 在 {BELT} 放 conveyor rot=0 ==")
    st, r = try_place(BELT[0], BELT[1], "conveyor", rot=0)
    print(f"  place -> {st} {str(r)[:110]}")
    if st != "OK":
        # 可能已经有东西了，看看是什么
        t = a.map(BELT[0], BELT[1], 1, 1)
        print(f"  该格现状: {json.dumps(t[0], ensure_ascii=False)[:200]}" if t else "  map 取不到")

    got = a.poll_until(lambda: a.building_at(*BELT), timeout=90)
    print(f"  带子落地: {bool(got)}")
    if not got:
        return 1

    # ---- 双向印证 ----
    print("\n== 双向印证 ==")
    d2 = a.building_at(DR_X, DR_Y)
    belt = a.building_at(*BELT)
    print(f"  钻机   ({DR_X},{DR_Y})  sendsTo      = {d2.get('sendsTo')}")
    print(f"  带子   {BELT}  acceptsFrom  = {belt.get('acceptsFrom')}")
    print(f"          {BELT}  sendsTo      = {belt.get('sendsTo')}")

    exp_drill = [[BELT[0], BELT[1]]]
    exp_belt = [[DR_X, DR_Y + 1]]
    ok1 = d2.get("sendsTo") == exp_drill
    ok2 = exp_belt in (belt.get("acceptsFrom") or [])
    print(f"\n  钻机 sendsTo 含 {exp_drill}: {ok1}")
    print(f"  带子 acceptsFrom 含 {exp_belt}（钻机下半格，位于带子北侧=侧面）: {ok2}")

    # ---- A4：下 30 个计划让它积压 ----
    print("\n== A4 队列积压时的 planList ==")
    core = next(b for b in a.buildings() if b["block"].startswith("core"))
    cx, cy = core["x"], core["y"]
    placed = 0
    for y in range(cy + 6, cy + 30):
        for x in range(cx - 14, cx + 18):
            if placed >= 30:
                break
            t = a.map(x, y, 1, 1)
            if not t or not t[0].get("visible"):
                continue
            if (t[0].get("block") or "air").strip() not in ("", "air"):
                continue
            if a.building_at(x, y):
                continue
            st, _ = try_place(x, y, "conveyor", rot=0)
            if st == "OK":
                placed += 1
        if placed >= 30:
            break
    print(f"  已下 {placed} 个计划")

    q = a.queue()
    b0 = (q.get("builders") or [{}])[0]
    print(f"  /queue -> plans={b0.get('plans')}")
    for p in (b0.get("planList") or [])[:6]:
        print(f"    {json.dumps(p, ensure_ascii=False)}")
    if len(b0.get("planList") or []) > 6:
        print(f"    ...（共 {len(b0['planList'])} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
