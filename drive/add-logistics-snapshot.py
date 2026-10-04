#!/usr/bin/env python3
"""A1 / A2 / 补1：让 /buildings 说出物流接口。

现象（FEATURE-REQUESTS A1，★★★★★ 最高痛点）：
「反复设计出『图纸上对、实际堵死』的链。place 成功、rotation 也对，
  物品就是不动。」—— 传输规则完全没有接口暴露，只能靠实验反推。

这里把「规则」暴露出来（不是「结论」，红线见 REVIEW-ADDENDUM §3）：
  acceptsFrom  这一格能从哪几个邻格收货（传送带专用）
  sendsTo      它把货推到哪（传送带 = 正面格；钻机 = 实测能接的邻格）

依据全部来自源码，不是猜的：
  Conveyor.java:352-358
      int direction = Math.abs(facing.relativeTo(tile.x, tile.y) - rotation);
      direction == 0   背面，minitem >= 0.4  收
      direction 1 / 3  两侧，minitem >  0.7  收
      direction == 2   正面（下游）          拒收
  Tile.java:95-101   relativeTo 编码 0=西 1=北 2=东 3=南
  Drill.java:289     dump() 向所有相邻接收方推货，不受 rotation 控制
  Building.java:577  acceptItem 是纯判定，无副作用
"""
import pathlib
import sys

P = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Snapshot.java")

FIELDS_OLD = """        public final int[] powerLinks;

        BuildInfo(int x, int y, int team, String block,"""

FIELDS_NEW = """        public final int[] powerLinks;

        /**
         * 能推货进来的邻格（Point2.pack），null 表示该方块没有「接货口」概念。
         *
         * 传送带专用，按 `Conveyor.acceptItem` 的方位规则算（Conveyor.java:352-358）：
         *
         *     direction = |relativeTo(源格) - rotation|
         *     direction == 0   背面，minitem >= 0.4   收
         *     direction 1 / 3  两侧，minitem >  0.7   收  ← 拐弯容易堵的真因
         *     direction == 2   正面（下游）           拒收
         *
         * 只列**该方位上真有建筑**的格 —— 空地不列，免得读的人以为那里有东西。
         *
         * 这是**规则**不是**结论**：告诉 AI 这格能从哪边收料，不替它判断
         * 「这条链会不会堵」。
         */
        public final int[] acceptsFrom;

        /**
         * 把货推出去的格（Point2.pack）。
         *
         * 传送带 = 正面那一格（不管那里有没有东西，那是它的朝向）。
         * 钻机 = **所有能接收的邻格** —— 钻机输出不受 rotation 控制，
         * 所以这里给的是实测结果而不是推导，探针用它脚下占多数的那个矿。
         */
        public final int[] sendsTo;

        BuildInfo(int x, int y, int team, String block,"""

CTOR_OLD = """                  int rotation, float powerStatus, int[] powerLinks) {
            this.x = x; this.y = y; this.team = team; this.block = block;
            this.health = health; this.maxHealth = maxHealth;
            this.enabled = enabled; this.efficiency = efficiency;
            this.items = items; this.itemAmounts = itemAmounts;
            this.liquids = liquids; this.liquidAmounts = liquidAmounts;
            this.config = config; this.constructing = constructing;
            this.buildProgress = buildProgress;
            this.rotation = rotation;
            this.powerStatus = powerStatus;
            this.powerLinks = powerLinks;
        }"""

CTOR_NEW = """                  int rotation, float powerStatus, int[] powerLinks,
                  int[] acceptsFrom, int[] sendsTo) {
            this.x = x; this.y = y; this.team = team; this.block = block;
            this.health = health; this.maxHealth = maxHealth;
            this.enabled = enabled; this.efficiency = efficiency;
            this.items = items; this.itemAmounts = itemAmounts;
            this.liquids = liquids; this.liquidAmounts = liquidAmounts;
            this.config = config; this.constructing = constructing;
            this.buildProgress = buildProgress;
            this.rotation = rotation;
            this.powerStatus = powerStatus;
            this.powerLinks = powerLinks;
            this.acceptsFrom = acceptsFrom;
            this.sendsTo = sendsTo;
        }"""

ADD_OLD = """                list.add(new BuildInfo(
                    b.tileX(), b.tileY(), b.team.id, b.block.name,
                    b.health, b.maxHealth, b.enabled, b.efficiency,
                    iNames, iAmts, lNames, lVals, cfg, constructing, progress,
                    b.rotation, pstat, plinks));
            }
        }
        return list.toArray(BuildInfo.class);
    }"""

