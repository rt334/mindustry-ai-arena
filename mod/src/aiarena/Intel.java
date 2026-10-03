package aiarena;

import arc.struct.Seq;
import mindustry.Vars;
import mindustry.game.Team;
import mindustry.gen.Building;
import mindustry.world.blocks.storage.CoreBlock.CoreBuild;

/**
 * 「确认核心数据」状态机（DESIGN.md 6.2）。
 *
 * 核心库存是原版对所有人公开的信息（NetServer.writeStateSnapshot 会把每个队的
 * 核心库存广播给所有客户端），所以这里不是「隐藏」而是「要求确认」：
 *
 *   unknown ──[连续可见 600 tick]──→ confirmed
 *                                       └─ 保存快照 {items, tick}，永久保留
 *                                          再次确认 → 追加（保留历史）
 *
 * 参数：
 *   - 确认时长 600 tick（10 秒）—— 接近「一次成功的穿插」，而非「驻扎」
 *   - 抖动容错 30 tick（0.5 秒）—— 视野边缘每 tick 重算会出现瞬时丢失，
 *     一次瞬时丢失就清零会让机制几乎无法完成
 *   - 无加速 —— 多个单位观察同一核心不加速
 *   - 己方核心全知 —— 不走确认流程
 *
 * 「察觉」不需要额外机制：防守方能看见敌方单位，这就是察觉。
 * 加一个「你正在被侦察」的提示反而是额外免费情报，违背对等原则。
 *
 * 线程约定：update() 在主线程每 tick 调用；读方法可从 HTTP 线程调用，
 * 因为写入方只增不改已有快照对象。
 */
public final class Intel {

    /** 连续可见达到此 tick 数即确认。 */
    public static final int CONFIRM_TICKS = 600;

    /** 视野丢失的容错窗口。 */
    public static final int CLEAR_TOLERANCE_TICKS = 30;

    /** 一条已确认的库存快照。 */
    public static final class Snap {
        public final long tick;
        public final String[] itemNames;
        public final int[] amounts;
        public final int total;

        Snap(long tick, String[] itemNames, int[] amounts, int total) {
            this.tick = tick;
            this.itemNames = itemNames;
            this.amounts = amounts;
            this.total = total;
        }
    }

    /** 单个（观察方队伍 → 目标核心队伍）的侦察状态。 */
    public static final class State {
        public volatile int visibleTicks;
        public volatile int clearTicks;
        public volatile boolean confirmed;
        public volatile long lastSeenTick;
        public volatile long confirmedAt;

        /** 已确认的历史快照。保留历史而非覆盖 —— 两次读数的差额直接给出经济增长。 */
        public final Seq<Snap> snapshots = new Seq<>();

        public float progress() {
            return Math.min(1f, visibleTicks / (float) CONFIRM_TICKS);
        }
    }

    private static final java.util.Map<Long, State> states = new java.util.concurrent.ConcurrentHashMap<>();

    private Intel() {}

    private static long key(int observerTeam, int targetTeam) {
        return ((long) observerTeam << 32) | (targetTeam & 0xffffffffL);
    }

    /** 由主线程每 tick 调用。 */
    public static void update() {
        try {
            for (var td : Vars.state.teams.present) {
                Team target = td.team;
                if (target == null || td.cores.size == 0) continue;

                for (var other : Vars.state.teams.present) {
                    Team observer = other.team;
                    if (observer == null || observer == target) continue;

                    // 己方核心全知，不走确认流程
                    if (observer == target) continue;

                    State st = states.computeIfAbsent(key(observer.id, target.id), k -> new State());

                    // 取该队的任意一个核心作为观察目标（同队核心库存不同，
                    // 这里对每个核心单独判定）
                    for (CoreBuild core : td.cores) {
                        if (core == null || core.items == null) continue;

                        if (!core.inFogTo(observer)) {
                            st.visibleTicks++;
                            st.lastSeenTick = (long) Vars.state.tick;
                            st.clearTicks = 0;

                            if (st.visibleTicks >= CONFIRM_TICKS) {
                                if (!st.confirmed) {
                                    st.confirmed = true;
                                    st.confirmedAt = (long) Vars.state.tick;
                                }
                                // 每次达到确认阈值都追加一条快照
                                if (st.snapshots.isEmpty()
                                    || (long) Vars.state.tick - st.snapshots.peek().tick
                                       >= CONFIRM_TICKS) {
                                    st.snapshots.add(capture((long) Vars.state.tick, core));
                                }
                            }
                        } else {
                            st.clearTicks++;
                            if (st.clearTicks > CLEAR_TOLERANCE_TICKS) {
                                if (st.visibleTicks > 0 && !st.confirmed) st.visibleTicks = 0;
                                // 已确认的不回退 —— 两态、无失效
                            }
                        }
                    }
                }
            }
        } catch (Throwable t) {
            AIArena.log("intel update failed: " + t);
        }
    }

    private static Snap capture(long tick, CoreBuild core) {
        Seq<String> names = new Seq<>();
        Seq<Integer> amts = new Seq<>();
        int total = 0;

        for (mindustry.type.Item item : Vars.content.items()) {
            int amount = core.items.get(item);
            if (amount > 0) {
                names.add(item.name);
                amts.add(amount);
                total += amount;
            }
        }

        String[] n = names.toArray(String.class);
        int[] a = new int[amts.size];
        for (int i = 0; i < a.length; i++) a[i] = amts.get(i);
        return new Snap(tick, n, a, total);
    }

    public static State get(int observerTeam, int targetTeam) {
        return states.get(key(observerTeam, targetTeam));
    }

    /** 核心被摧毁时清空该队的全部 intel 状态。 */
    public static void clearTeam(int teamId) {
        states.keySet().removeIf(k -> (int) (k & 0xffffffffL) == teamId
                                  || (int) (k >> 32) == teamId);
    }

    /** 核心易主（changeTeam）时，该队视为全新核心。 */
    public static void resetPair(int observerTeam, int targetTeam) {
        states.remove(key(observerTeam, targetTeam));
    }

    public static void clearAll() {
        states.clear();
    }

    public static int size() { return states.size(); }
}
