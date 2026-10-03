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
 *   {"t":"meta", ...}                                    开局元数据（地图/尺寸/队伍/规则）
 *   {"t":"snap","tick":N,"units":[...],"builds":[...]}   周期快照（单位全量 + 方块增量）
 *   {"t":"ev", ...}                                      事件（来自 EventLog）
 *   {"t":"end", ...}                                     结束标记
 *
 * 方块只存增量（首次全量 + 后续变化），因为地图上多数方块长期不变。
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
            .put("version", 1)
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
