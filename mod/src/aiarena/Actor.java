package aiarena;

import arc.math.Mathf;
import arc.struct.Queue;
import mindustry.Vars;
import mindustry.entities.units.BuildPlan;
import mindustry.gen.Building;
import mindustry.gen.Groups;
import mindustry.gen.Player;
import mindustry.gen.Unit;
import mindustry.type.ItemStack;
import mindustry.world.Block;
import mindustry.world.Tile;
import mindustry.world.blocks.ConstructBlock.ConstructBuild;
import mindustry.game.Team;

/**
 * 写操作执行器。全部方法必须在游戏主线程调用（由 HttpApi 经 Core.app.post 投递）。
 *
 * 建造路径遵循 DESIGN.md 4.5 的三步：
 *
 *   1) fogControl.isVisibleTile(team, x, y)        ← 对称于「玩家点得到」
 *   2) 找到队伍的建造单位（canBuild()）
 *   3) builder.addBuild(new BuildPlan(...))        ← 之后引擎全自动
 *
 * 引擎随后自动完成：finalPlaceDst 范围筛选 → 单位走过去 → validPlace
 * → hasAll 资源扣除 → buildCounter 速度控制 → Call.beginPlace 网络广播
 * → ConstructBlock 施工进度。
 *
 * 关键：绝不能绕过 BuilderComp 直接调 Build.beginPlace —— 那条路径不检查
 * 资源与范围，会让 AI 凭空建造。
 */
public final class Actor {

    private Actor() {}

    public static final class Result {
        public final boolean ok;
        public final int code;
        public final String message;
        /** 结构化附加信息（材料清单等）。null 表示没有。 */
        public final Json.Obj extra;

        private Result(boolean ok, int code, String message, Json.Obj extra) {
            this.ok = ok; this.code = code; this.message = message; this.extra = extra;
        }
        static Result ok(String msg)                 { return new Result(true, 0, msg, null); }
        static Result ok(String msg, Json.Obj extra) { return new Result(true, 0, msg, extra); }
        static Result err(int c, String m)           { return new Result(false, c, m, null); }
        static Result err(int c, String m, Json.Obj extra) { return new Result(false, c, m, extra); }
    }

    // ---------------------------------------------------------------- place

    /**
     * 下单放置。注意：返回成功仅代表「计划已入队」，建造实际完成需要时间
     * （受单位 buildSpeed 与移动速度约束），AI 需通过 /map 或 /state 观察结果。
     *
     * 响应里始终附带 materials 字段（见 materialReport）：AI 拿不到材料时
     * 不必再靠「反复重试 + 猜」来判断原因。
     */
    public static Result place(Team team, int x, int y, String blockName, int rotation, Object config) {
        return place(team, x, y, blockName, rotation, config, -1);
    }

    public static Result place(Team team, int x, int y, String blockName, int rotation, Object config, int unitId) {
        if (!Vars.state.isPlaying()) return Result.err(1005, "game not in playing state");
        if (Vars.world.tile(x, y) == null) return Result.err(1003, "coordinates out of bounds");

        // ---- 约束 1：目标格必须在己方当前可见范围内 ----
        if (Vars.state.rules.fog && !Vars.fogControl.isVisibleTile(team, x, y)) {
            return Result.err(1005, "target tile is not visible to team " + team.name);
        }

        Block block = resolveBlock(blockName);
        if (block == null) return Result.err(1002, "unknown block: " + blockName);

        Json.Obj mat = materialReport(team, block);

        // ---- 约束 2：必须有建造单位（优先用被接管的、或显式指定的那一个）----
        Unit builder = findBuilder(team, unitId);
        if (builder == null) {
            Json.Obj e = new Json.Obj();
            if (mat != null) e.putRaw("materials", mat.toString());
            return Result.err(1005, "team " + team.name + " has no builder unit"
                              + (unitId > 0 ? " (requested id=" + unitId + ")" : ""), e);
        }

        // ---- 约束 3：预检。不给原因的话 AI 只能盲重试 ----
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
        BuildPlan plan = (config == null)
            ? new BuildPlan(x, y, rotation, block)
            : new BuildPlan(x, y, rotation, block, config);

        // 「转移建造目标」：对同一格重复下单会替换掉原有计划 ——
        // BuilderComp.addBuild 会按 (x,y) 找到旧计划并移除，且若该格已在施工
        // （ConstructBuild）则新计划继承其 progress。这里把「被替换掉的是谁」
        // 以及「进度是否继承」显式报出来，否则 AI 无法区分「新建」和「改建」。
        String previous = null;
        float inherited = 0f;
        Tile target = Vars.world.tile(x, y);
        if (target != null && target.build instanceof ConstructBuild cons) {
            previous = cons.current == null ? cons.block.name : cons.current.name;
            inherited = cons.progress;
        } else if (target != null && target.build != null && target.build.block != null) {
            previous = target.build.block.name;
        }
        for (BuildPlan pl : builder.plans) {
            if (pl.x == x && pl.y == y && pl.block != null) { previous = pl.block.name; break; }
        }

        builder.addBuild(plan);
        Queue<BuildPlan> q = builder.plans;

        Json.Obj builderInfo = new Json.Obj()
            .put("id", builder.id)
            .put("type", builder.type.name);
        Json.Obj extra = new Json.Obj()
            .putRaw("builder", builderInfo.toString())
            .put("pendingPlans", q == null ? 0 : q.size)
            .put("mode", previous == null ? "new" : "transfer");
        if (previous != null) {
            extra.put("previousBlock", previous);
            extra.put("inheritedProgress", inherited);
        }
        if (mat != null) extra.putRaw("materials", mat.toString());

        String verb = previous == null
            ? "queued "
            : "transfer target to ";
        return Result.ok(verb + block.name + " at (" + x + "," + y
                         + ") by " + builder.type.name
                         + (previous == null ? "" : " (was " + previous + ")")
                         + "; pending plans=" + (q == null ? 0 : q.size),
                         extra);
    }

