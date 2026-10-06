package aiarena;

import arc.Core;
import arc.files.Fi;
import arc.util.Log;
import mindustry.Vars;

import java.time.Instant;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 审计日志 —— DESIGN.md 684 要求「记录发起者 / 时间 / 目标格，供回放与仲裁」。
 *
 * 此前只有限流，没有审计：一个请求改变了世界，事后无法回答
 * 「谁在什么时候动了哪一格」。比赛里出现争议（谁拆了我的产线）时没有凭据。
 *
 * 写 JSONL 追加。记两类：
 *   1. **会改变世界**的动作；
 *   2. **特权读** —— 带 `view=` 的请求。`view=all` 是裁判的组织者特权，
 *      而参赛 agent 一旦读到 admin token 也能用。这一类是后加的：在此之前
 *      读接口完全不记，于是「谁用了全图视野」事后无法回答 —— 越界不可检测。
 *
 * 普通读接口（不带 `view=`）仍然不记 —— 否则日志会被 /map 刷爆，
 * 真出事时反而查不出来。
 *
 * 同时带 tick 与真实时间两条时间轴：tick 用于和录像对齐，
 * 时间用于和 HTTP 层日志对齐。
 */
public final class Audit {
    private static final java.util.Set<String> MUTATING = java.util.Set.of(
        "place", "break", "config", "mine", "control", "command",
        "queue", "admin", "chat", "spawn", "record", "setup",
        // 下面这三个同样改游戏状态，此前漏记：
        "host",   // 打开游戏端口 6567
        "start",  // 解除暂停
        "fog"     // 改迷雾规则
    );

    private static Fi file;
    private static final AtomicLong written = new AtomicLong();
    private static volatile boolean enabled = true;

    public static void init() {
        try {
            file = Core.files.local("ai-arena-audit.jsonl");
            file.parent().mkdirs();
            Log.info("[ai-arena] audit log -> @", file.absolutePath());
        } catch (Throwable t) {
            enabled = false;
            Log.warn("[ai-arena] audit log disabled: @", String.valueOf(t));
        }
    }

    public static long count() { return written.get(); }
    public static Fi path() { return file; }

    public static boolean isMutating(String action) {
        return action != null && MUTATING.contains(action);
    }

    /**
     * 特权读：query 里带 `view=` 就算。
     *
     * 刻意**宽进** —— 宁可把裁判的正常请求也一并记下，也不漏掉越界的那一条。
     * 普通 agent 传 `view=all` 会被静默降级（不生效），但**照样留痕**：
     * 「尝试过」本身就是要查的事。
     */
    public static boolean isPrivileged(String query) {
        return query != null && query.contains("view=");
    }

    /**
     * query 原样存 —— 目标格就藏在里面（x=&y=...）。
     * 刻意**不解析**：按动作分别解析容易漏字段，原样存下来事后要什么有什么。
     */
    public static void log(String agentId, int teamId, String action, String query, String method,
                           boolean privileged) {
        if (!enabled || file == null) return;
        try {
            int tick;
            try { tick = Vars.state == null ? -1 : (int) Vars.state.tick; }
            catch (Throwable t) { tick = -1; }

            StringBuilder sb = new StringBuilder(192);
            sb.append("{\"t\":\"").append(Instant.now()).append("\"")
              .append(",\"tick\":").append(tick)
              .append(",\"agent\":").append(Json.str(agentId))
              .append(",\"team\":").append(teamId)
              .append(",\"method\":").append(Json.str(method))
              .append(",\"action\":").append(Json.str(action));
            if (query != null && !query.isEmpty())
                sb.append(",\"query\":").append(Json.str(query));
            if (privileged) sb.append(",\"privileged\":true");
            sb.append('}');
            file.writeString(sb.append('\n').toString(), true);
            written.incrementAndGet();
        } catch (Throwable t) {
            Log.warn("[ai-arena] audit write failed: @", String.valueOf(t));
        }
    }
}
