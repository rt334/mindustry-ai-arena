package aiarena;

import arc.Events;
import arc.struct.Seq;
import arc.util.Log;
import mindustry.Vars;
import mindustry.game.EventType.*;
import mindustry.game.Team;
import mindustry.gen.Building;
import mindustry.gen.Unit;

/**
 * 事件流（DESIGN.md 6.3）。
 *
 *   状态变更 ──→ 事件流 ──┬──→ /events 轮询给 AI
 *                        └──→ Recorder 写文件（录像，P6）
 *
 * 同一份数据、同一个格式 —— 回放不需要单独的解析器。
 *
 * 视野约束：每个事件都带位置与相关队伍，读取时按观察方过滤。
 * 玩家只能看到自己视野内发生的事，AI 也一样。
 *
 * ⚠ 引擎警告：TileChangeEvent / TilePreChangeEvent / BuildDamageEvent 的实例是**复用的**，
 * 监听器里必须立即把字段抄出来，绝不能缓存事件对象本身。本类在 handle() 里一次性
 * 提取全部所需字段，不保留任何引擎对象引用。
 */
public final class EventLog {

    /** 环形缓冲容量。约等于 3～5 分钟的对局事件量。 */
    /**
     * 环形缓冲容量。
     *
     * 可被 -Darena.eventlog.capacity=N 覆盖 —— 只为**测试游标过期契约**用：
     * cursorExpired 判定要等缓冲绕一圈（firstSeq 前进）才会成立，而攒满 4096 条
     * 事件要十几分钟的正常游玩。用小容量复现同一条判定，与契约本身无关。
     * 生产一律用默认值。
     */
    private static final int CAPACITY =
        Math.max(2, Integer.getInteger("arena.eventlog.capacity", 4096));

    public static final class Ev {
        public final long seq;
        public final long tick;
        public final String type;
        /** 事件相关队伍；-1 表示与队伍无关（如地图事件）。 */
        public final int teamId;
        /** 事件发生位置（世界坐标）；NaN 表示无位置。 */
        public final float x, y;
        /** 预序列化的细节字段（不含外层花括号）。 */
        public final String detail;

        Ev(long seq, long tick, String type, int teamId, float x, float y, String detail) {
            this.seq = seq;
            this.tick = tick;
            this.type = type;
            this.teamId = teamId;
            this.x = x;
            this.y = y;
            this.detail = detail;
        }

        public String toJson() {
            Json.Obj o = new Json.Obj()
                .put("seq", seq).put("tick", tick).put("type", type);
            if (teamId >= 0) o.put("team", teamId);
            if (!Float.isNaN(x)) o.put("x", x).put("y", y);
            if (detail != null && !detail.isEmpty()) o.putRaw("detail", "{" + detail + "}");
            return o.toString();
        }
    }

    private static final Ev[] ring = new Ev[CAPACITY];
    private static long nextSeq = 1;
    private static long firstSeq = 1;      // 缓冲区中最旧的序号
    private static final Object lock = new Object();

    private static boolean installed = false;

    private EventLog() {}

    // ---------------------------------------------------------------- install

    /** 挂载引擎事件监听器。Mod 初始化时调用一次。 */
    public static void install() {
        if (installed) return;
        installed = true;

        Events.on(UnitCreateEvent.class, e -> {
            Unit u = e.unit;
            if (u == null) return;
            add("unitCreate", u.team == null ? -1 : u.team.id, u.x, u.y,
                new Json.Obj().put("unit", u.id).put("type", u.type == null ? "?" : u.type.name)
                              .put("health", u.health).toString().replaceAll("^\\{|\\}$", ""));
        });

        Events.on(UnitDestroyEvent.class, e -> {
            Unit u = e.unit;
            if (u == null) return;
            // unit 在事件之后可能被回收，字段必须现在抄走
            add("unitDestroy", u.team == null ? -1 : u.team.id, u.x, u.y,
                new Json.Obj().put("unit", u.id).put("type", u.type == null ? "?" : u.type.name)
                              .toString().replaceAll("^\\{|\\}$", ""));
        });

        Events.on(BlockBuildEndEvent.class, e -> {
            if (e.tile == null) return;
            add(e.breaking ? "blockBreak" : "blockPlace",
                e.team == null ? -1 : e.team.id,
                e.tile.worldx(), e.tile.worldy(),
                new Json.Obj()
                    .put("x", e.tile.x).put("y", e.tile.y)
                    .put("block", e.tile.block() == null ? "?" : e.tile.block().name)
                    .put("byUnit", e.unit == null ? -1 : e.unit.id)
                    .put("hasConfig", e.config != null)
                    .toString().replaceAll("^\\{|\\}$", ""));
        });

        Events.on(BlockDestroyEvent.class, e -> {
            if (e.tile == null) return;
            var t = e.tile;
            add("blockDestroy", t.team() == null ? -1 : t.team().id, t.worldx(), t.worldy(),
                new Json.Obj().put("x", t.x).put("y", t.y)
                              .put("block", t.block() == null ? "?" : t.block().name)
                              .toString().replaceAll("^\\{|\\}$", ""));
        });

        Events.on(ConfigEvent.class, e -> {
            if (e.tile == null) return;
            add("configure", e.tile.team == null ? -1 : e.tile.team.id, e.tile.x, e.tile.y,
                new Json.Obj().put("block", e.tile.block == null ? "?" : e.tile.block.name)
                              .put("value", String.valueOf(e.value))
                              .toString().replaceAll("^\\{|\\}$", ""));
        });

        Events.on(CoreChangeEvent.class, e -> {
            if (e.core == null) return;
            add("coreChange", e.core.team == null ? -1 : e.core.team.id, e.core.x, e.core.y,
                new Json.Obj().put("block", e.core.block == null ? "?" : e.core.block.name)
                              .toString().replaceAll("^\\{|\\}$", ""));
            // 核心易主 → 该队的 intel 视为全新
            Intel.clearTeam(e.core.team == null ? -1 : e.core.team.id);
        });

        Events.on(WaveEvent.class, e ->
            add("wave", -1, Float.NaN, Float.NaN,
                new Json.Obj().put("wave", Vars.state.wave).toString().replaceAll("^\\{|\\}$", "")));

        Events.on(GameOverEvent.class, e ->
            add("gameOver", e.winner == null ? -1 : e.winner.id, Float.NaN, Float.NaN,
                new Json.Obj().put("winner", e.winner == null ? "?" : e.winner.name)
                              .toString().replaceAll("^\\{|\\}$", "")));

        Events.on(WorldLoadEvent.class, e -> clear());

        AIArena.log("event log installed");
    }

