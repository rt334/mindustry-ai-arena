#!/usr/bin/env python3
"""A1/A2 输出端 + A4（/queue 给坐标）+ A3（/place 三种失败码分开报）。

A3 的动机（FEATURE-REQUESTS 原文）：
    「/place 返回成功，但方块永远不出现……同一次会话里我对 (40,97)、(41,97)、
      (69,99)、(85,110) 反复重试过 3~4 次，全部『成功』，全部不出现。」
    无法区分「队列忙」/「位置不可建」/「footprint 冲突」，只能盲重试。

这里在入队前做一次预检，把三种原因分成三个码：
    1004 queue_full      该建造单位的计划队列已满（引擎上限 60）
    1008 place_blocked   footprint 被别的建筑或固体地形占住（挪一格就行）
    1009 place_invalid   引擎 validPlace 拒绝，非占用所致（地形/规则/权限）

预检用的是引擎自己的 Build.validPlace（Build.java:163），不是复刻它的规则。
"""
import pathlib
import sys

H = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\HttpApi.java")
O = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Operations.java")
A = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Actor.java")

# ---------------------------------------------------------------- HttpApi

HTTP_OLD = """            if (b.config != null) o.put("config", b.config);
            if (b.constructing) o.put("constructing", true).put("buildProgress", b.buildProgress);
            sb.append(o.toString());"""

HTTP_NEW = """            if (b.config != null) o.put("config", b.config);
            if (b.constructing) o.put("constructing", true).put("buildProgress", b.buildProgress);

            // 物流接口：这一格能从哪收货、把货推到哪。
            // 只暴露**规则**，不暴露结论 —— 说清楚接口在哪，不替 AI 判断这条链会不会堵。
            if (b.acceptsFrom != null) o.putRaw("acceptsFrom", points(b.acceptsFrom));
            if (b.sendsTo != null) o.putRaw("sendsTo", points(b.sendsTo));

            sb.append(o.toString());"""

HTTP_HELPER_OLD = """    static String visibleBuildings(Snapshot.State s, int myTeam, boolean admin) {"""

HTTP_HELPER_NEW = """    /** Point2.pack 的数组 → `[[x,y],...]`。 */
    static String points(int[] packed) {
        StringBuilder s = new StringBuilder("[");
        for (int i = 0; i < packed.length; i++) {
            if (i > 0) s.append(',');
            arc.math.geom.Point2 pt = arc.math.geom.Point2.unpack(packed[i]);
            s.append('[').append(pt.x).append(',').append(pt.y).append(']');
        }
        return s.append(']').toString();
    }

    static String visibleBuildings(Snapshot.State s, int myTeam, boolean admin) {"""

# ---------------------------------------------------------------- Operations

QUEUE_OLD = """    /** 查看队伍所有建造单位的待办计划数。 */
    public static String queueReport(Team team) {
        StringBuilder sb = new StringBuilder("[");
        boolean first = true;
        for (Unit u : mindustry.gen.Groups.unit) {
            if (u == null || u.team != team || !u.canBuild()) continue;
            if (!first) sb.append(',');
            first = false;
            int n = u.plans == null ? 0 : u.plans.size;
            sb.append(new Json.Obj().put("unit", u.id).put("type", u.type.name).put("plans", n).toString());
        }
        return sb.append(']').toString();
    }"""