    /**
     * 该方块的建造材料 vs 当前核心库存。
     *
     * 动机：/place 以前只回「queued ...」，建造迟迟不出现时 AI 无从区分
     * 「队列忙」「位置不可建」「材料不够」——实测里这是最大的盲区之一。
     * 引擎自身的卡住判定（BuilderComp）就是查 core.items.has(requirements)，
     * 这里把同一份信息提前暴露出来。
     *
     * 返回 { adequate, requirements:[{item, need, have, ok, short}], missing:[...] }
     * 无材料需求时返回 null。
     */
    public static Json.Obj materialReport(Team team, Block block) {
        if (block == null || block.requirements == null || block.requirements.length == 0) return null;

        float mult = Vars.state.rules.buildCostMultiplier;
        Building core = team.core();
        Json.Obj items = new Json.Obj();
        Json.Obj arr = new Json.Obj();
        int idx = 0;
        boolean adequate = true;

        for (ItemStack req : block.requirements) {
            if (req == null || req.item == null) continue;
            int need = Math.max(1, Mathf.round(req.amount * mult));
            int have = core == null ? 0 : core.items.get(req.item);
            boolean ok = have >= need;
            if (!ok) adequate = false;
            Json.Obj one = new Json.Obj()
                .put("item", req.item.name)
                .put("need", need)
                .put("have", have)
                .put("ok", ok)
                .put("short", ok ? 0 : need - have);
            arr.putRaw(String.valueOf(idx++), one.toString());
        }

        Json.Obj out = new Json.Obj()
            .put("adequate", adequate)
            .putRaw("requirements", arr.toString());
        if (!adequate) out.put("coreCopper", core == null ? 0 : core.items.get(mindustry.content.Items.copper));
        return out;
    }


    // ---------------------------------------------------------------- break

    /** 下单拆除。同样只是入队，由单位走过去执行。 */
    public static Result breakBlock(Team team, int x, int y) {
        if (!Vars.state.isPlaying()) return Result.err(1005, "game not in playing state");

        Tile tile = Vars.world.tile(x, y);
        if (tile == null) return Result.err(1003, "coordinates out of bounds");
        if (tile.block() == null || tile.block() == mindustry.content.Blocks.air) {
            return Result.err(1002, "no block at (" + x + "," + y + ")");
        }

        if (Vars.state.rules.fog && !Vars.fogControl.isVisibleTile(team, x, y)) {
            return Result.err(1005, "target tile is not visible to team " + team.name);
        }

        Unit builder = findBuilder(team);
        if (builder == null) {
            return Result.err(1005, "team " + team.name + " has no builder unit");
        }

        BuildPlan plan = new BuildPlan(x, y);   // 两参数构造器自动 breaking = true
        builder.addBuild(plan);
        return Result.ok("queued break of " + tile.block().name + " at (" + x + "," + y + ")");
    }

    // ---------------------------------------------------------------- config

