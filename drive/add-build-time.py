#!/usr/bin/env python3
"""建造确认：材料够不够（已有）+ 建造要多久（本次）。

两个时间口径，都是「看一眼就知道」的量：

  /place  → buildSeconds   这个方块在这个建造单位手下的**施工时长**（不含走路）
                           引擎公式（BuilderComp.java:246）：
                             每帧增量 = type.buildSpeed * buildSpeedMultiplier
                                      * rules.buildSpeed(team) / entity.buildCost
                             entity.buildCost = block.buildTime * rules.buildCostMultiplier
                           所以 秒数 = buildCost / (speed * 60)
                           这是**规则**：方块属性 + 单位速度，玩家选中方块就能看到进度条速度。

  /queue  → etaSeconds     从**实测进度变化率**外推的剩余时间。
                           进度条在动，真人盯着就能估出还要多久。
"""
import pathlib
import sys

S = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\StallWatch.java")
O = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Operations.java")
A = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Actor.java")

# ---------------- StallWatch：进度变化率 ----------------

STATE_OLD = """    /** unitId -> [x, y]，判断建造单位自己有没有在动。 */
    private static final Map<Integer, float[]> unitPos = new HashMap<>();"""

STATE_NEW = """    /** unitId -> [x, y]，判断建造单位自己有没有在动。 */
    private static final Map<Integer, float[]> unitPos = new HashMap<>();
    /** key -> 上次算速率时的毫秒时刻。用来把「进度差」变成「进度/秒」。 */
    private static final Map<String, Long> planSampleMs = new HashMap<>();
    /** key -> 实测进度变化率（进度/秒，>0 表示在推进）。 */
    private static final Map<String, Float> planRate = new HashMap<>();"""

RATE_OLD = """                // 单位在走动就一律重置计时：进度为 0 是「还没开工」，不是停滞
                Float prev = planProgress.get(key);
                boolean progressed = prev != null && Math.abs(prev - prog) > 1e-4f;
                planProgress.put(key, prog);"""

RATE_NEW = """                // 单位在走动就一律重置计时：进度为 0 是「还没开工」，不是停滞
                Float prev = planProgress.get(key);
                boolean progressed = prev != null && Math.abs(prev - prog) > 1e-4f;

                // 顺带算进度变化率 —— 同样是两次采样的差，不额外增加观测成本。
                // 这是「盯着进度条看它涨多快」，真人抬眼就能做。
                Long prevMs = planSampleMs.get(key);
                if (prev != null && prevMs != null) {
                    long dt = now - prevMs;
                    if (dt >= 250L) {              // 太短的间隔噪声大，不采
                        float r = (prog - prev) / (dt / 1000f);
                        if (r > 0f) planRate.put(key, r);
                        else planRate.remove(key);
                        planSampleMs.put(key, now);
                    }
                } else {
                    planSampleMs.put(key, now);
                }

                planProgress.put(key, prog);"""

CLEAN_OLD = """        planProgress.keySet().removeIf(k -> !seen.contains(k));
        planStuckSince.keySet().removeIf(k -> !seen.contains(k));
        unitPos.keySet().removeIf(id -> !aliveUnits.contains(id));"""

CLEAN_NEW = """        planProgress.keySet().removeIf(k -> !seen.contains(k));
        planStuckSince.keySet().removeIf(k -> !seen.contains(k));
        planSampleMs.keySet().removeIf(k -> !seen.contains(k));
        planRate.keySet().removeIf(k -> !seen.contains(k));
        unitPos.keySet().removeIf(id -> !aliveUnits.contains(id));"""

ETA_OLD = """    /** 该计划已经多久没动了（毫秒）；没停滞返回 0。 */
    public static long planStuckMillis(int unitId, int x, int y) {
        Long since = planStuckSince.get(unitId + "@" + plan.x + "," + plan.y);
        return since == null ? 0L : System.currentTimeMillis() - since;
    }"""

ETA_NEW = """    /** 该计划已经多久没动了（毫秒）；没停滞返回 0。 */
    public static long planStuckMillis(int unitId, int x, int y) {
        Long since = planStuckSince.get(unitId + "@" + plan.x + "," + plan.y);
        return since == null ? 0L : System.currentTimeMillis() - since;
    }

    /** 实测进度变化率（进度/秒）；没在推进返回 0。 */
    public static float planRate(int unitId, int x, int y) {
        return planRate.getOrDefault(unitId + "@" + x + "," + y, 0f);
    }

    /**
     * 按当前实测速率外推的剩余秒数。
     *
     * **这是从进度条推出来的，不是引擎给的** —— 进度在涨就线性外推，
     * 没在涨就返回 -1（此时该看 stuckSeconds，而不是瞎估一个数）。
     */
    public static float planEtaSeconds(int unitId, int x, int y, float progress) {
        float r = planRate(unitId, x, y);
        if (r <= 1e-5f) return -1f;
        return Math.max(0f, (1f - progress) / r);
    }"""

