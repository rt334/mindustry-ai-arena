#!/usr/bin/env python3
"""补 stuckReason —— 把「卡了多久」升级成「为什么卡」。

FEATURE-REQUESTS A5 原文要求：「/diag 或 /queue 标出『进度长时间停滞的计划』，
并说明停滞原因（无建造单位可达 / footprint 冲突 / 计划被孤立）」

之前只做了前半截：给了 stuckSeconds 和 hint（解法），没说原因。
而 hint 说的「用移动命令推一把」在「被墙挡住」的情况下根本不是解法 ——
推过去还是会卡回来。

三种可检测的原因（都是玩家能直接看到的）：
  材料不够    核心物品栏里没有 / 不够 —— 选中方块能看到配方，选中核心能看到库存
  那格被占着  工地上已经站着别的建筑 —— 肉眼可见
  单位够不到  单位离工地比 buildRange 还远 —— 看得见单位在哪、方块在哪

第四种（单位自己的状态机卡死）没法从外部判定，如实报 unknown，
不编一个看起来像答案的字符串。
"""
import pathlib
import sys

O = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Operations.java")

OLD = """                    long stuck = StallWatch.planStuckMillis(u.id, plan.x, plan.y);
                    if (stuck > 3000L) {
                        po.put("stuckSeconds", Math.round(stuck / 1000.0))
                          .put("hint", "move the builder to the site to break it loose: "
                                     + "/control?op=order&unit=" + u.id
                                     + "&x=" + plan.x + "&y=" + plan.y);
                    }"""

NEW = """                    long stuck = StallWatch.planStuckMillis(u.id, plan.x, plan.y);
                    if (stuck > 3000L) {
                        po.put("stuckSeconds", Math.round(stuck / 1000.0));
                        String why = whyStuck(team, u, plan, tb);
                        po.put("stuckReason", why);
                        // 只有「单位够不到」才推移动命令。别的原因推了也没用 ——
                        // 被墙挡住的话，推过去还会卡回来。
                        if ("builderTooFar".equals(why)) {
                            po.put("hint", "move the builder to the site: "
                                         + "/control?op=order&unit=" + u.id
                                         + "&x=" + plan.x + "&y=" + plan.y);
                        } else if ("missingMaterials".equals(why)) {
                            po.put("hint", "produce the missing item, or clear this plan "
                                         + "with POST /queue?clear=true");
                        } else if ("tileOccupied".equals(why)) {
                            po.put("hint", "that tile already has a building; use /break, "
                                         + "or /place again on the same tile to retarget");
                        }
                    }"""

HELPER_ANCHOR = """    /** 清空队伍所有建造单位的待办计划。 */"""

HELPER = """    /**
     * 计划不动的直接原因。**都是玩家能直接看到的东西**：
     *   材料       —— 选中方块看配方、选中核心看库存，一比就知道
     *   那格被占   —— 工地上站着别的建筑，肉眼可见
     *   单位够不到 —— 看得见单位在哪、方块在哪，而引擎的建造范围是固定值
     *
     * 第四种（单位自己的状态机卡死）从外部判定不了，如实报 unknown ——
     * 不编一个看起来像答案的字符串。
     */
    private static String whyStuck(Team team, Unit u, mindustry.entities.units.BuildPlan plan,
                                   mindustry.gen.Building at) {
        // 1) 材料
        if (!plan.breaking && plan.block != null && plan.block.requirements != null) {
            mindustry.gen.Building core = team.core();
            if (core != null) {
                float mult = Vars.state.rules.buildCostMultiplier;
                for (mindustry.type.ItemStack req : plan.block.requirements) {
                    if (req == null || req.item == null) continue;
                    int need = Math.max(1, arc.math.Mathf.round(req.amount * mult));
                    int have = core.items.get(req.item);
                    if (have < need) {
                        return "missingMaterials: " + plan.block.name + " needs "
                             + need + " " + req.item.name + ", core has " + have;
                    }
                }
            }
        }
        // 2) 那格已经被别的建筑占了（ConstructBuild 是施工中，不算占）
        if (at != null && at.block != null
            && !(at instanceof mindustry.world.blocks.ConstructBlock.ConstructBuild)) {
            return "tileOccupied: " + at.block.name + " is already there";
        }
        // 3) 单位够不到
        float dst = arc.math.Mathf.dst(u.x, u.y,
            plan.x * 8f + 4f, plan.y * 8f + 4f);
        if (dst > u.type.buildRange) {
            return "builderTooFar: " + (int) dst + "px away, buildRange "
                 + (int) u.type.buildRange;
        }
        return "unknown";
    }

    /** 清空队伍所有建造单位的待办计划。 */"""

RULES = [
    (OLD, NEW, "stuckSeconds 加归因与分情况 hint"),
    (HELPER_ANCHOR, HELPER, "加 whyStuck()"),
]


def main():
    text = O.read_text(encoding="utf-8")
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
    O.write_text(text, encoding="utf-8")
    print("\nOperations.java：已补 stuckReason")
    return 0


if __name__ == "__main__":
    sys.exit(main())
