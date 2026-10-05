package aiarena;

import arc.Core;
import arc.files.Fi;
import arc.struct.Seq;
import arc.util.Log;
import mindustry.Vars;
import mindustry.game.Team;

import java.io.BufferedWriter;
import java.io.OutputStreamWriter;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;

/**
 * 录像器（DESIGN.md P6）。
 *
 * 格式：JSON Lines（每行一条独立记录）。
 *
 * 为什么用 JSONL 而不是自定义二进制：
 *   - 流式追加写，崩溃时已写部分仍可解析
 *   - 客户端可以用「与实时同一套解析器」逐行读，不需要两套代码
 *   - 可读、可 grep、可用任何工具处理
 *   代价是体积偏大，但对一局几分钟的对战可接受。
 *
 * 记录类型：
 *   {"t":"meta", ...}    开局元数据：地图名/尺寸/队伍/规则 + **mapData（整张地图）**
 *   {"t":"snap", ...}    周期快照：units 全量、builds 增量、removed 本帧消失的方块
 *   {"t":"ev", ...}      事件（来自 EventLog）
 *   {"t":"end", ...}     结束标记
 *
 * 快照三条流的语义**不同**，别混：
 *   units    每帧全量 —— 单位少（几十个），全量比增量简单且不会漏
 *   builds   增量 —— 首次全量，之后只写「新增或变化的」
 *   removed  增量 —— 本帧消失的方块坐标。**必须单独报**：
 *            builds 只写出现的，拆掉的方块从集合里消失后不会出现在任何记录里，
 *            回放端会一直画着它
 *
 * mapData 也用一维 RLE（行优先展开，[名称, 段长, ...]，null 表示该段什么都没有）。
 * 实测 veins 图 350x200 = 70000 格：逐格写是 1.38 MB，RLE 后约 230 KB ——
 * 而整局录像才 300 KB，所以这一步不是可选的优化，是不做就没法用。
 * 地板细碎（11643 段），矿脉和岩壁成片（分别 2974 / 6770 段）。
 *
 * 线程约定：主线程写。文件 IO 在写入线程上同步做，但因为每条记录都很小、
 * 且快照间隔是秒级，不会影响 tick。
 */
public final class Recorder {

    /** 快照间隔（tick）。60 tick ≈ 1 秒。 */
    public static final int SNAPSHOT_INTERVAL = 60;

    private static BufferedWriter writer;
    private static Fi currentFile;
    private static boolean recording = false;
    private static int lastSnapshotTick = -1;
    private static int snapshotCount = 0;
    private static long bytesWritten = 0;
    private static int lastEventSeq = 0;

    /** 已记录过的方块（key = x*100000+y），用于只写增量。 */
    private static final arc.struct.IntSet knownBuilds = new arc.struct.IntSet();
    private static boolean buildsPrimed = false;

    private Recorder() {}

    // ---------------------------------------------------------------- control

    public static boolean isRecording() { return recording; }

    public static String status() {
        if (!recording) return "not recording";
        return "recording to " + (currentFile == null ? "?" : currentFile.name())
             + " snapshots=" + snapshotCount
             + " bytes=" + bytesWritten;
    }

    /** 开始录制。返回文件名。 */
    public static String start(String label) {
        stop();
        try {
            Fi dir = Core.settings.getDataDirectory().child("ai-arena-recordings");
            dir.mkdirs();

            String stamp = new java.text.SimpleDateFormat("yyyyMMdd-HHmmss").format(new java.util.Date());
            String safeLabel = (label == null || label.isEmpty()) ? "match" : label.replaceAll("[^a-zA-Z0-9_-]", "_");
            currentFile = dir.child(stamp + "-" + safeLabel + ".jsonl");

            writer = new BufferedWriter(new OutputStreamWriter(
                new FileOutputStream(currentFile.file(), false), StandardCharsets.UTF_8));

            recording = true;
            snapshotCount = 0;
            bytesWritten = 0;
            lastSnapshotTick = -1;
            lastEventSeq = (int) EventLog.lastSeq();
            knownBuilds.clear();
            buildsPrimed = false;

            writeLine(metaLine());
            AIArena.log("recording started: " + currentFile.absolutePath());
            return currentFile.name();
        } catch (Throwable t) {
            AIArena.log("recording failed to start: " + t);
            recording = false;
            return null;
        }
    }

    public static void stop() {
        if (!recording) return;
        try {
            writeLine(new Json.Obj()
                .put("t", "end")
                .put("tick", (int) Vars.state.tick)
                .put("snapshots", snapshotCount)
                .toString());
            writer.flush();
            writer.close();
        } catch (Throwable t) {
            Log.err("recorder stop failed", t);
        }
        AIArena.log("recording stopped: " + (currentFile == null ? "?" : currentFile.name())
                    + " snapshots=" + snapshotCount + " bytes=" + bytesWritten);
        recording = false;
        writer = null;
    }

    // ---------------------------------------------------------------- write

    /** 由主线程每帧调用。 */
    public static void update() {
        if (!recording) return;
        try {
            int tick = (int) Vars.state.tick;

            // tick 回退说明换图了，重开一份元数据
            if (tick < lastSnapshotTick) {
                writeLine(metaLine());
                knownBuilds.clear();
                buildsPrimed = false;
                lastSnapshotTick = -1;
            }

            if (lastSnapshotTick < 0 || tick - lastSnapshotTick >= SNAPSHOT_INTERVAL) {
                lastSnapshotTick = tick;
                writeSnapshot(tick);
            }

            drainEvents();
        } catch (Throwable t) {
            Log.err("recorder update failed", t);
        }
    }