    /**
     * 修改建筑配置。走 InputHandler.tileConfig（@Remote，targets = Loc.both）。
     * 注意服务器侧 player 传 null 时 allowAction 会无条件放行，
     * 所以可见性校验必须在这里自己做。
     */
    public static Result configure(Team team, int x, int y, String value) {
        if (!Vars.state.isPlaying()) return Result.err(1005, "game not in playing state");

        Tile tile = Vars.world.tile(x, y);
        if (tile == null || tile.build == null) {
            return Result.err(1002, "no building at (" + x + "," + y + ")");
        }
        Building build = tile.build;
        if (build.team != team) {
            return Result.err(1005, "building at (" + x + "," + y + ") belongs to " + build.team.name);
        }
        if (Vars.state.rules.fog && !Vars.fogControl.isVisibleTile(team, x, y)) {
            return Result.err(1005, "target tile is not visible to team " + team.name);
        }

        try {
            Object resolved = resolveConfigValue(build, value);
            build.configureAny(resolved);
            return Result.ok("configured " + build.block.name + " at (" + x + "," + y + ")"
                             + " with " + describeConfig(resolved));
        } catch (Throwable t) {
            return Result.err(1500, "configure failed: " + t);
        }
    }

    /**
     * 把 HTTP 传来的字符串解析成引擎认识的配置对象。
     *
     * 不能直接把字符串丢给 configureAny：BuildingComp.configured() 是按
     * value.getClass() 去查 block.configurations 的，而 UnitFactory 注册的是
     * UnitType.class / Integer.class —— 传 String 一律匹配不上，配置会静默失效。
     *
     * 所以按方块**声明的配置类型**来决定怎么解析：
     *   声明了 UnitType  -> 按单位名解析（工厂选产线就是这个）
     *   声明了 Integer   -> 按序号解析
     *   其它             -> 原样传字符串（分拣器之类）
     */
    private static Object resolveConfigValue(Building build, String value) {
        var configs = build.block.configurations;

        if (configs.containsKey(mindustry.type.UnitType.class)) {
            var ut = Vars.content.unit(value.trim());
            if (ut != null) return ut;
            // 工厂也支持用 plan 序号配置
            try { return Integer.parseInt(value.trim()); } catch (NumberFormatException ignored) {}
        }

        if (configs.containsKey(Integer.class)) {
            try { return Integer.parseInt(value.trim()); } catch (NumberFormatException ignored) {}
        }

        if (configs.containsKey(mindustry.type.Item.class)) {
            var it = Vars.content.item(value.trim());
            if (it != null) return it;
        }

        if (configs.containsKey(Block.class)) {
            var bl = Vars.content.block(value.trim());
            if (bl != null) return bl;
        }

        return value;
    }

    private static String describeConfig(Object resolved) {
        if (resolved instanceof mindustry.type.UnitType ut) return "unit=" + ut.name;
        if (resolved instanceof mindustry.type.Item it) return "item=" + it.name;
        if (resolved instanceof Block b) return "block=" + b.name;
        return resolved == null ? "null" : String.valueOf(resolved);
    }

    // ---------------------------------------------------------------- helpers

    private static Unit findBuilder(Team team) {
        return findBuilder(team, -1);
    }

    /**
     * 找执行建造的单位。选择顺序：
     *
     *   1) 显式指定的 unitId（如果它属于本队且 canBuild）
     *   2) 该队当前「被接管」的单位（对应玩家的双击切换 —— /control?op=enter 之后
     *      就应该由那一个单位来建，否则接管对建造毫无意义）
     *   3) 否则退回「第一个 canBuild 的单位」（旧行为，保持兼容）
     *
     * 第 2 条是这版新增的：以前无论接管了谁，/place 都随机挑一个 canBuild 的单位，
     * 于是「切换建造对象」这个动作在建造路径上完全不起作用。
     */
    private static Unit findBuilder(Team team, int unitId) {
        if (unitId > 0) {
            Unit u = Groups.unit.getByID(unitId);
            if (u != null && u.isValid() && !u.dead() && u.team == team && u.canBuild()) return u;
        }

        Player shadow = Shadow.of(team);
        if (shadow != null) {
            Unit u = shadow.unit();
            if (u != null && u.isValid() && !u.dead() && u.team == team && u.canBuild()) return u;
        }

        for (Unit u : Groups.unit) {
            if (u != null && u.isValid() && u.team == team && u.canBuild() && !u.dead()) return u;
        }
        return null;
    }

    private static Block resolveBlock(String name) {
        if (name == null || name.isEmpty()) return null;
        Block b = Vars.content.block(name);
        if (b != null && b != mindustry.content.Blocks.air) return b;
        return null;
    }
}
