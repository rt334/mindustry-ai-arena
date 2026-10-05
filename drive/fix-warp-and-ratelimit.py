#!/usr/bin/env python3
"""两个对等性/安全性问题。

1) /control?op=warp —— 唯一的瞬移后门
   Commander.java:294 直接 u.x = ...; u.y = ...，是 P0 技术验证留下的调试工具
   （它挂了个 Probe 观察「传送后位置会不会被引擎改回去」）。
   「移动速度 = 引擎行为」是对等约束第 9 条，而这条路完全绕过它：
   AI 能瞬移，人类只能 WASD。

   审计过全代码库，只有这一处瞬移：
     Commander.java:412  u.vel.set(dx, dy).nor().scl(sp)   ← 用 u.speed()，正常
     其余匹配都是 DTO 的字段赋值，无副作用。

   照 ALLOW_DIRECT_SPAWN 的先例：默认禁用，-Darena.allowwarp=true 打开。

2) rateLimit —— 配置了但从未实现
   AIArena:371-372 解析 perSecond / burst，HttpApi 的错误码表里也写着
   1429 rate_limited，但**没有任何限流逻辑**。一个 agent 可以放开打满 HTTP
   线程池（16 个线程），把其他 agent 的请求全堵在队列里。

   补一个每 agent 的令牌桶。
"""
import pathlib
import sys

A = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\AIArena.java")
C = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Commander.java")
H = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\HttpApi.java")

# ---------------- AIArena：开关 + 令牌桶 ----------------

FLAG_OLD = """    public static final boolean ALLOW_DIRECT_SPAWN =
        "true".equalsIgnoreCase(System.getProperty("arena.allowspawn", "false"));"""

FLAG_NEW = """    public static final boolean ALLOW_DIRECT_SPAWN =
        "true".equalsIgnoreCase(System.getProperty("arena.allowspawn", "false"));

    /**
     * 是否允许 /control?op=warp —— **直接改单位坐标**。
     *
     * 默认禁止。这是 P0 技术验证留下的调试探针（用来观察「服务器改世界之后
     * 位置会不会被引擎改回去」），但它同时是一条**瞬移后门**：
     *
     *   对等约束第 9 条是「移动速度 = 引擎行为」，人类玩家只能 WASD，
     *   而 warp 让 AI 一步跨到任意坐标 —— 走位、赶路、规避全都不再成立。
     *
     * 调试时用 -Darena.allowwarp=true 显式打开。
     */
    public static final boolean ALLOW_WARP =
        "true".equalsIgnoreCase(System.getProperty("arena.allowwarp", "false"));

    // ---------------------------------------------------------------- 限流

    /** 每 agent 的令牌桶。key = agent id。 */
    private static final java.util.Map<String, Bucket> buckets =
        new java.util.concurrent.ConcurrentHashMap<>();

    private static final class Bucket {
        double tokens;
        long lastMs;
        Bucket(double tokens, long now) { this.tokens = tokens; this.lastMs = now; }
    }

    /**
     * 令牌桶限流。超限返回 false（调用方回 429 + code 1429）。
     *
     * 动机：配置里的 rateLimit 以前是**死配置** —— 解析了却没人用，
     * 于是一个 agent 放开打就能占满 HTTP 线程池，把别的 agent 全堵住。
     *
     * 用同步块而不是无锁：只有 16 个 HTTP 线程会走到这，争用很低，
     * 而令牌桶的读改写必须原子。
     */
    public static boolean takeToken(Agent agent) {
        if (agent == null) return true;
        long now = System.currentTimeMillis();
        Bucket b = buckets.computeIfAbsent(agent.id, k -> new Bucket(rateBurst, now));
        synchronized (b) {
            double elapsed = (now - b.lastMs) / 1000.0;
            b.lastMs = now;
            b.tokens = Math.min(rateBurst, b.tokens + elapsed * ratePerSecond);
            if (b.tokens < 1.0) return false;
            b.tokens -= 1.0;
            return true;
        }
    }"""

# ---------------- Commander：warp 加开关 ----------------

WARP_OLD = """    public static Actor.Result warp(Team team, int unitId, float tx, float ty) {
        Unit u = Groups.unit.getByID(unitId);
        if (u == null) return err(1002, "unit id " + unitId + " not found");
        if (u.team != team) return err(1005, "unit belongs to " + u.team.name);
        u.x = px(tx); u.y = px(ty);"""

WARP_NEW = """    public static Actor.Result warp(Team team, int unitId, float tx, float ty) {
        // 默认禁止：这是直接改坐标的瞬移，人类只能 WASD。
        // 详见 AIArena.ALLOW_WARP 的说明。
        if (!AIArena.ALLOW_WARP) {
            return err(1005, "direct position setting is disabled: unit movement must go "
                + "through the engine (use /command?action=move). "
                + "Server-side override: -Darena.allowwarp=true");
        }
        Unit u = Groups.unit.getByID(unitId);
        if (u == null) return err(1002, "unit id " + unitId + " not found");
        if (u.team != team) return err(1005, "unit belongs to " + u.team.name);
        u.x = px(tx); u.y = px(ty);"""

# ---------------- HttpApi：挂上限流 ----------------

ROUTE_OLD = """            if (!agent.id.equals(agentId)) {
                respond(ex, 403, Json.error(1403, "token does not belong to agent '" + agentId + "'"));
                return;
            }"""

ROUTE_NEW = """            if (!agent.id.equals(agentId)) {
                respond(ex, 403, Json.error(1403, "token does not belong to agent '" + agentId + "'"));
                return;
            }

            // 限流在鉴权之后、路由之前：过不了鉴权的请求不该消耗配额。
            if (!AIArena.takeToken(agent)) {
                respond(ex, 429, Json.error(1429, "rate limit exceeded: "
                    + AIArena.ratePerSecond + "/s (burst " + AIArena.rateBurst + ")"));
                return;
            }"""

CODE_OLD = """            case 1008 -> 409;           // conflict：footprint 被别的建筑或固体地形占住"""

CODE_NEW = """            case 1008 -> 409;           // conflict：footprint 被别的建筑或固体地形占住
            case 1429 -> 429;           // too many requests：令牌桶空了"""

JOBS = [
    (A, [(FLAG_OLD, FLAG_NEW, "ALLOW_WARP 开关 + 令牌桶限流")]),
    (C, [(WARP_OLD, WARP_NEW, "warp 默认禁用")]),
    (H, [(ROUTE_OLD, ROUTE_NEW, "路由挂上限流"),
         (CODE_OLD, CODE_NEW, "statusFor 加 1429 -> 429")]),
]


def main():
    bad = []
    for path, rules in JOBS:
        text = path.read_text(encoding="utf-8")
        print(f"  {path.name}")
        for old, new, label in rules:
            n = text.count(old)
            if n != 1:
                bad.append(f"{path.name}: {n} 次命中 -> {label}")
                print(f"      !! {n} 次  {label}")
                continue
            text = text.replace(old, new)
            print(f"      1 处  {label}")
        path.write_text(text, encoding="utf-8")
    print()
    if bad:
        print("有问题（注意上面已写盘的部分）：")
        for b in bad:
            print("  " + b)
        return 1
    print("已落地")
    return 0


if __name__ == "__main__":
    sys.exit(main())