QUEUE_NEW = """    /**
     * 查看队伍所有建造单位的待办计划。
     *
     * 早先只给一个 plans 计数，AI 拿不到坐标 —— 想加速建造就得自己维护一份
     * pending 清单，而丢单会让清单和服务端实际状态对不上。现在把每个计划摊开：
     * 坐标、目标方块、是不是拆除，以及**该格已经在施工时的进度** ——
     * 有 progress 才能定位「卡住不动的那一个」。
     */
    public static String queueReport(Team team) {
        StringBuilder sb = new StringBuilder("[");
        boolean first = true;
        for (Unit u : mindustry.gen.Groups.unit) {
            if (u == null || u.team != team || !u.canBuild()) continue;
            if (!first) sb.append(',');
            first = false;

            StringBuilder plans = new StringBuilder("[");
            boolean pf = true;
            int n = 0;
            if (u.plans != null) {
                n = u.plans.size;
                for (mindustry.gen.BuildPlan plan : u.plans) {
                    if (plan == null) continue;
                    if (!pf) plans.append(',');
                    pf = false;
                    Json.Obj po = new Json.Obj()
                        .put("x", plan.x).put("y", plan.y)
                        .put("breaking", plan.breaking);
                    if (plan.block != null) po.put("block", plan.block.name);
                    // 只有已在施工的格子才有进度：0 且长时间不涨 = 卡住
                    mindustry.gen.Building tb = Vars.world.build(plan.x, plan.y);
                    if (tb instanceof mindustry.world.blocks.ConstructBlock.ConstructBuild cb) {
                        po.put("constructing", true).put("progress", cb.progress);
                    }
                    plans.append(po.toString());
                }
            }
            plans.append(']');

            sb.append(new Json.Obj()
                .put("unit", u.id).put("type", u.type.name).put("plans", n)
                .putRaw("planList", plans.toString())
                .toString());
        }
        return sb.append(']').toString();
    }"""

# ---------------------------------------------------------------- Actor

ACTOR_OLD = """        // ---- 约束 3：入队，交给引擎 ----
        BuildPlan plan = (config == null)"""

ACTOR_NEW = """        // ---- 约束 3：预检。不给原因的话 AI 只能盲重试 ----
        //
        // 三种失败必须分开报，否则「place 成功但方块不出现」无法归因：
        //   1004 队列满      —— 等一等就行
        //   1008 footprint 被占 —— 挪一格或先拆
        //   1009 位置不合法   —— 换地方，重试没有意义
        if (builder.plans != null && builder.plans.size >= Operations.MAX_PLANS_PER_UNIT) {
            Json.Obj e = new Json.Obj();
            if (mat != null) e.putRaw("materials", mat.toString());
            e.put("pendingPlans", builder.plans.size)
             .put("maxPlans", Operations.MAX_PLANS_PER_UNIT)
             .put("suggestion", "wait for the builder to drain its queue, or POST /queue?clear=true");
            return Result.err(1004, "builder " + builder.id + " queue is full: "
                              + builder.plans.size + " plans (max "
                              + Operations.MAX_PLANS_PER_UNIT + ")", e);
        }

        // 用引擎自己的判定，不复刻它的规则（含地形、权限、coreZone 等全部条件）。
        // checkVisible 传 false —— 可见性上面已经单独查过了。
        if (!mindustry.world.Build.validPlace(block, team, x, y, rotation, false)) {
            int size = block.size;
            int hx = -1, hy = -1;
            for (int dx = 0; dx < size && hx < 0; dx++) {
                for (int dy = 0; dy < size; dy++) {
                    Tile t = Vars.world.tile(x + dx, y + dy);
                    if (t == null) continue;
                    if (t.build != null || t.solid()) { hx = x + dx; hy = y + dy; break; }
                }
            }
            Json.Obj e = new Json.Obj();
            if (mat != null) e.putRaw("materials", mat.toString());
            e.put("block", block.name).put("size", size)
             .put("anchor", "[" + x + "," + y + "]");
            if (hx >= 0) {
                e.putRaw("conflictAt", "[" + hx + "," + hy + "]")
                 .put("suggestion", "footprint is occupied; shift the anchor or /break that tile");
                return Result.err(1008, "footprint of " + block.name + " (" + size + "x" + size
                                  + ") at (" + x + "," + y + ") is blocked by the tile at ("
                                  + hx + "," + hy + ")", e);
            }
            e.put("suggestion", "engine rejected this placement (terrain, rules or team permission)");
            return Result.err(1009, "placement invalid at (" + x + "," + y + ") for "
                              + block.name, e);
        }

        // ---- 约束 4：入队，交给引擎 ----
        BuildPlan plan = (config == null)"""

JOBS = [
    (H, [(HTTP_OLD, HTTP_NEW, "visibleBuildings 输出 acceptsFrom / sendsTo"),
         (HTTP_HELPER_OLD, HTTP_HELPER_NEW, "加 points() 辅助")]),
    (O, [(QUEUE_OLD, QUEUE_NEW, "queueReport 带坐标与进度")]),
    (A, [(ACTOR_OLD, ACTOR_NEW, "place 加预检：队列满 / footprint 被占 / 位置不合法")]),
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
    print("三个文件已更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