ADD_NEW = """                // 物流接口：这一格能从哪收、往哪推。单独 try —— 判定失败
                // 不该让整张快照挂掉。
                int[] acceptsFrom = null, sendsTo = null;
                try {
                    acceptsFrom = conveyorInputs(b);
                    sendsTo = conveyorOutput(b);
                    if (sendsTo == null) sendsTo = drillOutputs(b);
                } catch (Throwable ignored) { }

                list.add(new BuildInfo(
                    b.tileX(), b.tileY(), b.team.id, b.block.name,
                    b.health, b.maxHealth, b.enabled, b.efficiency,
                    iNames, iAmts, lNames, lVals, cfg, constructing, progress,
                    b.rotation, pstat, plinks, acceptsFrom, sendsTo));
            }
        }
        return list.toArray(BuildInfo.class);
    }

    // ---------------------------------------------------------------- 物流接口

    /**
     * relativeTo 编码 → 格偏移（Tile.java:95-101）。
     *
     *     0 = 西 (x-1)   1 = 北 (y-1)   2 = 东 (x+1)   3 = 南 (y+1)
     *
     * 别按屏幕直觉读：y 向下增长，编码 3 是屏幕**下方**。
     * rotation 用同一套编码，于是 rot 0 = 面朝东、1 = 面朝南、2 = 面朝西、3 = 面朝北。
     * （引擎自己在 Conveyor.java:166 的注释里把 1 写成「北」，那是照抄 Rotation.top
     *   这个枚举名 —— 枚举的 top 指向屏幕下方，别信它。）
     */
    private static final int[] REL_DX = {-1, 0, 1, 0};
    private static final int[] REL_DY = {0, -1, 0, 1};

    /** 传送带的接货口：背面 + 两侧，只保留该方位上真有建筑的格。正面拒收，不列。 */
    private static int[] conveyorInputs(mindustry.gen.Building b) {
        if (!(b instanceof mindustry.world.blocks.distribution.Conveyor.ConveyorBuild)) return null;
        arc.struct.IntSeq seq = new arc.struct.IntSeq();
        int x = b.tileX(), y = b.tileY(), r = b.rotation;
        for (int rel = 0; rel < 4; rel++) {
            if (Math.abs(rel - r) == 2) continue;               // 正面：拒收
            int nx = x + REL_DX[rel], ny = y + REL_DY[rel];
            if (Vars.world.build(nx, ny) == null) continue;     // 那格是空地
            seq.add(arc.math.geom.Point2.pack(nx, ny));
        }
        return seq.size == 0 ? null : seq.toArray();
    }

    /** 传送带的正面格。即使空着也返回 —— 那是它的朝向。 */
    private static int[] conveyorOutput(mindustry.gen.Building b) {
        if (!(b instanceof mindustry.world.blocks.distribution.Conveyor.ConveyorBuild)) return null;
        int rel = (b.rotation + 2) % 4;
        return new int[]{ arc.math.geom.Point2.pack(b.tileX() + REL_DX[rel],
                                                    b.tileY() + REL_DY[rel]) };
    }

    /**
     * 钻机实际能推货出去的邻格。
     *
     * 钻机输出不受 rotation 控制（Drill.java:289 的 dump 向所有相邻接收方推），
     * 所以这不是推导而是实测：拿它脚下占多数的那个矿当探针，逐个邻格调 acceptItem。
     * footprint 退化成一份「谁在接货」的真实清单。
     */
    private static int[] drillOutputs(mindustry.gen.Building b) {
        if (!(b instanceof mindustry.world.blocks.production.Drill.DrillBuild db)) return null;
        mindustry.type.Item probe = db.dominantItem;
        if (probe == null) return null;

        arc.struct.IntSeq seq = new arc.struct.IntSeq();
        int x = db.tileX(), y = db.tileY(), s = db.block.size;
        for (int i = 0; i < s; i++) {
            addAcceptor(seq, db, probe, x + i, y - 1);          // 上
            addAcceptor(seq, db, probe, x + i, y + s);          // 下
            addAcceptor(seq, db, probe, x - 1, y + i);          // 左
            addAcceptor(seq, db, probe, x + s, y + i);          // 右
        }
        return seq.size == 0 ? null : seq.toArray();
    }

    /** acceptItem 是纯判定（Building.java:577 / Conveyor.java:352），调用无副作用。 */
    private static void addAcceptor(arc.struct.IntSeq seq, mindustry.gen.Building from,
                                    mindustry.type.Item probe, int x, int y) {
        mindustry.gen.Building nb = Vars.world.build(x, y);
        if (nb == null) return;
        if (nb.acceptItem(from, probe)) seq.add(arc.math.geom.Point2.pack(x, y));
    }"""

RULES = [
    (FIELDS_OLD, FIELDS_NEW, "BuildInfo 加 acceptsFrom / sendsTo 字段"),
    (CTOR_OLD, CTOR_NEW, "构造函数加两个参数"),
    (ADD_OLD, ADD_NEW, "采集点 + 四个辅助方法"),
]


def main():
    text = P.read_text(encoding="utf-8")
    bad = []
    for old, new, label in RULES:
        n = text.count(old)
        if n != 1:
            bad.append(f"{n} 次命中（应为 1）: {label}")
            print(f"  !! {n} 次  {label}")
            continue
        text = text.replace(old, new)
        print(f"  1 处  {label}")
    if bad:
        print("\n有规则不满足，未写盘：")
        for b in bad:
            print("  " + b)
        return 1
    P.write_text(text, encoding="utf-8")
    print(f"\nSnapshot.java 已更新，共 {len(RULES)} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
