#!/usr/bin/env python3
"""补功能缺口 §2.2 的三项：审计日志 / 端口发现文件 / 写队列每 tick 预算。

**SSE 与蓝图导入这次不做** —— SSE 要复用 events 的序列化（我还没确认它的
JSON 构造函数，硬写有编译不过的风险）；蓝图导入涉及 Mindustry 的 .msch
二进制格式，不是插几行能完的。宁可少做两项，不做假动作。
"""
import pathlib
import sys

MOD = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena")
API = MOD / "HttpApi.java"
ARENA = MOD / "AIArena.java"
AUDIT = MOD / "Audit.java"

AUDIT_SRC = '''package aiarena;

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
 * 写 JSONL 追加。只记**会改变世界**的动作 —— 读接口不记，
 * 否则日志会被 /map 刷爆，真出事时反而查不出来。
 *
 * 同时带 tick 与真实时间两条时间轴：tick 用于和录像对齐，
 * 时间用于和 HTTP 层日志对齐。
 */
public final class Audit {
    private static final java.util.Set<String> MUTATING = java.util.Set.of(
        "place", "break", "config", "mine", "control", "command",
        "queue", "admin", "chat", "spawn", "record", "setup"
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
     * query 原样存 —— 目标格就藏在里面（x=&y=...）。
     * 刻意**不解析**：按动作分别解析容易漏字段，原样存下来事后要什么有什么。
     */
    public static void log(String agentId, int teamId, String action, String query, String method) {
        if (!enabled || file == null) return;
        try {
            int tick;
            try { tick = Vars.state == null ? -1 : Vars.state.tick; }
            catch (Throwable t) { tick = -1; }

            StringBuilder sb = new StringBuilder(192);
            sb.append("{\\"t\\":\\"").append(Instant.now()).append("\\"")
              .append(",\\"tick\\":").append(tick)
              .append(",\\"agent\\":").append(Json.str(agentId))
              .append(",\\"team\\":").append(teamId)
              .append(",\\"method\\":").append(Json.str(method))
              .append(",\\"action\\":").append(Json.str(action));
            if (query != null && !query.isEmpty())
                sb.append(",\\"query\\":").append(Json.str(query));
            sb.append('}');
            file.writeString(sb.append('\\n').toString(), true);
            written.incrementAndGet();
        } catch (Throwable t) {
            Log.warn("[ai-arena] audit write failed: @", String.valueOf(t));
        }
    }
}
'''

ROUTE_OLD = """            // 限流在鉴权之后、路由之前：过不了鉴权的请求不该消耗配额。
            if (!AIArena.takeToken(agent)) {"""
ROUTE_NEW = """            // 审计：谁、什么时候、要动哪一格。只记会改变世界的动作，
            // 读接口不记 —— 否则被 /map 刷爆，真出事时反而查不出东西。
            if (Audit.isMutating(action)) {
                Audit.log(agentId, agent.team == null ? -1 : agent.team.id, action,
                          ex.getRequestURI().getRawQuery(), ex.getRequestMethod());
            }

            // 限流在鉴权之后、路由之前：过不了鉴权的请求不该消耗配额。
            if (!AIArena.takeToken(agent)) {"""

BUDGET_OLD = """    private static void postToGame(HttpExchange ex, GameTask task) {
        CompletableFuture<String> future = new CompletableFuture<>();

        Core.app.post(() -> {
            try { future.complete(task.run()); }
            catch (Throwable t) { future.complete(Json.error(1500, String.valueOf(t))); }
        });"""

