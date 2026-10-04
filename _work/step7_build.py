#!/usr/bin/env python3
"""阶段 7：清场 + 按施工图重建基础产线（煤→电→硅→石墨，铜→核心）。

施工图（rot: 0=东 1=南 2=西 3=北；坐标为该方块的最小角）
  core-nucleus (61,104) size5 -> 占 x59..63 y102..106
  沙   (61,108) drill rot=1 -> (61,110)/(62,110) 带 rot=1 -> 熔炉
  硅   (60,111) silicon-smelter size2 (占 60..61,111..112)
  煤分配 (59,113) r -> (59,112) 带 rot=3 -> (59,111) router -> 熔炉 + 石墨压机
  石墨 (59,109) graphite-press size2 (占 59..60,109..110) -> (60,108) rot=3 -> (60,107) rot=3 -> core
  电   (64,112) generator <- (64,113) router；node (63,112)+(62,112) 把 gen 与 smelter 并网
  煤链 y=113 x=59..72 全 router
  煤矿 (66,114) drill / (69,115) drill + (69,114) r / (68,116) drill + (68,115) r + (68,114) r
  铜   (68,101) drill rot=2 -> (67,102)(66,102)(65,102)(64,102) 带 rot=2 -> core
"""
import sys
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)

bs = a.buildings()
victims = [k for k, b in bs.items() if b["block"] != "core-nucleus"]
print(f"拆除 {len(victims)} 个旧建筑…")
print("  errs:", a.break_many(victims, workers=6))
ok, left = a.confirm_broken(victims, timeout=240)
print("  全清空:", ok, "残留:", left)

specs = []

# --- 煤链骨架 y=113 ---
for x in range(59, 73):
    specs.append((x, 113, "router", 0))

# --- 沙 ---
specs += [
    (61, 108, "mechanical-drill", 1),
    (61, 110, "conveyor", 1),
    (62, 110, "conveyor", 1),
]
# --- 硅 ---
specs += [
    (60, 111, "silicon-smelter", 0),
    (59, 111, "router", 0),
    (59, 112, "conveyor", 3),
]
# --- 石墨 ---
specs += [
    (59, 109, "graphite-press", 0),
    (60, 108, "conveyor", 3),
    (60, 107, "conveyor", 3),
]
# --- 电 ---
specs += [
    (62, 112, "power-node", 0),
    (63, 112, "power-node", 0),
    (64, 112, "combustion-generator", 0),
]
# --- 煤矿 ---
specs += [
    (66, 114, "mechanical-drill", 3),
    (69, 115, "mechanical-drill", 0),
    (69, 114, "router", 0),
    (68, 116, "mechanical-drill", 0),
    (68, 115, "router", 0),
    (68, 114, "router", 0),
    (67, 114, "router", 0),
]
# --- 铜 ---
specs += [
    (68, 101, "mechanical-drill", 2),
    (67, 102, "conveyor", 2),
    (66, 102, "conveyor", 2),
    (65, 102, "conveyor", 2),
    (64, 102, "conveyor", 2),
]

print(f"下 {len(specs)} 个建造计划…")
print("  errs:", a.place_many(specs, workers=5))
got, missing = a.confirm_placed(specs, timeout=600)
print(f"  建成 {len(got)}/{len(specs)}  missing={missing}")

print()
print("== 现状 ==")
bs = a.buildings()
for k in sorted(bs, key=lambda k: (bs[k]["block"], k[1], k[0])):
    b = bs[k]
    print(f"  {b['block']:<20} ({k[0]:>3},{k[1]:>3}) rot={b.get('rotation')} eff={b.get('efficiency')} "
          f"items={b.get('items')} pow={b.get('powerStatus')}")
print("core:", [b for b in bs.values() if b["block"] == "core-nucleus"][0]["items"])
print("rates:", a.rates(window=20).get("stored"))
