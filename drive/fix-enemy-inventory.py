#!/usr/bin/env python3
"""裁掉敌方建筑的库存 —— DESIGN.md 4.4 那处「刻意偏离」的前提条件。

DESIGN.md:909 原文：
    **前提**：/state 里必须裁掉 writeStateSnapshot 的全量核心库存（只保留自己队）。

设计意图（4.4 节 + 6.2 节）：
  原版把每个队的核心库存**无条件广播**给所有客户端（NetServer.writeStateSnapshot），
  本项目刻意偏离——改为「按视野给」，而且敌方库存要**连续可见 600 tick（10 秒）**
  才算「确认」，之后才能拿到快照。Intel 状态机就是干这个的，它直接读引擎，
  不依赖 /buildings。

缺口：visibleBuildings 对可见的敌方建筑**照样输出完整 items / liquids**，
等于绕过了整套确认机制 —— AI 一进视野就能读到敌方核心有多少铜，
而设计上它该盯满 10 秒。

修法：非己方队伍的建筑，items / liquids 一律清空。
其余字段保留 —— 朝向、效率、电力条都是画在屏幕上的（玩家看得见），
这个文件里本来就逐项论证过。
"""
import pathlib
import sys

H = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\HttpApi.java")

OLD = """            StringBuilder its = new StringBuilder("{");
            for (int i = 0; i < b.items.length; i++) {
                if (i > 0) its.append(',');
                its.append(Json.str(b.items[i])).append(':').append(b.itemAmounts[i]);
            }
            its.append('}');

            StringBuilder lqs = new StringBuilder("{");
            for (int i = 0; i < b.liquids.length; i++) {
                if (i > 0) lqs.append(',');
                lqs.append(Json.str(b.liquids[i])).append(':').append(b.liquidAmounts[i]);
            }
            lqs.append('}');"""

NEW = """            // 库存只给自己的队（DESIGN.md 4.4 的刻意偏离，也是 6.2 的前提）：
            // 原版把每队核心库存无条件广播，本项目改为「按视野 + 需确认」——
            // 敌方库存要连续可见 600 tick 才由 Intel 状态机放出快照。
            // 这里如果照样输出，等于让 AI 一进视野就读到对面核心有多少铜，
            // 整套确认机制被绕过。
            //
            // 其余字段不动：朝向、效率、电力条都是画在屏幕上的，玩家看得见。
            boolean ownTeam = (b.team == myTeam) || admin;

            StringBuilder its = new StringBuilder("{");
            if (ownTeam) {
                for (int i = 0; i < b.items.length; i++) {
                    if (i > 0) its.append(',');
                    its.append(Json.str(b.items[i])).append(':').append(b.itemAmounts[i]);
                }
            }
            its.append('}');

            StringBuilder lqs = new StringBuilder("{");
            if (ownTeam) {
                for (int i = 0; i < b.liquids.length; i++) {
                    if (i > 0) lqs.append(',');
                    lqs.append(Json.str(b.liquids[i])).append(':').append(b.liquidAmounts[i]);
                }
            }
            lqs.append('}');"""


def main():
    text = H.read_text(encoding="utf-8")
    n = text.count(OLD)
    if n != 1:
        print(f"!! {n} 次命中（应为 1），未写盘")
        return 1
    H.write_text(text.replace(OLD, NEW), encoding="utf-8")
    print("HttpApi.java：敌方建筑的库存已裁掉")
    return 0


if __name__ == "__main__":
    sys.exit(main())
