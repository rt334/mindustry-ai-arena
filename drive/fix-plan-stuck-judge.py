#!/usr/bin/env python3
"""修正补3 的判据漏洞：单位在**走路**时会被误判成停滞。

原判据只看「plan.progress 连续不变」。但 BuilderComp:326 只在目标格变成
ConstructBuild 之后才把 cons.progress 写回 plan.progress —— 也就是说，
单位还在赶路的这段时间里 progress 一直是 0，**不变，但不是卡住**。
照原判据，任何稍远一点的计划都会在 3 秒后被误报成 stuckSeconds。

补上第二个条件：**单位自己的位置也得多帧不动**才算停。
真人判断「卡住了」看的正是这两件事——方块不出现、单位也站着不动。
"""
import pathlib
import sys

S = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\StallWatch.java")

OLD = """    /** key = "unitId@x,y" -> 上次看到的进度（0~1）。 */
    private static final Map<String, Float> planProgress = new HashMap<>();
    /** key = "unitId@x,y" -> 进度**首次**不再变化的毫秒时刻。 */
    private static final Map<String, Long> planStuckSince = new HashMap<>();"""

NEW = """    /** key = "unitId@x,y" -> 上次看到的进度（0~1）。 */
    private static final Map<String, Float> planProgress = new HashMap<>();
    /** key = "unitId@x,y" -> 进度**首次**不再变化的毫秒时刻。 */
    private static final Map<String, Long> planStuckSince = new HashMap<>();
    /** unitId -> [x, y]，判断建造单位自己有没有在动。 */
    private static final Map<Integer, float[]> unitPos = new HashMap<>();"""

UPDATE_OLD = """    public static void updatePlans() {
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
    }"""

UPDATE_NEW = """    /** 建造单位位置变化超过这个距离（格）就算「在动」。 */
    private static final float MOVING_EPS = 0.5f;

    public static void updatePlans() {
        long now = System.currentTimeMillis();
        java.util.HashSet<String> seen = new java.util.HashSet<>();
        java.util.HashSet<Integer> aliveUnits = new java.util.HashSet<>();

        for (mindustry.gen.Unit u : mindustry.gen.Groups.unit) {
            if (u == null) continue;
            aliveUnits.add(u.id);

            // 这个单位自己有没有在动？走路中的单位不算「卡住」——
            // 它只是还没走到工地。
            float[] pp = unitPos.get(u.id);
            boolean moved = pp == null
                || Math.abs(pp[0] - u.x) > MOVING_EPS
                || Math.abs(pp[1] - u.y) > MOVING_EPS;
            unitPos.put(u.id, new float[]{u.x, u.y});

            if (u.plans == null) continue;
            for (mindustry.entities.units.BuildPlan plan : u.plans) {
                if (plan == null) continue;
                String key = u.id + "@" + plan.x + "," + plan.y;
                seen.add(key);

                float prog = plan.progress;
                Building tb = Vars.world.build(plan.x, plan.y);
                if (tb instanceof mindustry.world.blocks.ConstructBlock.ConstructBuild cb) {
                    prog = cb.progress;          // 已在施工的格子，进度以它为准
                }

                // 单位在走动就一律重置计时：进度为 0 是「还没开工」，不是停滞
                Float prev = planProgress.get(key);
                boolean progressed = prev != null && Math.abs(prev - prog) > 1e-4f;
                planProgress.put(key, prog);

                if (moved || progressed) {
                    planStuckSince.remove(key);  // 有动作，重新计时
                } else if (!planStuckSince.containsKey(key)) {
                    planStuckSince.put(key, now); // 单位和进度都停住了
                }
            }
        }

        // 计划消失（建完了、被替换了、被清了）就丢掉
        planProgress.keySet().removeIf(k -> !seen.contains(k));
        planStuckSince.keySet().removeIf(k -> !seen.contains(k));
        unitPos.keySet().removeIf(id -> !aliveUnits.contains(id));
    }"""

CLEAR_OLD = """        planProgress.clear();
        planStuckSince.clear();
    }"""
CLEAR_NEW = """        planProgress.clear();
        planStuckSince.clear();
        unitPos.clear();
    }"""

RULES = [
    (OLD, NEW, "加 unitPos 跟踪"),
    (UPDATE_OLD, UPDATE_NEW, "判据补上「单位自己也在动」"),
    (CLEAR_OLD, CLEAR_NEW, "clear 清 unitPos"),
]


def main():
    text = S.read_text(encoding="utf-8")
    bad = []
    for old, new, label in RULES:
        n = text.count(old)
        if n != 1:
            bad.append(f"{n} 次命中: {label}")
            print(f"  !! {n} 次  {label}")
            continue
        text = text.replace(old, new)
        print(f"  1 处  {label}")
    if bad:
        print("\n有问题，未写盘")
        return 1
    S.write_text(text, encoding="utf-8")
    print("\nStallWatch.java 已修正")
    return 0


if __name__ == "__main__":
    sys.exit(main())