    private static void writeSnapshot(int tick) {
        Snapshot.State s = Snapshot.get();

        // 单位：全量
        StringBuilder units = new StringBuilder("[");
        boolean uf = true;
        for (Snapshot.UnitInfo u : s.units) {
            if (!uf) units.append(',');
            uf = false;
            units.append(new Json.Obj()
                .put("id", u.id).put("type", u.type).put("team", u.team)
                .put("x", u.x).put("y", u.y)
                .put("health", u.health).put("rot", u.rotation).toString());
        }
        units.append(']');

        // 方块：首次全量，之后只写增量
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
        snapshotCount++;
    }

    private static void drainEvents() {
        long last = EventLog.lastSeq();
        if (last <= lastEventSeq) return;

        var evs = EventLog.since(lastEventSeq, 256, null);   // 录制不按视野过滤
        for (var ev : evs) {
            writeLine(new Json.Obj()
                .put("t", "ev")
                .put("seq", ev.seq).put("tick", ev.tick).put("type", ev.type)
                .put("team", ev.teamId)
                .putRaw("detail", ev.detail == null || ev.detail.isEmpty() ? "{}" : "{" + ev.detail + "}")
                .toString());
            lastEventSeq = (int) ev.seq;
        }
    }

    /**
     * 地图的静态部分 —— 录像里原本完全没有它，回放端只能画一片黑底上的点。
     *
     * 70000 格逐个存会爆 —— 实测全图 walls 44658 格（占 64%）、ores 4994 格，
     * 逐格写成 JSON 是 1.38 MB，而整局录像才 1.24 MB。地图比录像还大，本末倒置。
     *
     * 三样都用一维 RLE（行优先展开）：[名称, 段长, 名称, 段长, ...]
     * 岩壁和矿脉都是成片的，RLE 之后通常只剩几百段。
     * 无矿 / 无墙的段用 null 占位。
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
            walls.append(']');

            // 诊断：三样各多少段、矿样本长什么样
            AIArena.log("mapData: floors=" + (countRuns(floors) / 2)
                + " ores=" + (countRuns(ores) / 2)
                + " walls=" + (countRuns(walls) / 2)
                + " oreSample=" + firstNonNullName(ores));

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

    /** 数一数字符串里有多少个元素（逗号分隔，用于诊断）。 */
    private static int countRuns(StringBuilder sb) {
        int n = 0;
        for (int i = 0; i < sb.length(); i++) {
            if (sb.charAt(i) == ',') n++;
        }
        return n + 1;
    }

    /** 取 RLE 里第一个非 null 的名称，用于诊断。 */
    private static String firstNonNullName(StringBuilder sb) {
        String s = sb.toString();
        int i = 0, n = 0;
        while (true) {
            int comma = s.indexOf(',', i);
            if (comma < 0) return "(none)";
            String tok = s.substring(i, comma).trim();
            if (!tok.equals("null") && tok.length() > 2) return tok;
            i = s.indexOf(',', comma + 1);
            if (i < 0) return "(none)";
            i++;
            if (++n > 20000) return "(none)";
        }
    }

    /** RLE 的一段。name 为 null 表示「这一段的格子上什么都没有」。 */
    private static void appendRun(StringBuilder sb, String name, int run) {
        if (sb.charAt(sb.length() - 1) != '[') sb.append(',');
        if (name == null) sb.append("null");
        else sb.append(Json.str(name));
        sb.append(',').append(run);
    }

    private static String metaLine() {
        StringBuilder teams = new StringBuilder("[");
        boolean first = true;
        for (var td : Vars.state.teams.present) {
            if (!first) teams.append(',');
            first = false;
            teams.append(new Json.Obj()
                .put("id", td.team.id).put("name", td.team.name)
                .put("cores", td.cores.size).toString());
        }
        teams.append(']');

        var m = Vars.state.map;
        return new Json.Obj()
            .put("t", "meta")
            .put("version", 2)
            // 接口版本：跨版本的成绩不可比，成绩与录像必须带得上它。
            // 见 docs/API.md「接口版本号」与 docs/DEVELOPING.md「溯源命名」。
            .put("apiVersion", AIArena.API_VERSION)
            .putRaw("mapData", mapDataJson())
            .put("map", m == null ? "?" : m.name())
            .put("mapCustom", m != null && m.custom)
            .put("w", Vars.world.width()).put("h", Vars.world.height())
            .put("tick", (int) Vars.state.tick)
            .put("pvp", Vars.state.rules.pvp)
            .put("fog", Vars.state.rules.fog)
            .put("snapshotInterval", SNAPSHOT_INTERVAL)
            .putRaw("teams", teams.toString())
            .toString();
    }

    private static void writeLine(String line) {
        if (writer == null) return;
        try {
            writer.write(line);
            writer.write('\n');
            bytesWritten += line.length() + 1;
            // 每条都快刷，保证崩溃时数据可用
            writer.flush();
        } catch (Throwable t) {
            Log.err("recorder write failed", t);
            recording = false;
        }
    }

    // ---------------------------------------------------------------- read

    /** 列出已有录像文件。 */
    public static String listFiles() {
        Fi dir = Core.settings.getDataDirectory().child("ai-arena-recordings");
        if (!dir.exists()) return "[]";
        Fi[] files = dir.list();
        java.util.Arrays.sort(files, (a, b) -> Long.compare(b.lastModified(), a.lastModified()));

        StringBuilder sb = new StringBuilder("[");
        boolean first = true;
        for (Fi f : files) {
            if (!f.name().endsWith(".jsonl")) continue;
            if (!first) sb.append(',');
            first = false;
            sb.append(new Json.Obj()
                .put("name", f.name())
                .put("bytes", f.length())
                .put("modified", f.lastModified()).toString());
        }
        return sb.append(']').toString();
    }
}