BUDGET_NEW = """    /**
     * 写队列每 tick 的执行预算（DESIGN.md 662「参考 MindustryX 的 1ms」）。
     *
     * 没有它时，一批 /place 会把主线程按住不放：那几毫秒本该用来跑对局，
     * 却被 HTTP 请求吃掉，全场 tick 跟着抖。这是**别人的操作拖慢我**的典型
     * 来源，竞技场里不可接受。
     *
     * 在主线程里计量任务真正执行的时间，按 tick 累计，tick 一变清零。
     * 预算用完后直接拒（1007），不排队 —— 排队只会让积压更深。
     */
    private static long budgetNanos = 1_000_000L;      // 默认 1ms
    private static long budgetTick = -1L;
    private static long budgetUsed = 0L;

    public static void setWriteBudgetMillis(double ms) {
        budgetNanos = (long) (Math.max(0.05, ms) * 1_000_000L);
    }

    private static void postToGame(HttpExchange ex, GameTask task) {
        CompletableFuture<String> future = new CompletableFuture<>();

        Core.app.post(() -> {
            long nowTick;
            try { nowTick = Vars.state == null ? -1 : Vars.state.tick; }
            catch (Throwable t) { nowTick = -1; }

            if (nowTick != budgetTick) {          // 新 tick 清零
                budgetTick = nowTick;
                budgetUsed = 0L;
            }
            if (budgetUsed >= budgetNanos) {
                future.complete(Json.error(1007, "write queue budget exhausted for tick "
                    + nowTick + " (" + (budgetNanos / 1_000_000.0) + " ms/tick); retry next tick"));
                return;
            }

            long t0 = System.nanoTime();
            try { future.complete(task.run()); }
            catch (Throwable t) { future.complete(Json.error(1500, String.valueOf(t))); }
            finally { budgetUsed += System.nanoTime() - t0; }
        });"""

PORT_OLD = """        log("loaded " + agents.size() + " agent(s), bind=" + bind + ":" + port);"""
PORT_NEW = """        log("loaded " + agents.size() + " agent(s), bind=" + bind + ":" + port);
        Audit.init();
        writeDiscoveryFiles();"""

PORT_METHOD = '''
    /**
     * 端口发现文件 —— DESIGN.md 704-715 要求 `bridge-<agentId>.json`。
     *
     * 此前零实现，而且 DESIGN.md 里写死的 `port: 7199` 与可配置端口冲突：
     * 改了配置之后别人还得去读配置才知道连哪。这个文件就是「实际在哪个端口」
     * 的唯一答案。
     *
     * **不写 token** —— 它只解决「连哪」，不解决「以谁的身份」。
     * 把凭据塞进固定路径的文件里，等于把钥匙放在门口垫子下。
     */
    private static void writeDiscoveryFiles() {
        try {
            for (Agent ag : agents) {
                String base = "http://" + bind + ":" + port + "/v1/" + ag.id;
                String json = new Json.Obj()
                    .put("agent", ag.id)
                    .put("httpPort", port)
                    .put("httpBase", base)
                    .toString();
                Core.files.local("bridge-" + ag.id + ".json").writeString(json);
            }
            log("wrote " + agents.size() + " discovery file(s): bridge-<agent>.json");
        } catch (Throwable t) {
            log("discovery files failed: " + t);
        }
    }
'''


def apply(path, old, new, want, label):
    t = path.read_text(encoding="utf-8")
    n = t.count(old)
    if n != want:
        print(f"  !! {n}/{want}  {label}")
        return None
    print(f"  ✓ {n} 处  {label}")
    return t.replace(old, new, 1)


def main():
    ok = True
    AUDIT.write_text(AUDIT_SRC, encoding="utf-8")
    print(f"  ✓ 新建  {AUDIT.name}")

    for path, old, new, label in (
        (API, ROUTE_OLD, ROUTE_NEW, "route 挂审计"),
        (API, BUDGET_OLD, BUDGET_NEW, "postToGame 加 tick 预算"),
        (ARENA, PORT_OLD, PORT_NEW, "启动写端口发现文件"),
    ):
        r = apply(path, old, new, 1, label)
        if r is None:
            ok = False
            continue
        path.write_text(r, encoding="utf-8")

    # 方法追加到类尾（插在最后一个 '}' 之前）。**不能挂在 try 块里的锚点上** ——
    # 那样会顺手闭合 try，把结构搞坏（第一次就是这么编译失败的）。
    t = ARENA.read_text(encoding="utf-8").rstrip()
    if not t.endswith("}"):
        print("  !! AIArena 结尾不是 '}'，未追加方法")
        ok = False
    else:
        t = t[:-1] + PORT_METHOD + "}\n"
        ARENA.write_text(t, encoding="utf-8")
        print("  ✓ 1 处  writeDiscoveryFiles 追加到类尾")
    if not ok:
        print("\n有锚点不匹配，未全部写盘")
        return 1
    print("\n三项已改")
    return 0


if __name__ == "__main__":
    sys.exit(main())
