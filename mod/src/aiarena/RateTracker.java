package aiarena;

import mindustry.Vars;
import mindustry.game.Team;
import mindustry.gen.Building;
import mindustry.type.Item;

import java.util.HashMap;
import java.util.Map;

/**
 * 物品速率追踪器。
 *
 * 解决的问题：光看某一刻的库存，分不清「这条产线在产还是在堵」。
 * 之前诊断煤线只能每隔 20 秒拍一次快照、人眼比对数字，既慢又容易看错 ——
 * 而且完全看不出「煤在传送带上堆着」和「煤已经被消耗掉」的区别。
 *
 * 这里按 tick 采样两类总量，用滑动窗口算变化率：
 *
 *   core   该队**核心**里的物品（= 净产出，产多少减消耗多少）
 *   stored 该队**所有建筑**里的物品总量（含传送带在途）
 *
 * 两者对照着看就能定位瓶颈：
 *   core 不涨 + stored 涨  -> 东西都堵在产线里，没送到核心
 *   core 涨   + stored 平  -> 健康
 *   两者都不涨              -> 上游没在挖（矿机空转 / 没料 / 没电）
 *
 * 采样在主线程做（要读 Groups），读取走快照，不跨线程碰世界。
 */
public final class RateTracker {

    /** 采样间隔（tick）。5 tick ≈ 12 次/秒，够精度又不费。 */
    private static final int SAMPLE_INTERVAL = 5;

    /** 环形缓冲容量。12 次/秒 × 120 秒 = 1440，留足长窗口。 */
    private static final int CAPACITY = 1440;

    /** 物品索引上限（Vars.content.items() 的数量远小于这个）。 */
    private static final int MAX_ITEMS = 256;

    private static final class Sample {
        long tick;
        long millis;
        /** [teamId][itemId] -> 核心库存 */
        final Map<Integer, int[]> core = new HashMap<>();
        /** [teamId][itemId] -> 全部建筑库存 */
        final Map<Integer, int[]> stored = new HashMap<>();
    }

    private static final Sample[] ring = new Sample[CAPACITY];
    private static int head = 0;
    private static int count = 0;
    private static long lastSampleTick = -1;

    private RateTracker() {}

    /** 由主线程每帧调用，内部自己限流。 */
    public static void update() {
        try {
            if (Vars.state == null || !Vars.state.isGame()) return;
            long tick = (long) Vars.state.tick;
            if (lastSampleTick >= 0 && tick - lastSampleTick < SAMPLE_INTERVAL) return;
            lastSampleTick = tick;

            int itemCount = Vars.content.items().size;
            if (itemCount > MAX_ITEMS) itemCount = MAX_ITEMS;

            Sample s = new Sample();
            s.tick = tick;
            s.millis = System.currentTimeMillis();

            for (var td : Vars.state.teams.present) {
                Team team = td.team;
                if (team == null || team == Team.derelict) continue;

                int[] coreArr = new int[itemCount];
                int[] storedArr = new int[itemCount];

                // 核心库存
                for (int i = 0; i < itemCount; i++) {
                    Item it = Vars.content.items().get(i);
                    int amt = 0;
                    for (var core : td.cores) {
                        if (core != null && core.items != null) amt += core.items.get(it);
                    }
                    coreArr[i] = amt;
                    storedArr[i] = amt;
                }
                // 其余建筑（含传送带在途）
                for (Building b : td.buildings) {
                    if (b == null || b.items == null) continue;
                    if (b.block != null && b.block.name != null && b.block.name.startsWith("core-")) continue;
                    for (int i = 0; i < itemCount; i++) {
                        Item it = Vars.content.items().get(i);
                        int amt = b.items.get(it);
                        if (amt > 0) storedArr[i] += amt;
                    }
                }

                s.core.put(team.id, coreArr);
                s.stored.put(team.id, storedArr);
            }

            ring[head] = s;
            head = (head + 1) % CAPACITY;
            if (count < CAPACITY) count++;

        } catch (Throwable t) {
            arc.util.Log.err("rate tracker failed: " + t);
        }
    }

    /** 换图 / 重开时清空。 */
    public static void clear() {
        for (int i = 0; i < CAPACITY; i++) ring[i] = null;
        head = 0;
        count = 0;
        lastSampleTick = -1;
    }

    public static int sampleCount() { return count; }

    /**
     * 算某个队伍在窗口内的物品变化率。
     *
     * @param windowSeconds 窗口长度（秒）
     * @return JSON 字符串
     */
    public static String ratesJson(Team team, double windowSeconds) {
        if (team == null || count == 0) {
            return "{\"error\":\"no samples yet\"}";
        }

        long nowTick = (long) Vars.state.tick;
        long fromTick = nowTick - (long) (windowSeconds * 60.0);

        // 找窗口起点：最接近 fromTick 的那条样本
        Sample newest = null, oldest = null;
        for (int i = 0; i < count; i++) {
            int idx = ((head - 1 - i) % CAPACITY + CAPACITY) % CAPACITY;
            Sample s = ring[idx];
            if (s == null) continue;
            if (newest == null) newest = s;
            if (s.tick >= fromTick) { oldest = s; }
        }
        if (newest == null || oldest == null) oldest = newest;
        if (newest == oldest) {
            return "{\"error\":\"window too short, only one sample\",\"samples\":" + count + "}";
        }

        int[] a = oldest.core.get(team.id);
        int[] b = newest.core.get(team.id);
        int[] sa = oldest.stored.get(team.id);
        int[] sb = newest.stored.get(team.id);
        if (a == null || b == null) {
            return "{\"error\":\"no data for team " + team.name + "\"}";
        }

        double seconds = Math.max(0.001, (newest.tick - oldest.tick) / 60.0);

        StringBuilder core = new StringBuilder("{");
        StringBuilder stored = new StringBuilder("{");
        boolean cf = true, sf = true;
        int itemCount = Math.min(a.length, Vars.content.items().size);

        for (int i = 0; i < itemCount; i++) {
            Item it = Vars.content.items().get(i);
            int d1 = b[i] - a[i];
            int d2 = (sb != null && sa != null && i < sb.length) ? (sb[i] - sa[i]) : 0;

            if (d1 != 0) {
                if (!cf) core.append(',');
                cf = false;
                core.append(Json.str(it.name)).append(':')
                    .append(new Json.Obj()
                        .put("start", a[i]).put("end", b[i])
                        .put("delta", d1)
                        .put("perSecond", (float)(Math.round(d1 / seconds * 100.0) / 100.0))
                        .toString());
            }
            if (d2 != 0 || (sa != null && i < sa.length && (sa[i] > 0 || (sb != null && i < sb.length && sb[i] > 0)))) {
                if (!sf) stored.append(',');
                sf = false;
                stored.append(Json.str(it.name)).append(':')
                    .append(new Json.Obj()
                        .put("start", sa != null && i < sa.length ? sa[i] : 0)
                        .put("end", sb != null && i < sb.length ? sb[i] : 0)
                        .put("delta", d2)
                        .put("perSecond", (float)(Math.round(d2 / seconds * 100.0) / 100.0))
                        .toString());
            }
        }
        core.append('}');
        stored.append('}');

        return new Json.Obj()
            .put("team", team.name)
            .put("windowSeconds", (float)(Math.round(seconds * 100.0) / 100.0))
            .put("fromTick", oldest.tick)
            .put("toTick", newest.tick)
            .put("sampleCount", count)
            .putRaw("core", core.toString())
            .putRaw("stored", stored.toString())
            .toString();
    }
}
