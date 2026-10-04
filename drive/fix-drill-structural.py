#!/usr/bin/env python3
"""修正 drillOutputs：判「挨着谁」，不判「此刻收不收」。

实测撞到的现象：
    钻机 (286,64)，带子 (286,66) 上堆着 2 个铜 —— 物理上货在流。
    但 /buildings 报钻机 sendsTo=null。

原因：原实现逐个邻格调 acceptItem，而 Conveyor.acceptItem 读的是瞬时状态
（Conveyor.java:354 `if(len >= capacity) return false` 与 358 的 minitem 阈值）。
带子入口被自己身上的货占住时 minitem <= 0.7，侧面判定立刻变 false。

对布线来说需要的是**结构事实**（挨着哪几个邻居），不是瞬时状态。
后者会抖，前者稳定、可缓存。
"""
import pathlib
import sys

P = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Snapshot.java")

OLD = """    private static int[] drillOutputs(mindustry.gen.Building b) {
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

NEW = """    private static int[] drillOutputs(mindustry.gen.Building b) {
        if (!(b instanceof mindustry.world.blocks.production.Drill.DrillBuild db)) return null;

        arc.struct.IntSeq seq = new arc.struct.IntSeq();
        int x = db.tileX(), y = db.tileY(), s = db.block.size;
        for (int i = 0; i < s; i++) {
            addNeighbour(seq, x + i, y - 1);                    // 上
            addNeighbour(seq, x + i, y + s);                    // 下
            addNeighbour(seq, x - 1, y + i);                    // 左
            addNeighbour(seq, x + s, y + i);                    // 右
        }
        return seq.size == 0 ? null : seq.toArray();
    }

    /**
     * 只列**有建筑**的方位，不判「此刻能不能收」。
     *
     * 原先这里调的是 `acceptItem`，读数会来回抖：传送带入口被自己身上的货占住时
     * `minitem <= 0.7`（Conveyor.java:358 的侧面条件），判定立刻变 false，
     * sendsTo 就空了 —— 而钻机其实一直在往那条带子上推货。实测撞到过：
     * 带子上明明堆着 2 个铜，sendsTo 却是 null。
     *
     * 「这台钻机挨着哪几个邻居」是**结构事实**，稳定、可缓存、能拿来布线；
     * 「此刻这一格收不收」是瞬时状态，要判也该由读的人结合 items 自己判。
     */
    private static void addNeighbour(arc.struct.IntSeq seq, int x, int y) {
        if (Vars.world.build(x, y) == null) return;
        seq.add(arc.math.geom.Point2.pack(x, y));
    }"""


def main():
    text = P.read_text(encoding="utf-8")
    n = text.count(OLD)
    if n != 1:
        print(f"!! {n} 次命中（应为 1），未写盘")
        return 1
    P.write_text(text.replace(OLD, NEW), encoding="utf-8")
    print("Snapshot.java：drillOutputs 改为结构判定")
    return 0


if __name__ == "__main__":
    sys.exit(main())
