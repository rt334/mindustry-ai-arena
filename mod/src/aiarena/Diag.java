package aiarena;

import arc.util.Time;

import java.util.ArrayDeque;
import java.util.Deque;

/**
 * 运行时诊断。
 *
 * 为什么要单独做一套：这一轮排查里最耗时间的不是「哪个字段错了」，而是
 * **看不到事实**。症状（切队跳回、全图没单位、建筑要等一会儿才出现）都能被
 * 至少两种完全不同的原因解释，而没有数据就只能猜。实测多次出现「日志看起来
 * 正常、但现象依旧」的情况 —— 因为关键事实（断线重连、视角被重置、实体
 * 数量对不上）根本没人记录。
 *
 * 这里记三类东西：
 *   1. 连接生命周期 —— 什么时候连上、什么时候断开、**断开原因是什么**
 *   2. 断开原因的直方图 —— 一眼看出是超时、是客户端主动关、还是底层错误
 *   3. 快照路由计数 —— 每帧给谁发了哪个队的实体，验证视角真的生效了
 *
 * 全部通过 /v1/{admin}/diag 暴露，配合 diagnose.ps1 一次性拉取。
 */
public final class Diag {

    /** 一条连接事件。 */
    public static final class Event {
        public final long millis;
        public final long tick;
        public final String name;
        public final String uuid;
        public final String kind;    // join / leave
        public final String reason;  // leave 时才有

        Event(long millis, long tick, String name, String uuid, String kind, String reason) {
            this.millis = millis;
            this.tick = tick;
            this.name = name;
            this.uuid = uuid;
            this.kind = kind;
            this.reason = reason;
        }

        public String toJson() {
            return new Json.Obj()
                .put("t", millis)
                .put("tick", tick)
                .put("name", name == null ? "?" : name)
                .put("uuid", uuid == null ? "?" : uuid)
                .put("kind", kind)
                .put("reason", reason == null ? "" : reason)
                .toString();
        }
    }

    private static final int MAX_EVENTS = 200;
    private static final Deque<Event> events = new ArrayDeque<>();

    /** 快照路由计数：直接读引擎里的计数器，避免两处各记一份而不同步。 */
    public static long teamBatchSends() { return mindustry.core.NetServer.diagTeamBatchSends; }
    public static long fullViewSends() { return mindustry.core.NetServer.diagFullViewSends; }
    public static long spectatorRouted() { return mindustry.core.NetServer.diagSpectatorRouted; }

    private Diag() {}

    private static void add(String name, String uuid, String kind, String reason) {
        synchronized (events) {
            events.addLast(new Event(Time.millis(), (long) mindustry.Vars.state.tick,
                name, uuid, kind, reason));
            while (events.size() > MAX_EVENTS) events.removeFirst();
        }
    }

    public static void join(mindustry.gen.Player p) {
        if (p == null) return;
        add(p.name, p.uuid(), "join", null);
    }

    public static void leave(mindustry.gen.Player p, String reason) {
        if (p == null) return;
        add(p.name, p.uuid(), "leave", reason);
    }

    /** 最近的事件（旧的在前）。 */
    public static String eventsJson() {
        StringBuilder sb = new StringBuilder("[");
        synchronized (events) {
            boolean first = true;
            for (Event e : events) {
                if (!first) sb.append(',');
                first = false;
                sb.append(e.toJson());
            }
        }
        return sb.append(']').toString();
    }

    /**
     * 断开原因直方图。
     *
     * Kryonet 的 DcReason 会以字符串形式传进来：
     *   closed      客户端主动关闭（正常退出）
     *   timeout     心跳超时 —— 通常是 UDP 被拦或丢包
     *   error       底层读写错误 —— 网络栈层面的问题
     *   reset       连接被重置
     * 反复出现 timeout/error 而不是 closed，基本就能确定是网络层在拦包。
     */
    public static String reasonHistogramJson() {
        java.util.Map<String, Integer> counts = new java.util.TreeMap<>();
        synchronized (events) {
            for (Event e : events) {
                if (!"leave".equals(e.kind)) continue;
                String r = (e.reason == null || e.reason.isEmpty()) ? "(none)" : e.reason;
                counts.merge(r, 1, Integer::sum);
            }
        }
        Json.Obj o = new Json.Obj();
        for (var en : counts.entrySet()) o.put(en.getKey(), en.getValue());
        return o.toString();
    }

    /** 重置计数（开新一局时调用）。 */
    public static void reset() {
        synchronized (events) {
            events.clear();
        }
        mindustry.core.NetServer.diagTeamBatchSends = 0;
        mindustry.core.NetServer.diagFullViewSends = 0;
        mindustry.core.NetServer.diagSpectatorRouted = 0;
    }
}
