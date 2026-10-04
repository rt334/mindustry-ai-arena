#!/usr/bin/env python3
"""阶段 50：用 sorter 解决「压机把石墨倒回煤道」造成的混料死锁。

煤道 y=112 同时被压机当垃圾口用，石墨随煤流到 (65,112) 再到熔炉，熔炉不收石墨 -> 整条堵死。
把 (65,112) 换成 sorter(config=coal)：煤送前方熔炉，石墨从侧面被带走。
"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221
print("拆 (65,112):", a.break_many([(65, 112)], workers=1))
t0 = time.time()
while time.time() - t0 < 60:
    if (65, 112) not in a.buildings():
        break
    time.sleep(0.4)

# sorter rot=2（朝西）: 煤 -> 前方 (64,112) 熔炉；石墨 -> 侧面
try:
    r = a.call("place", method="POST", x=65, y=112, block="sorter", rot=2, config="coal")
    print("place sorter:", r)
except Exception as e:
    print("place err:", e)
# 侧面清运：南北各接一条小带，指向汇流
S = [(65, 111, "conveyor", 3), (65, 110, "conveyor", 0), (65, 109, "conveyor", 0)]
print("侧线:", a.place_many(S, workers=3))
for _ in range(20):
    for c in [(65, 112), (65, 111), (65, 110), (65, 109)]:
        try:
            a.call("control", method="POST", op="warp", unit=UNIT, x=c[0], y=c[1])
        except Exception:
            pass
    time.sleep(0.25)
bs = a.buildings()
print("chk:", [(c, (bs.get(c) or {}).get("block"), (bs.get(c) or {}).get("config")) for c in [(65, 112), (65, 111), (65, 110)]])
print("smelter:", [(k, b.get("items"), b.get("efficiency")) for k, b in bs.items() if b["block"] == "silicon-smelter"])
