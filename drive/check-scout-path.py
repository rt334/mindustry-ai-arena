#!/usr/bin/env python3
"""看能不能在开局材料内造出有视野的建造单位。

背景：6 个核心的 unitType 恰好就是那 6 个无视野单位
（core-shard→alpha / core-foundation→beta / core-nucleus→gamma /
 Erekir 三核心→evoke/incite/emanate），所以核心送的初始单位必然无视野。
想要视野就得自己造 —— 查一下 air-factory 这条路开局走不走得通。
"""
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])

core = next(b for b in a.buildings() if b["block"].startswith("core"))
print(f"核心 {core['block']}  库存 {core['items']}\n")

blocks = {b["name"]: b for b in a.get("content").get("blocks", [])}
units = {u["name"]: u for u in a.get("content").get("units", [])}


def show(name):
    b = blocks.get(name)
    if not b:
        print(f"  {name}: /content 里没有")
        return
    print(f"  {name:<20} cost={b.get('cost')}  size={b.get('size')}  "
          f"hasPower={b.get('hasPower')}")


print("== 三种单位工厂的成本 ==")
for n in ("ground-factory", "air-factory", "naval-factory",
          "additive-reconstructor", "multiplicative-reconstructor"):
    show(n)

print("\n== 有视野的建造单位，各自的成本/来源 ==")
for n in ("poly", "mega", "nova", "quasar"):
    u = units.get(n)
    if u:
        print(f"  {n:<10} fogRadius={u.get('fogRadius')} buildSpeed={u.get('buildSpeed')} "
              f"speed={u.get('speed')} flying={u.get('flying')} health={u.get('health')}")

print("\n== 开局能不能直接造 air-factory ==")
af = blocks.get("air-factory")
if af:
    cost = af.get("cost") or {}
    have = core["items"]
    missing = {k: v - have.get(k, 0) for k, v in cost.items() if v > have.get(k, 0)}
    print(f"  成本 {cost}")
    print(f"  核心 {have}")
    if missing:
        print(f"  ⇒ 缺 {missing} —— 开局造不了，得先有硅/钛/石墨")
    else:
        print("  ⇒ 材料够，可以造")

print("\n== 对照：哪些方块能产视野 ==")
print("  建筑本身也贡献视野：核心 61 格，其余看各自的 fogRadius")
for n in ("core-nucleus", "core-shard", "power-node", "solar-panel",
          "mechanical-drill", "conveyor", "turret"):
    b = blocks.get(n)
    if b:
        print(f"    {n:<18} fogRadius 不在 /content 里（只有 name/size/health/category/hasPower/cost）")
        break
