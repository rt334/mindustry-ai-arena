package aiarena;

import mindustry.Vars;
import mindustry.entities.units.BuildPlan;
import mindustry.game.Team;
import mindustry.gen.Groups;
import mindustry.gen.Unit;

/**
 * 「值得注意」的聚合判定 —— 给客户端一个**能安心入睡的依据**。
 *
 * 为什么需要它（`docs/TODO.md` §九 #7、`docs/PRIOR-ART.md` §五）：
 *
 *   实时游戏里 AI 跟不上 tick（引擎 60 tick/s，一次 LLM 决策是秒级），
 *   所以正确形态是「**有事才醒**」而不是「一直轮询」。但光有「有事发生」不够 ——
 *   客户端还需要一个**明确的「现在没事」信号**，否则它不敢睡，只能继续轮询。
 *   现有信号散在三处（`/stalls` 的停机、`/queue` 的停滞、`/events` 的事件流），
 *   这个端点把它们合成**一个判断**。
 *
 * **它只做聚合，不新增游戏内情**：返回的每一项都能用既有端点单独查到，
 * 这里不解释「为什么会堵」「该改哪一格」—— 那是 AI 自己的事。
 */
public final class Watch {

    /** 停滞超过这个秒数才算「值得注意」。短于它属于正常施工节奏，报出来只是噪声。 */
    private static final double STUCK_ALERT_SECONDS = 10.0;

    private Watch() {}

    /**
     * @param team     调用方的队伍（只看自己队的信号 —— 对等约束）
     * @param sinceSeq 客户端上次拿到的事件序号；用来判断「有没有新事件」
     */
    public static String evaluate(Team team, long sinceSeq) {
        int stalls = 0;
        int plans = 0;
        int stuckPlans = 0;
        double worstStuck = 0;

        try {
            stalls = StallWatch.stalledCountFor(team);

            for (Unit u : Groups.unit) {
                if (u == null || u.team != team || u.plans == null) continue;
                for (BuildPlan p : u.plans) {
                    if (p == null) continue;
                    plans++;
                    long ms = StallWatch.planStuckMillis(u.id, p.x, p.y);
                    if (ms > 0) {
                        double s = ms / 1000.0;
                        if (s > worstStuck) worstStuck = s;
                        if (s >= STUCK_ALERT_SECONDS) stuckPlans++;
                    }
                }
            }
        } catch (Throwable ignored) { }

        long last = EventLog.lastSeq();
        long newEvents = Math.max(0L, last - sinceSeq);

        StringBuilder reasons = new StringBuilder("[");
        boolean first = true;
        if (stalls > 0) { reasons.append("\"stalls\""); first = false; }
        if (stuckPlans > 0) { if (!first) reasons.append(','); reasons.append("\"queueStuck\""); first = false; }
        if (newEvents > 0) { if (!first) reasons.append(','); reasons.append("\"newEvents\""); }
        reasons.append(']');

        boolean clear = stalls == 0 && stuckPlans == 0 && newEvents == 0;

        String hint = clear
            ? "没有待处理的事 —— 可以安心睡：用 /stream 等事件，醒来后带 since=" + last + " 再问一次"
            : "有事要看：停机 → /stalls；队列 → /queue；新事件 → /events?since=" + sinceSeq;

        return new Json.Obj()
            .put("tick", Vars.state == null ? -1L : (long) Vars.state.tick)
            .put("clear", clear)
            .putRaw("reasons", reasons.toString())
            .putRaw("counts", new Json.Obj()
                .put("stalls", stalls)
                .put("plans", plans)
                .put("stuckPlans", stuckPlans)
                .put("worstStuckSeconds", (float) Math.round(worstStuck * 10) / 10f)
                .put("newEvents", newEvents)
                .toString())
            .put("sinceSeq", sinceSeq)
            .put("nextSince", last)
            .put("hint", hint)
            .toString();
    }
}