    // ---------------------------------------------------------------- write

    static void add(String type, int teamId, float x, float y, String detail) {
        try {
            synchronized (lock) {
                long seq = nextSeq++;
                ring[(int) (seq % CAPACITY)] = new Ev(seq, (long) Vars.state.tick, type, teamId, x, y, detail);
                if (seq - firstSeq >= CAPACITY) firstSeq = seq - CAPACITY + 1;
            }
        } catch (Throwable t) {
            Log.err("event log add failed", t);
        }
    }

    /**
     * 供快照差分补事件用。
     *
     * 与 add() 的唯一区别是可见性：引擎事件的 teamId 表示「谁做的」，
     * 而差分事件的 teamId 表示「这属于谁」—— 对 unitAppear / buildAppear 来说，
     * 前者更合适（否则会被当成"敌方看不见"而漏报）。
     */
    static void addExternal(String type, int teamId, float x, float y, String detail) {
        add(type, teamId, x, y, detail);
    }

    public static void clear() {
        synchronized (lock) {
            java.util.Arrays.fill(ring, null);
            nextSeq = 1;
            firstSeq = 1;
        }
        Snapshot.resetDiff();
    }

    // ---------------------------------------------------------------- read

    /**
     * 游标是否已过期（请求的事件已被环形缓冲淘汰）。
     * 过期时调用方应重置 since=0 重新同步。
     */
    public static boolean cursorExpired(long since) {
        if (since <= 0) return false;
        synchronized (lock) { return since < firstSeq - 1; }
    }

    /**
     * 取指定序号之后的事件，按观察方视野过滤。
     *
     * @param since  起始序号（不含）。传 0 表示从头。
     * @param limit  最多返回条数
     * @param viewer 观察方队伍，null 表示不过滤（裁判）
     */
    public static Seq<Ev> since(long since, int limit, Team viewer) {
        Seq<Ev> out = new Seq<>();
        synchronized (lock) {
            if (cursorExpired(since)) return out;
            long start = Math.max(since + 1, firstSeq);
            for (long s = start; s < nextSeq && out.size < limit; s++) {
                Ev ev = ring[(int) (s % CAPACITY)];
                if (ev == null) continue;
                if (!visible(ev, viewer)) continue;
                out.add(ev);
            }
        }
        return out;
    }

    /** 事件是否对观察方可见。 */
    private static boolean visible(Ev ev, Team viewer) {
        if (viewer == null) return true;                    // 裁判：全见

        // 视野事件是**私有**的：只给产生它的那一队。
        //
        // ⚠ 不能走下面的「位置在我视野内就可见」规则。实测：
        // 102/103 队的核心看见了 sharded 的 gamma，于是产生 unitSpotted
        // （teamId=102），而那个位置正好在 sharded 自己基地里 ——
        // 按位置规则就泄漏给了 sharded。结果 sharded 会看到一串
        // 「有人看见了我的单位」，而「谁在看我」这件事本身是对手的情报。
        //
        // 视野进出天然是一队的私有状态，不是世界里发生的公开事件。
        if (isVisionEvent(ev.type)) {
            return ev.teamId == viewer.id;
        }

        if (ev.teamId == viewer.id) return true;            // 自己的事总是知道
        if (!Vars.state.rules.fog) return true;             // 无迷雾
        if (Float.isNaN(ev.x)) return false;                // 无位置且非己方 → 不透露
        return Vars.fogControl.isVisible(viewer, ev.x, ev.y);
    }

    private static boolean isVisionEvent(String type) {
        return type.endsWith("Spotted") || type.endsWith("Lost");
    }

    /** 当前最新序号。 */
    /** 最近 n 条事件的 JSON 数组。供 WebSocket 的 events 频道使用。 */
    public static String recentJson(int n) {
        StringBuilder sb = new StringBuilder("[");
        boolean first = true;
        synchronized (lock) {
            long from = Math.max(firstSeq, nextSeq - n);
            for (long s = from; s < nextSeq; s++) {
                Ev e = ring[(int) (s % CAPACITY)];
                if (e == null) continue;
                if (!first) sb.append(',');
                first = false;
                sb.append(e.toJson());
            }
        }
        return sb.append(']').toString();
    }

    public static long lastSeq() {
        synchronized (lock) { return nextSeq - 1; }
    }

    public static int size() {
        synchronized (lock) { return (int) Math.min(nextSeq - firstSeq, CAPACITY); }
    }
}
