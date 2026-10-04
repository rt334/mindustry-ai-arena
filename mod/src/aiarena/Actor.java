package aiarena;

import arc.struct.Queue;
import mindustry.Vars;
import mindustry.entities.units.BuildPlan;
import mindustry.gen.Building;
import mindustry.gen.Groups;
import mindustry.gen.Unit;
import mindustry.world.Block;
import mindustry.world.Tile;
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

        private Result(boolean ok, int code, String message) {
            this.ok = ok; this.code = code; this.message = message;
        }
        static Result ok(String msg)      { return new Result(true, 0, msg); }
        static Result err(int c, String m){ return new Result(false, c, m); }
    }

    // ---------------------------------------------------------------- place

    /**
     * 下单放置。注意：返回成功仅代表「计划已入队」，建造实际完成需要时间
     * （受单位 buildSpeed 与移动速度约束），AI 需通过 /map 或 /state 观察结果。
     */
    public static Result place(Team team, int x, int y, String blockName, int rotation, Object config) {
        if (!Vars.state.isPlaying()) return Result.err(1005, "game not in playing state");
        if (Vars.world.tile(x, y) == null) return Result.err(1003, "coordinates out of bounds");

        // ---- 约束 1：目标格必须在己方当前可见范围内 ----
        if (Vars.state.rules.fog && !Vars.fogControl.isVisibleTile(team, x, y)) {
            return Result.err(1005, "target tile is not visible to team " + team.name);
        }

        Block block = resolveBlock(blockName);
        if (block == null) return Result.err(1002, "unknown block: " + blockName);

        // ---- 约束 2：必须有建造单位 ----
        Unit builder = findBuilder(team);
        if (builder == null) {
            return Result.err(1005, "team " + team.name + " has no builder unit");
        }

        // ---- 约束 3：入队，交给引擎 ----
        BuildPlan plan = (config == null)
            ? new BuildPlan(x, y, rotation, block)
            : new BuildPlan(x, y, rotation, block, config);

        builder.addBuild(plan);
        Queue<BuildPlan> q = builder.plans;
        return Result.ok("queued " + block.name + " at (" + x + "," + y
                         + ") by " + builder.type.name + "; pending plans=" + (q == null ? 0 : q.size));
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
