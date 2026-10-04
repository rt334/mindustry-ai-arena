#!/usr/bin/env python3
"""阶段 54：在铜带上截煤——簇 C 的煤现在全被铜带送进核心白扔。

用 inverted-sorter(config=coal) 放在 (64,102)：铜继续进核心，煤被分到侧面；
下面接一台紧贴核心的压机，产物直接落进核心，不需要任何出料带。
"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
UNIT = 221
bs = a.buildings()
print("占用:", [(c, (bs.get(c) or {}).get("block")) for c in
              [(64, 101), (64, 102), (64, 103), (64, 104), (65, 104), (63, 102), (64, 105)]])

print("拆 (64,102):", a.break_many([(64, 102)], workers=1))
t0 = time.time()
while time.time() - t0 < 60:
    if (64, 102) not in a.buildings():
        break
    time.sleep(0.4)

try:
    r = a.call("place", method="POST", x=64, y=102, block="inverted-sorter", rot=2, config="coal")
    print("place sorter:", r)
except Exception as e:
    print("place err:", e)
S = [(64, 103, "conveyor", 1), (64, 104, "graphite-press", 0)]
print("place:", a.place_many(S, workers=2))
for _ in range(25):
    for c in [(64, 102), (64, 103), (64, 104)]:
        try:
            a.call("control", method="POST", op="warp", unit=UNIT, x=c[0], y=c[1])
        except Exception:
            pass
    time.sleep(0.3)
try:
    print("cfg:", a.call("config", method="POST", x=64, y=102, value="coal"))
except Exception as e:
    print("cfgerr:", e)
bs = a.buildings()
print("chk:", [(c, (bs.get(c) or {}).get("block"), (bs.get(c) or {}).get("config")) for c in [(64, 102), (64, 103), (64, 104)]])
print("press:", [(k, b.get("items"), b.get("efficiency")) for k, b in bs.items() if b["block"] == "graphite-press"])
