#!/usr/bin/env python3
"""修 drillOutputs 的 footprint 计算 —— 多格方块的坐标是**中心**，不是锚点。

证据（实测 dump）：core-nucleus 覆盖 (287,102)-(291,106)，5x5，
而 /buildings 报的坐标是 (289,104) —— 正好是中心。

Mindustry 的换算（与 ai-client.py 里的 toff 一致）：
    off = -((size - 1) / 2)          // 整数除法
    footprint = [x + off, x + off + size - 1]
  size=2 → off=0    中心落在左上那一格
  size=3 → off=-1   中心在正中
  size=5 → off=-2   中心在正中

原实现直接 x + i（i 从 0 到 size-1），等价于 off=0 ——
对 2x2 的 mechanical-drill / pneumatic-drill 恰好对，
对 3x3 的 laser-drill 就整体偏了一格，sendsTo 会指向错误的邻居。
"""
import pathlib
import sys

S = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Snapshot.java")

OLD = """        arc.struct.IntSeq seq = new arc.struct.IntSeq();
        int x = db.tileX(), y = db.tileY(), s = db.block.size;
        for (int i = 0; i < s; i++) {
            addNeighbour(seq, x + i, y - 1);                    // 上
            addNeighbour(seq, x + i, y + s);                    // 下
            addNeighbour(seq, x - 1, y + i);                    // 左
            addNeighbour(seq, x + s, y + i);                    // 右
        }
        return seq.size == 0 ? null : seq.toArray();"""

NEW = """        arc.struct.IntSeq seq = new arc.struct.IntSeq();
        int s = db.block.size;
        // 多格方块的坐标是**中心**（实测：core-nucleus 覆盖 (287,102)-(291,106)，
        // 而 /buildings 报 (289,104)）。footprint 要按 size 换算：
        //   off = -((size-1)/2)   →  2x2 时 0（中心在左上格）、3x3 时 -1、5x5 时 -2
        // 直接 x+i 只在 2x2 时对，3x3 会整体偏一格。
        int off = -((s - 1) / 2);
        int x0 = db.tileX() + off, y0 = db.tileY() + off;
        for (int i = 0; i < s; i++) {
            addNeighbour(seq, x0 + i, y0 - 1);                  // 上
            addNeighbour(seq, x0 + i, y0 + s);                  // 下
            addNeighbour(seq, x0 - 1, y0 + i);                  // 左
            addNeighbour(seq, x0 + s, y0 + i);                  // 右
        }
        return seq.size == 0 ? null : seq.toArray();"""


def main():
    text = S.read_text(encoding="utf-8")
    n = text.count(OLD)
    if n != 1:
        print(f"!! {n} 次命中（应为 1），未写盘")
        return 1
    S.write_text(text.replace(OLD, NEW), encoding="utf-8")
    print("Snapshot.java：drillOutputs 的 footprint 已按中心换算")
    return 0


if __name__ == "__main__":
    sys.exit(main())
