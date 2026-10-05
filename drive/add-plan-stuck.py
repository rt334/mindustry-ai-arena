#!/usr/bin/env python3
"""补3：/queue 能看出哪个计划卡住了、卡了多久。

原始痛点（REVIEW-ADDENDUM 补3）：
    「plans 长时间不变、建筑数不变、建造单位位置不变……常规手段无效：
      break 空格想取消排队中的计划是无效的，反而追加拆除计划。」
    ⇒ 建议 /queue 应该能判断「停滞」并提示这是个可操作项。

判据是**进度是否还在变**，不是「过了多久」—— 同一个 progress 连续保持才算停滞，
和 clogWarm 那套一样用状态而不是时长。真人判断「卡住了」也是这么看的：
单位站在原地不动、方块迟迟不出现。

同时把已知的解法（移动命令）在响应里点出来，免得 AI 再踩一遍。
"""
import pathlib
import sys

S = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\StallWatch.java")
M = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\AIArenaMod.java")
O = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Operations.java")

CLEAR_OLD = """    public static void clear() {
        lastReport.clear();
        stalledSince.clear();
        stalledKind.clear();
        lastSnapshot = "[]";
    }"""

CLEAR_NEW = """    public static void clear() {
        lastReport.clear();
        stalledSince.clear();
        stalledKind.clear();
        lastSnapshot = "[]";
        planProgress.clear();
        planStuckSince.clear();
    }

    // ---------------------------------------------------------------- 计划停滞

    /** key = "unitId@x,y" -> 上次看到的进度（0~1）。 */
    private static final Map<String, Float> planProgress = new HashMap<>();
    /** key = "unitId@x,y" -> 进度**首次**不再变化的毫秒时刻。 */
    private static final Map<String, Long> planStuckSince = new HashMap<>();

    /**
     * 跟踪建造计划有没有卡住。
     *
     * 判据是**进度是否还在变** —— 同一个 progress 连续保持才算停滞，
     * 和 clogHeat 那套一样用的是状态而不是时长。真人判断「卡住了」也是这么看：
     * 单位站在原地不动、方块迟迟不出现。
     *
     * 动机：队列卡死时 AI 只能看到一个不变的计划数，既不知道卡在哪一格、
     * 也不知道卡了多久 —— 而这两件事抬眼就能看见。
     */
    public static void updatePlans() {
        long now = System.currentTimeMillis();
        java.util.HashSet<String> seen = new java.util.HashSet<>();

        for (mindustry.gen.Unit u : mindustry.gen.Groups.unit) {
            if (u == null || u.plans == null) continue;
            for (mindustry.entities.units.BuildPlan plan : u.plans) {
                if (plan == null) continue;
                String key = u.id + "@" + plan.x + "," + plan.y;
                seen.add(key);

                float prog = plan.progress;
                Building tb = Vars.world.build(plan.x, plan.y);
                if (tb instanceof mindustry.world.blocks.ConstructBlock.ConstructBuild cb) {
                    prog = cb.progress;          // 已在施工的格子，进度以它为准
                }

                Float prev = planProgress.get(key);
                if (prev == null || Math.abs(prev - prog) > 1e-4f) {
                    planProgress.put(key, prog);
                    planStuckSince.remove(key);  // 动了，重新计时
                } else if (!planStuckSince.containsKey(key)) {
                    planStuckSince.put(key, now); // 第一次发现它没动
                }
            }
        }

        // 计划消失（建完了、被替换了、被清了）就丢掉
        planProgress.keySet().removeIf(k -> !seen.contains(k));
        planStuckSince.keySet().removeIf(k -> !seen.contains(k));
    }

    /** 该计划已经多久没动了（毫秒）；没停滞返回 0。 */
    public static long planStuckMillis(int unitId, int x, int y) {
        Long since = planStuckSince.get(unitId + "@" + x + "," + y);
        return since == null ? 0L : System.currentTimeMillis() - since;
    }"""

MOD_OLD = """                StallWatch.update();"""
MOD_NEW = """                StallWatch.update();
                StallWatch.updatePlans();"""

QUEUE_OLD = """                    mindustry.gen.Building tb = Vars.world.build(plan.x, plan.y);
                    if (tb instanceof mindustry.world.blocks.ConstructBlock.ConstructBuild cb) {
                        po.put("constructing", true).put("progress", cb.progress);
                    }"""

QUEUE_NEW = """                    mindustry.gen.Building tb = Vars.world.build(plan.x, plan.y);
                    if (tb instanceof mindustry.world.blocks.ConstructBlock.ConstructBuild cb) {
                        po.put("constructing", true).put("progress", cb.progress);
                    }
                    // 进度连续不动 = 卡住。超过 3 秒才报，免得把正常的启动间隔
                    // 当成异常。真人是靠「单位站着不动、方块不出现」看出来的。
                    long stuck = StallWatch.planStuckMillis(u.id, plan.x, plan.y);
                    if (stuck > 3000L) {
                        po.put("stuckSeconds", Math.round(stuck / 1000.0))
                          .put("hint", "move the builder to the site to break it loose: "
                                     + "/control?op=order&unit=" + u.id
                                     + "&x=" + plan.x + "&y=" + plan.y);
                    }"""

JOBS = [
    (S, [(CLEAR_OLD, CLEAR_NEW, "计划停滞跟踪 + clear 清状态")]),
    (M, [(MOD_OLD, MOD_NEW, "每帧调用 updatePlans")]),
    (O, [(QUEUE_OLD, QUEUE_NEW, "queueReport 输出 stuckSeconds 与解法")]),
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
        print("有问题：")
        for b in bad:
            print("  " + b)
        return 1
    print("补3 已落地")
    return 0


if __name__ == "__main__":
    sys.exit(main())
