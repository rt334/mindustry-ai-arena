#!/usr/bin/env python3
"""阶段 10：修煤路（router 汇流 + 煤柱直通汇流带，机器靠 router 截留），并测试 core 是否向下倾倒库存沙。"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221


def warp(x, y):
    try:
        a.call("control", method="POST", op="warp", unit=UNIT, x=int(x), y=int(y))
    except Exception as e:
        print("  warp err:", e)


def smart_place(specs, batch=6, timeout=180):
    missing_all = []
    for i in range(0, len(specs), batch):
        sub = specs[i:i + batch]
        a.place_many(sub, workers=3)
        warp(sum(s[0] for s in sub) / len(sub), sum(s[1] for s in sub) / len(sub))
        t0 = time.time()
        while time.time() - t0 < timeout:
            bs = a.buildings()
            if all(bs.get((s[0], s[1]), {}).get("block") == s[2] for s in sub):
                break
            time.sleep(0.25)
        bs = a.buildings()
        miss = [(s[0], s[1], s[2]) for s in sub if bs.get((s[0], s[1]), {}).get("block") != s[2]]
        if miss:
            print(f"   miss: {miss}")
            missing_all += miss
    return missing_all


dead = [(68, 113), (68, 112), (65, 113), (65, 112), (66, 113), (67, 113)]
print("break:", a.break_many(dead, workers=3), a.confirm_broken(dead, timeout=120))
warp(66, 113)

S = [
    # 煤路骨架
    (66, 113, "router", 0),
    (67, 113, "conveyor", 2),
    (65, 113, "combustion-generator", 0),
    (64, 115, "power-node", 0),
    (66, 112, "router", 0),
    (65, 112, "conveyor", 2),
    (66, 111, "conveyor", 3),
    (66, 110, "router", 0),
    (66, 109, "conveyor", 3),
    (67, 110, "conveyor", 0),
    # core dump 测试：从 core 南缘拉沙
    (63, 107, "conveyor", 1),
]
print("place:", smart_place(S))
warp(61, 104)

t0 = time.time()
while time.time() - t0 < 40:
    b = a.building_at(63, 107)
    if b and b.get("items"):
        print(f"core dump 测试：(63,107) items={b['items']}  -> core 会向下游倒货")
        break
    time.sleep(0.5)
else:
    print("core dump 测试：(63,107) 一直空 -> core 不倒货")

print()
bs = a.buildings()
for k in sorted(bs, key=lambda k: (bs[k]["block"], k[1], k[0])):
    b = bs[k]
    print(f"  {b['block']:<20} ({k[0]:>3},{k[1]:>3}) rot={b.get('rotation')} eff={b.get('efficiency')} "
          f"items={b.get('items')} pow={b.get('powerStatus')}")
print("core:", [b for b in bs.values() if b["block"] == "core-nucleus"][0]["items"])

t0 = time.time()
while time.time() - t0 < 120:
    st = a.rates(window=15).get("stored") or {}
    v = {k: s.get("perSecond", 0) for k, s in st.items()}
    if any(x > 0.05 for x in v.values()):
        break
    time.sleep(1.0)
print("rates:", {k: round(s.get("perSecond", 0), 3) for k, s in (a.rates(window=15).get("stored") or {}).items()})
print("stalls:", [(s['x'], s['y'], s['block'], s['kind'], s.get('missing')) for s in a.stalls() if s.get('team') == 'sharded'])
