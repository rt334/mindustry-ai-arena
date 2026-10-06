#!/usr/bin/env python3
"""定产线路径：为了造出有视野的单位，需要哪些方块、要什么材料。

背景：/intel 的验证需要一个有视野的单位，而 Serpulo（veins）上：
  核心       61 格视野，但挪不动
  radar      34 格，但要铍（Erekir 的），造不了
  普通方块   默认 fogRadius = -1，Block.java:1390 明确只有 > 0 才注册视野
  单位       poly/mega 等 21.75 格 —— 只能走这条路

所以要把「煤+沙 → 硅 → 工厂 → 单位」这条链接起来。先看每一环要什么。
"""
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])

core = next(b for b in a.buildings() if b["block"].startswith("core"))
print(f"核心 {core['block']}  开局库存 {core['items']}\n")

blocks = {b["name"]: b for b in a.get("content").get("blocks", [])}
units = {u["name"]: u for u in a.get("content").get("units", [])}

CHAIN = [
    ("采煤", "mechanical-drill"),
    ("采沙", "mechanical-drill"),
    ("硅冶炼", "silicon-smelter"),
    ("电力", "combustion-generator"),
    ("送电", "power-node"),
    ("工厂", "ground-factory"),
    ("工厂", "air-factory"),
    ("中继", "conveyor"),
]

print("== 沿途要用的方块成本 ==")
seen = set()
for step, name in CHAIN:
    if name in seen:
        continue
    seen.add(name)
    b = blocks.get(name)
    if not b:
        print(f"  {name:<22} /content 里没有")
        continue
    print(f"  {step:<6} {name:<22} cost={b.get('cost')}  size={b.get('size')}  "
          f"hasPower={b.get('hasPower')}")

print("\n== 有视野的建造单位（能造工厂后可选的目标）==")
for n in ("poly", "mega", "nova", "quasar", "pulsar"):
    u = units.get(n)
    if u:
        print(f"  {n:<10} fogRadius={u.get('fogRadius')}  buildSpeed={u.get('buildSpeed')}  "
              f"speed={u.get('speed')}  flying={u.get('flying')}  health={u.get('health')}")

print("\n== 逐步算：从开局 500 铜 / 500 铅 能不能走到工厂 ==")
have = dict(core["items"])
steps = ["mechanical-drill", "conveyor", "silicon-smelter",
         "combustion-generator", "power-node", "ground-factory", "air-factory"]
print(f"  起始 {have}")
for name in steps:
    b = blocks.get(name)
    if not b:
        continue
    cost = b.get("cost") or {}
    lack = {k: v - have.get(k, 0) for k, v in cost.items() if v > have.get(k, 0)}
    status = "够" if not lack else f"缺 {lack}"
    print(f"  造 1 个 {name:<22} 要 {cost}  -> {status}")
    # 不真的扣，只看单件是否可负担
