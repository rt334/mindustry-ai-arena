#!/usr/bin/env python3
"""把 mapData 的 ores/walls 也改成 RLE —— 逐格存让地图比整局录像还大。

实测（全图 350x200 = 70000 格）：
  walls 44658 格（占 64%）、ores 4994 格 —— 逐格存出来 1.38 MB，
  而整局录像才 1.24 MB。地图比录像还大，本末倒置。

岩壁和矿脉都是**成片**的，逐格存纯属浪费。改成一维 RLE（行优先展开），
和 floors 用同一套编码：[名称, 段长, 名称, 段长, ...]，无矿/无墙的段用 null。

预期从 1.38 MB 压到几十 KB。
"""
import pathlib
import sys

R = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Recorder.java")

OLD = """     * 70000 格全存太大，所以只存「非默认」的：
     *   floors  一维 RLE，[名称, 段长, 名称, 段长, ...]（行优先展开）
     *   ores    逐格 —— 本来就稀疏（本局实测 253 格）
     *   walls   逐格 —— 固体静态方块（岩壁），约 949 格
     *
     * 整图扫一遍只在录制开始时做一次，几十毫秒。
     */"""

NEW = """     * 70000 格逐个存会爆 —— 实测全图 walls 44658 格（占 64%）、ores 4994 格，
     * 逐格写成 JSON 是 1.38 MB，而整局录像才 1.24 MB。地图比录像还大，本末倒置。
     *
     * 三样都用一维 RLE（行优先展开）：[名称, 段长, 名称, 段长, ...]
     * 岩壁和矿脉都是成片的，RLE 之后通常只剩几百段。
     * 无矿 / 无墙的段用 null 占位。
     *
     * 整图扫一遍只在录制开始时做一次，几十毫秒。
     */"""

BODY_OLD = """            StringBuilder floors = new StringBuilder("[");
            StringBuilder ores = new StringBuilder("[");
            StringBuilder walls = new StringBuilder("[");

            String prev = null;
            int run = 0;
            boolean ff = true, of = true, wf = true;

            for (int y = 0; y < h; y++) {
                for (int x = 0; x < w; x++) {
                    mindustry.world.Tile t = world.tile(x, y);
                    if (t == null) continue;

                    String fl = t.floor() == null ? "air" : t.floor().name;
                    if (!fl.equals(prev)) {
                        if (prev != null) {
                            if (!ff) floors.append(',');
                            ff = false;
                            floors.append(Json.str(prev)).append(',').append(run);
                        }
                        prev = fl;
                        run = 1;
                    } else {
                        run++;
                    }

                    if (t.overlay() != null && !"air".equals(t.overlay().name)) {
                        if (!of) ores.append(',');
                        of = false;
                        ores.append('[').append(x).append(',').append(y).append(',')
                              .append(Json.str(t.overlay().name)).append(']');
                    }

                    mindustry.world.Block bl = t.block();
                    if (bl != null && bl.isStatic() && bl.solid) {
                        if (!wf) walls.append(',');
                        wf = false;
                        walls.append('[').append(x).append(',').append(y).append(',')
                             .append(Json.str(bl.name)).append(']');
                    }
                }
            }
            if (prev != null) {
                if (!ff) floors.append(',');
                floors.append(Json.str(prev)).append(',').append(run);
            }
            floors.append(']');
            ores.append(']');
            walls.append(']');"""

BODY_NEW = """            StringBuilder floors = new StringBuilder("[");
            StringBuilder ores = new StringBuilder("[");
            StringBuilder walls = new StringBuilder("[");

            // 三样共用同一套 RLE：名称（或 null）+ 段长
            String pFloor = null, pOre = null, pWall = null;
            int rFloor = 0, rOre = 0, rWall = 0;
            boolean ff = true, of = true, wf = true;

            for (int y = 0; y < h; y++) {
                for (int x = 0; x < w; x++) {
                    mindustry.world.Tile t = world.tile(x, y);
                    if (t == null) continue;

                    String fl = t.floor() == null ? "air" : t.floor().name;

                    String ov = t.overlay() == null ? null : t.overlay().name;
                    if ("air".equals(ov)) ov = null;

                    mindustry.world.Block bl = t.block();
                    String wl = (bl != null && bl.isStatic() && bl.solid) ? bl.name : null;

                    if (pFloor != null && fl.equals(pFloor)) rFloor++;
                    else {
                        if (pFloor != null) { appendRun(floors, pFloor, rFloor); ff = false; }
                        pFloor = fl; rFloor = 1;
                    }

                    if (ov == null ? pOre == null : ov.equals(pOre)) rOre++;
                    else {
                        if (pOre != null || rOre > 0) { appendRun(ores, pOre, rOre); of = false; }
                        pOre = ov; rOre = 1;
                    }

                    if (wl == null ? pWall == null : wl.equals(pWall)) rWall++;
                    else {
                        if (pWall != null || rWall > 0) { appendRun(walls, pWall, rWall); wf = false; }
                        pWall = wl; rWall = 1;
                    }
                }
            }
            if (pFloor != null) appendRun(floors, pFloor, rFloor);
            if (pOre != null || rOre > 0) appendRun(ores, pOre, rOre);
            if (pWall != null || rWall > 0) appendRun(walls, pWall, rWall);
            floors.append(']');
            ores.append(']');
            walls.append(']');"""

APPEND_OLD = """    private static String metaLine() {"""

APPEND_NEW = """    /** RLE 的一段。name 为 null 表示「这一段的格子上什么都没有」。 */
    private static void appendRun(StringBuilder sb, String name, int run) {
        if (sb.charAt(sb.length() - 1) != '[') sb.append(',');
        if (name == null) sb.append("null");
        else sb.append(Json.str(name));
        sb.append(',').append(run);
    }

    private static String metaLine() {"""

RULES = [
    (OLD, NEW, "更新注释说明实测数字"),
    (BODY_OLD, BODY_NEW, "ores/walls 改 RLE"),
    (APPEND_OLD, APPEND_NEW, "加 appendRun()"),
]


def main():
    text = R.read_text(encoding="utf-8")
    bad = []
    for old, new, label in RULES:
        n = text.count(old)
        if n != 1:
            bad.append(f"{n} 次命中: {label}")
            print(f"  !! {n} 次  {label}")
            continue
        text = text.replace(old, new)
        print(f"  1 处  {label}")
    if bad:
        print("\n有问题，未写盘")
        return 1
    R.write_text(text, encoding="utf-8")
    print("\nRecorder.java：mapData 三样都改成 RLE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