CLEAR_OLD = """        planProgress.clear();
        planStuckSince.clear();
        unitPos.clear();
    }"""
CLEAR_NEW = """        planProgress.clear();
        planStuckSince.clear();
        planSampleMs.clear();
        planRate.clear();
        unitPos.clear();
    }"""

# ---------------- Operations：输出 ----------------

QUEUE_OLD = """                    long stuck = StallWatch.planStuckMillis(u.id, plan.x, plan.y);
                    if (stuck > 3000L) {"""

QUEUE_NEW = """                    // 建造还要多久：按实测进度变化率外推。进度条在动，
                    // 真人盯着就能估出来 —— 这里只是把这件肉眼可做的事自动化。
                    float rate = StallWatch.planRate(u.id, plan.x, plan.y);
                    if (rate > 1e-5f) {
                        po.put("progressRate", Math.round(rate * 1000f) / 1000f);
                        po.put("etaSeconds",
                            Math.round(StallWatch.planEtaSeconds(u.id, plan.x, plan.y, prog)));
                    }

                    long stuck = StallWatch.planStuckMillis(u.id, plan.x, plan.y);
                    if (stuck > 3000L) {"""

QUEUE_PROG = """                    float prog = 0f;
                    mindustry.gen.Building tb = Vars.world.build(plan.x, plan.y);
                    if (tb instanceof mindustry.world.blocks.ConstructBlock.ConstructBuild cb) {
                        po.put("constructing", true).put("progress", cb.progress);
                    }"""

QUEUE_PROG_NEW = """                    float prog = 0f;
                    mindustry.gen.Building tb = Vars.world.build(plan.x, plan.y);
                    if (tb instanceof mindustry.world.blocks.ConstructBlock.ConstructBuild cb) {
                        prog = cb.progress;
                        po.put("constructing", true).put("progress", prog);
                    }"""

# ---------------- Actor：理论施工时长 ----------------

ACTOR_OLD = """        if (mat != null) extra.putRaw("materials", mat.toString());
        if (resolvedConfig != null) extra.put("config", describeConfig(resolvedConfig));"""

ACTOR_NEW = """        if (mat != null) extra.putRaw("materials", mat.toString());

        // 施工时长（不含走过去的时间）。公式照抄引擎：
        //   BuilderComp.java:246  每帧增量 = type.buildSpeed * buildSpeedMultiplier
        //                                    * rules.buildSpeed(team) / entity.buildCost
        //   ConstructBlock.java:451  entity.buildCost = block.buildTime * rules.buildCostMultiplier
        // 所以 seconds = buildCost / (speed * 60)。
        // 这是**规则**：方块属性 + 单位速度，玩家看着进度条也能感知快慢。
        try {
            float buildCost = block.buildTime * Vars.state.rules.buildCostMultiplier;
            float speed = builder.type.buildSpeed;
            try { speed *= Vars.state.rules.buildSpeed(team); } catch (Throwable ignored) { }
            if (buildCost > 0f && speed > 0f) {
                extra.putRaw("buildTime", new Json.Obj()
                    .put("seconds", Math.round(buildCost / (speed * 60f) * 100f) / 100f)
                    .put("buildCost", Math.round(buildCost * 100f) / 100f)
                    .put("builderSpeed", Math.round(speed * 100f) / 100f)
                    .toString());
            }
        } catch (Throwable ignored) { }

        if (resolvedConfig != null) extra.put("config", describeConfig(resolvedConfig));"""

JOBS = [
    (S, [
        (STATE_OLD, STATE_NEW, "加 planSampleMs / planRate"),
        (RATE_OLD, RATE_NEW, "算进度变化率"),
        (CLEAN_OLD, CLEAN_NEW, "清理新状态"),
        (ETA_OLD, ETA_NEW, "planRate / planEtaSeconds"),
        (CLEAR_OLD, CLEAR_NEW, "clear 清新状态"),
    ]),
    (O, [
        (QUEUE_PROG, QUEUE_PROG_NEW, "取到 prog 变量"),
        (QUEUE_OLD, QUEUE_NEW, "输出 progressRate / etaSeconds"),
    ]),
    (A, [
        (ACTOR_OLD, ACTOR_NEW, "place 输出 buildTime"),
    ]),
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
    print("建造时间已落地")
    return 0


if __name__ == "__main__":
    sys.exit(main())
