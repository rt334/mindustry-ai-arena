#!/usr/bin/env python3
"""把单位开到敌方核心旁边，真正验证库存裁剪。

上一轮没验成：各队核心相距 228 格，而视野只有 61 格，己方视野里
压根没有敌方建筑 —— 统计上「可见敌方建筑 0」，证明不了裁剪逻辑。

这里让 beta 的单位走到最近的那个敌方核心附近（CommandAI 自己寻路），
再看 beta 的 /buildings：敌方核心应该出现（在视野内），
但 items 必须是空的。
"""
import json
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
beta = Arena("beta", toks["beta"])
adm = Arena("referee", toks["referee"])


def main():
    # 全部核心位置
    allb = adm.get("buildings", view="all").get("buildings", [])
    cores = [b for b in allb if b["block"].startswith("core")]
    print("所有核心:")
    for c in cores:
        items = c.get("items") or {}
        print(f"  team {c['team']:<4} {c['block']:<15} @({c['x']},{c['y']})  "
              f"items={items}")

    mine = next((c for c in cores if c["team"] == 2), None)
    enemies = [c for c in cores if c["team"] != 2]
    if not mine or not enemies:
        print("找不到己方或敌方核心")
        return 1

    # 挑最近的敌方核心
    def dist(a, b):
        return ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5

    tgt = min(enemies, key=lambda c: dist(c, mine))
    print(f"\n己方核心 @({mine['x']},{mine['y']})")
    print(f"最近的敌方核心 team {tgt['team']} @({tgt['x']},{tgt['y']})  "
          f"距离 {dist(tgt, mine):.0f} 格")
    print(f"  该核心真实库存（admin 视角）: {tgt.get('items')}")

    u = (beta.units() or [None])[0]
    if not u:
        print("beta 没有单位")
        return 1
    uid = u["id"]
    print(f"\n命令单位 #{uid} 去 ({tgt['x'] - 3},{tgt['y'] - 3})")
    try:
        beta.post("control", op="order", unit=uid, x=tgt["x"] - 3, y=tgt["y"] - 3)
    except ArenaError as e:
        print(f"  order ERR {e.code} {e.message}")
        return 1

    # 轮询：等敌方建筑进入己方视野
    print("\n轮询 beta 的 /buildings，等敌方建筑出现：")
    seen = None
    for i in range(40):
        bs = beta.buildings()
        enemy_builds = [b for b in bs if b.get("team") != 2]
        uu = (beta.units() or [{}])[0]
        pos = f"({uu.get('x', 0)/8:.0f},{uu.get('y', 0)/8:.0f})"
        if enemy_builds:
            print(f"  #{i:>2} 单位@ {pos}  可见建筑 {len(bs)} 个，其中敌方 {len(enemy_builds)} 个")
            for b in enemy_builds[:4]:
                print(f"        team {b['team']} {b['block']} @({b['x']},{b['y']}) "
                      f"items={b.get('items')} efficiency={b.get('efficiency')} "
                      f"rotation={b.get('rotation')}")
            seen = enemy_builds
            break
        else:
            print(f"  #{i:>2} 单位@ {pos}  可见建筑 {len(bs)} 个（全是自己的）")
        time.sleep(1.5)

    print()
    if seen:
        leaked = [b for b in seen if b.get("items")]
        print(f"  出现敌方建筑 {len(seen)} 个，其中带 items 的 {len(leaked)} 个")
        if leaked:
            print(f"  !! 泄漏：{[(b['block'], b['items']) for b in leaked]}")
        else:
            print("  ⇒ 裁剪生效：敌方建筑可见，但库存是空的")
            # 对照：同一个响应里己方建筑应当仍然带 items
            mineb = [b for b in beta.buildings() if b.get("team") == 2 and b.get("items")]
            print(f"     对照：己方有 {len(mineb)} 个建筑带 items（正常）")
    else:
        print("  40 次轮询内敌方建筑始终没进视野 —— 可能走不过去（被墙挡）")
        print("  这条仍未实测，只能靠代码逻辑确认。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
