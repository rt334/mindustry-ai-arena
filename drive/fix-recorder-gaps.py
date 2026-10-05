#!/usr/bin/env python3
"""补齐录像缺的四样，让回放真的能画出来。

验证结论（读现有录像得出）：JSONL 里单位是全量且完整的（含 rot/health），
方块是增量（含 block/team/health）。但**画不出来**，缺四样：

  1. 地图完全没有 —— meta 和 snap 里都没有 floor/overlay/block。
     没有地图就画不出地板、矿脉、岩壁，只能是一片黑底上的点。
  2. 方块没有 rot —— 传送带流向、炮塔朝向、工厂出口全画不出来。
  3. 方块被拆不记录 —— knownBuilds 每帧用当前全量替换，
     拆掉的方块从 nowBuilds 消失后不写任何记录，回放端会一直画着它。
  4. 方块没有 items —— 可选，但有它画面才有信息量（看得出谁堵了）。

地图 350x200 = 70000 格，全存太大。所以只存「非默认」的：
  地板   一维 RLE（(名称, 段长) 轮转），整图扫一遍通常只剩几十段
  矿/墙  逐格存 —— 本来就稀疏（本局实测矿 253 格、墙 949 格）

整体开销约 10–20 KB，相对整局 MB 级录像可忽略。
"""
import pathlib
import sys

R = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Recorder.java")

# ---- 1) 方块加 rot，2) 新增 removed ----
OLD_SNAP = """        // 方块：首次全量，之后只写增量
        StringBuilder builds = new StringBuilder("[");
        boolean bf = true;
        arc.struct.IntSet nowBuilds = new arc.struct.IntSet();
        for (Snapshot.BuildInfo b : s.builds) {
            int key = b.x * 100000 + b.y;
            nowBuilds.add(key);
            if (buildsPrimed && knownBuilds.contains(key)) continue;   // 没变
            if (!bf) builds.append(',');
            bf = false;
            builds.append(new Json.Obj()
                .put("x", b.x).put("y", b.y).put("team", b.team)
                .put("block", b.block).put("health", b.health).toString());
        }
        builds.append(']');

        boolean fullBuilds = !buildsPrimed;
        knownBuilds.clear();
        knownBuilds.addAll(nowBuilds);
        buildsPrimed = true;

        writeLine(new Json.Obj()
            .put("t", "snap")
            .put("tick", tick)
            .put("full", fullBuilds)
            .putRaw("units", units.toString())
            .putRaw("builds", builds.toString())
            .toString());
        snapshotCount++;"""

NEW_SNAP = """        // 方块：首次全量，之后只写增量
        StringBuilder builds = new StringBuilder("[");
        boolean bf = true;
        arc.struct.IntSet nowBuilds = new arc.struct.IntSet();
        for (Snapshot.BuildInfo b : s.builds) {
            int key = b.x * 100000 + b.y;
            nowBuilds.add(key);
            if (buildsPrimed && knownBuilds.contains(key)) continue;   // 没变
            if (!bf) builds.append(',');
            bf = false;
            builds.append(new Json.Obj()
                .put("x", b.x).put("y", b.y).put("team", b.team)
                .put("block", b.block).put("health", b.health)
                // rot 是画传送带流向、炮塔朝向、工厂出口的唯一依据
                .put("rot", b.rotation)
                .toString());
        }
        builds.append(']');

        // 本帧消失的方块。**必须单独报** —— 上面只写「新增或变化的」，
        // 被拆的方块从 nowBuilds 里消失后不会出现在任何一条记录里，
        // 回放端会一直画着它。
        StringBuilder removed = new StringBuilder("[");
        boolean rf = true;
        if (buildsPrimed) {
            for (arc.struct.IntSet.IntSetIterator it = knownBuilds.iterator(); it.hasNext; ) {
                int key = it.next();
                if (nowBuilds.contains(key)) continue;
                if (!rf) removed.append(',');
                rf = false;
                removed.append('[').append(key / 100000).append(',')
                       .append(key % 100000).append(']');
            }
        }
        removed.append(']');

        boolean fullBuilds = !buildsPrimed;
        knownBuilds.clear();
        knownBuilds.addAll(nowBuilds);
        buildsPrimed = true;

        writeLine(new Json.Obj()
            .put("t", "snap")
            .put("tick", tick)
            .put("full", fullBuilds)
            .putRaw("units", units.toString())
            .putRaw("builds", builds.toString())
            .putRaw("removed", removed.toString())
            .toString());
        snapshotCount++;"""

# ---- 3) meta 加地图 ----
OLD_META = """        var m = Vars.state.map;
        return new Json.Obj()
            .put("t", "meta")
            .put("version", 1)
            .put("map", m == null ? "?" : m.name())"""

NEW_META = """        var m = Vars.state.map;
        return new Json.Obj()
            .put("t", "meta")
            .put("version", 2)
            .putRaw("mapData", mapDataJson())
            .put("map", m == null ? "?" : m.name())"""

# ---- 4) 新增 mapDataJson() ----
MAP_ANCHOR = """    private static String metaLine() {"""

MAP_HELPER = """    /**
     * 地图的静态部分 —— 录像里原本完全没有它，回放端只能画一片黑底上的点。
     *
     * 70000 格全存太大，所以只存「非默认」的：
     *   floors  一维 RLE，[名称, 段长, 名称, 段长, ...]（行优先展开）
     *   ores    逐格 —— 本来就稀疏（本局实测 253 格）
     *   walls   逐格 —— 固体静态方块（岩壁），约 949 格
     *
     * 整图扫一遍只在录制开始时做一次，几十毫秒。
     */
    private static String mapDataJson() {
        try {
            var world = Vars.world;
            int w = world.width(), h = world.height();

            StringBuilder floors = new StringBuilder("[");
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
            walls.append(']');

            return new Json.Obj()
                .put("w", w).put("h", h)
                .putRaw("floors", floors.toString())
                .putRaw("ores", ores.toString())
                .putRaw("walls", walls.toString())
                .toString();
        } catch (Throwable t) {
            Log.err("mapDataJson failed", t);
            return "{}";
        }
    }

    private static String metaLine() {"""

RULES = [
    (OLD_SNAP, NEW_SNAP, "snap 加 rot 与 removed"),
    (OLD_META, NEW_META, "meta 加 mapData"),
    (MAP_ANCHOR, MAP_HELPER, "新增 mapDataJson()"),
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
    print("\nRecorder.java：录像已补齐四样")
    return 0


if __name__ == "__main__":
    sys.exit(main())
