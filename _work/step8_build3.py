#!/usr/bin/env python3
"""阶段 8：清场 + 重建 v3 布局；用 /control op=warp 把建造单位送到施工现场加速。

v3 关键修正：
  * 汇流改回**传送带**（router 串联吞吐太低，实测堵塞）
  * 工厂的输入/输出带严格分开摆放，避免钻机把料倒进输出带、或工厂把产物倒进燃料干带
"""
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


def smart_place(specs, batch=6, timeout=150):
    missing_all = []
    for i in range(0, len(specs), batch):
        sub = specs[i:i + batch]
        a.place_many(sub, workers=3)
        cx = sum(s[0] for s in sub) / len(sub)
        cy = sum(s[1] for s in sub) / len(sub)
        warp(cx, cy)
        t0 = time.time()
        while time.time() - t0 < timeout:
            bs = a.buildings()
            if all(bs.get((s[0], s[1]), {}).get("block") == s[2] for s in sub):
                break
            time.sleep(0.25)
        bs = a.buildings()
        miss = [(s[0], s[1], s[2]) for s in sub if bs.get((s[0], s[1]), {}).get("block") != s[2]]
        if miss:
            print(f"   批次 {i//batch} 未完成: {miss}")
            missing_all += miss
            warp(cx, cy)
    return missing_all


bs = a.buildings()
victims = [k for k, b in bs.items() if b["block"] != "core-nucleus"]
print(f"拆除 {len(victims)} 旧建筑")
print("  errs:", a.break_many(victims, workers=6))
print("  cleared:", a.confirm_broken(victims, timeout=300)[0])
warp(61, 104)

S = []
# 1 汇流带 y=108（朝西），末端从西侧注入 core
for x in range(59, 71):
    S.append((x, 108, "conveyor", 2))
S += [(59, 108, "conveyor", 3), (59, 107, "conveyor", 3)]
# 2 沙钻机（东邻正对熔炉，避免把沙倒进输出带）
S.append((61, 110, "mechanical-drill", 0))
# 3 硅熔炉 + 产物输出
S += [(63, 111, "silicon-smelter", 0), (64, 110, "conveyor", 3), (64, 109, "conveyor", 3)]
# 4 煤干带 y=113 朝西，中间一格 router 分流给石墨压机
for x in range(66, 74):
    S.append((x, 113, "conveyor", 2))
S += [(68, 113, "router", 0)]
# 5 煤支线进熔炉
S += [(65, 113, "conveyor", 3), (65, 112, "conveyor", 2)]
# 6 电
S += [(65, 114, "combustion-generator", 0), (65, 115, "combustion-generator", 0),
      (64, 114, "power-node", 0), (64, 113, "power-node", 0)]
# 7 石墨压机 + 产物输出
S += [(68, 110, "graphite-press", 0), (68, 112, "conveyor", 3), (69, 109, "conveyor", 3)]
# 8 煤钻机
S += [(66, 114, "mechanical-drill", 0), (69, 115, "mechanical-drill", 0),
      (69, 114, "conveyor", 3), (68, 116, "mechanical-drill", 0),
      (68, 115, "conveyor", 3), (68, 114, "conveyor", 3)]
# 9 铜线
S += [(68, 101, "mechanical-drill", 2),
      (67, 102, "conveyor", 2), (66, 102, "conveyor", 2),
      (65, 102, "conveyor", 2), (64, 102, "conveyor", 2)]

print(f"建造 {len(S)} 项")
miss = smart_place(S, batch=6)
print("missing:", miss)
warp(61, 104)
print("done")
