#!/usr/bin/env python3
"""纠正上一轮的过度概括：不是「单位开过去没用」，而是「部分单位不开视野」。

我上一轮只测了 gamma，就写成「想侦察远处，把单位开过去是没用的」——
这是过度概括。UnitTypes.java 里显式 fogRadius = 0f 的只有 6 处，
其余单位走 init() 的默认推导 max(174, hitSize*2)/8 = 21.75。

这里把全部单位按「有没有视野 / 能不能建造」摊开看。
"""
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])


def main():
    units = a.get("content").get("units") or []
    print(f"/content 共 {len(units)} 个单位\n")

    blind = [u for u in units if (u.get("fogRadius") or 0) <= 0]
    sighted = [u for u in units if (u.get("fogRadius") or 0) > 0]
    print(f"无视野(fogRadius<=0): {len(blind)} 个")
    print(f"有视野(fogRadius>0) : {len(sighted)} 个")

    print("\n== 有视野 且 能建造 的单位（buildSpeed > 0）==")
    rows = [u for u in sighted if (u.get("buildSpeed") or 0) > 0]
    rows.sort(key=lambda u: -(u.get("fogRadius") or 0))
    if rows:
        print(f"  {'名称':<18}{'fogRadius':<12}{'buildSpeed':<12}{'speed':<8}{'飞行':<6}{'血量':<8}")
        for u in rows:
            print(f"  {u['name']:<18}{u.get('fogRadius'):<12}{u.get('buildSpeed'):<12}"
                  f"{u.get('speed'):<8}{str(u.get('flying')):<6}{u.get('health'):<8}")
    else:
        print("  没有")

    print("\n== 无视野的单位（被 FogControl 跳过）==")
    for u in sorted(blind, key=lambda x: x["name"]):
        print(f"  {u['name']:<18} buildSpeed={u.get('buildSpeed')}  "
              f"speed={u.get('speed')}  flying={u.get('flying')}")

    print("\n== 对照：有视野但 buildSpeed=0 的（纯战斗/辅助）==")
    combat = [u for u in sighted if not (u.get("buildSpeed") or 0) > 0]
    combat.sort(key=lambda u: -(u.get("fogRadius") or 0))
    for u in combat[:10]:
        print(f"  {u['name']:<18} fogRadius={u.get('fogRadius')}  "
              f"speed={u.get('speed')}  flying={u.get('flying')}")
    if len(combat) > 10:
        print(f"  ...（共 {len(combat)} 个）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
