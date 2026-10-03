package aiarena;

import arc.math.geom.Vec2;
import mindustry.Vars;
import mindustry.ai.UnitCommand;
import mindustry.ai.UnitStance;
import mindustry.core.World;
import mindustry.game.Team;
import mindustry.gen.Building;
import mindustry.gen.Groups;
import mindustry.gen.Player;
import mindustry.gen.Unit;

/**
 * 指挥类操作。全部在主线程执行。
 *
 * 引擎对「指挥」本身没有任何距离检查（InputHandler.java:331 只判定队伍归属），
 * 所以「被指挥的单位」与「指挥的目标」都必须在己方当前可见范围内 —— 这是
 * DESIGN.md 4.6 里唯一必须自行实现的对等约束。
 *
 * 其余约束（队伍归属、单位是否 CommandAI）由引擎自己把关。
 */
public final class Commander {

    private Commander() {}

    // ---------------------------------------------------------------- helpers

    /**
     * 指挥范围校验：单位与目标都必须对己方可见。
     *
     * 坐标单位必须小心：FogControl.isVisible(team, x, y) 接受的是**世界坐标（像素）**，
     * 而 HTTP 参数给的是**格坐标**。本方法统一接收像素坐标，由调用方负责换算 ——
     * 早期版本在这里把格当像素传，导致相邻 8 格的目标也被判定为不可见。
     *
     * @return null 表示通过，否则返回错误说明
     */
    private static String checkVisible(Team team, float upx, float upy, float tpx, float tpy, boolean checkTarget) {
        if (!Vars.state.rules.fog) return null;   // 无迷雾时不存在「看不见」的问题

        if (!Vars.fogControl.isVisible(team, upx, upy)) {
            return "unit at tile(" + World.toTile(upx) + "," + World.toTile(upy)
                 + ") is not visible to " + team.name;
        }
        if (checkTarget && !Vars.fogControl.isVisible(team, tpx, tpy)) {
            return "target at tile(" + World.toTile(tpx) + "," + World.toTile(tpy)
                 + ") is not visible to " + team.name;
        }
        return null;
    }

    /** 格坐标 → 世界坐标（像素）。 */
    private static float px(float tile) { return tile * Vars.tilesize; }

    /** 把 id 数组解析成单位列表，顺带做队伍归属过滤。 */
    private static arc.struct.Seq<Unit> resolveUnits(Team team, int[] ids) {
        arc.struct.Seq<Unit> out = new arc.struct.Seq<>();
        if (ids == null) return out;
        for (int id : ids) {
            Unit u = Groups.unit.getByID(id);
            if (u != null && u.team == team && !u.dead()) out.add(u);
        }
        return out;
    }

    // ---------------------------------------------------------------- command

    /** 指挥目标类型。 */
    public enum TargetKind { position, unit, building }

    /**
     * 指挥单位前往某处 / 攻击某单位 / 协助某建筑。
     * 对应 ActionType.commandUnits。
     */
    public static Actor.Result command(Team team, int[] unitIds, TargetKind kind,
                                       float tx, float ty, int targetId, boolean queue) {
        if (!Vars.state.isPlaying()) return err(1005, "game not in playing state");

        var units = resolveUnits(team, unitIds);
        if (units.isEmpty()) return err(1002, "no valid units for " + team.name);

        // 范围校验：逐个单位检查是否可见
        for (Unit u : units) {
            String bad = checkVisible(team, u.x, u.y, px(tx), px(ty), kind == TargetKind.position);
            if (bad != null) return err(1005, bad);
        }

        Building buildTarget = null;
        Unit unitTarget = null;
        Vec2 posTarget = null;

        switch (kind) {
            case position -> posTarget = new Vec2(px(tx), px(ty));
            case unit -> {
                unitTarget = Groups.unit.getByID(targetId);
                if (unitTarget == null) return err(1002, "unit id " + targetId + " not found");
                if (unitTarget.team == team) return err(1001, "cannot command attack on own team");
                String bad = checkVisible(team, px(tx), px(ty), unitTarget.x, unitTarget.y, true);
                if (bad != null) return err(1005, bad);
            }
            case building -> {
                var tile = Vars.world.tile((int) tx, (int) ty);
                if (tile == null || tile.build == null) return err(1002, "no building at (" + (int) tx + "," + (int) ty + ")");
                buildTarget = tile.build;
                String bad = checkVisible(team, px(tx), px(ty), buildTarget.x, buildTarget.y, true);
                if (bad != null) return err(1005, bad);
            }
        }

        // 影子 Player 的位置设到目标附近，让引擎自带的距离检查合理
        Player shadow = Shadow.at(team, px(tx), px(ty));

        int[] ids = new int[units.size];
        for (int i = 0; i < ids.length; i++) ids[i] = units.get(i).id;

        mindustry.gen.Call.commandUnits(shadow, ids, buildTarget, unitTarget, posTarget, queue, true);
        return Actor.Result.ok("commanded " + ids.length + " unit(s) to " + kind);
    }

    /**
     * 设置单位的指令（移动/攻击/维修等行为模式）。
     * 对应 ActionType.commandUnits。
     */
    public static Actor.Result setCommand(Team team, int[] unitIds, String commandName) {
        if (!Vars.state.isPlaying()) return err(1005, "game not in playing state");

        UnitCommand cmd = resolveCommand(commandName);
        if (cmd == null) return err(1002, "unknown unit command: " + commandName);

        var units = resolveUnits(team, unitIds);
        if (units.isEmpty()) return err(1002, "no valid units for " + team.name);

        for (Unit u : units) {
            String bad = checkVisible(team, u.x, u.y, u.x, u.y, false);
            if (bad != null) return err(1005, bad);
        }

        Player shadow = Shadow.of(team);
        int[] ids = new int[units.size];
        for (int i = 0; i < ids.length; i++) ids[i] = units.get(i).id;

        mindustry.gen.Call.setUnitCommand(shadow, ids, cmd);
        return Actor.Result.ok("set command " + cmd.name + " on " + ids.length + " unit(s)");
    }

    /** 设置单位的姿态开关（如「保持距离」「自动攻击」）。 */
    public static Actor.Result setStance(Team team, int[] unitIds, String stanceName, boolean enable) {
        if (!Vars.state.isPlaying()) return err(1005, "game not in playing state");

        UnitStance stance = resolveStance(stanceName);
        if (stance == null) return err(1002, "unknown unit stance: " + stanceName);

        var units = resolveUnits(team, unitIds);
        if (units.isEmpty()) return err(1002, "no valid units for " + team.name);

        for (Unit u : units) {
            String bad = checkVisible(team, u.x, u.y, u.x, u.y, false);
            if (bad != null) return err(1005, bad);
        }

        Player shadow = Shadow.of(team);
        int[] ids = new int[units.size];
        for (int i = 0; i < ids.length; i++) ids[i] = units.get(i).id;

        mindustry.gen.Call.setUnitStance(shadow, ids, stance, enable);
        return Actor.Result.ok("set stance " + stance.name + "=" + enable + " on " + ids.length + " unit(s)");
    }

    /**
     * 指挥建筑（炮塔等）攻击目标。
     * 对应 ActionType.commandBuilding。
     */
    public static Actor.Result commandBuilding(Team team, int[] buildingIds, float tx, float ty) {
        if (!Vars.state.isPlaying()) return err(1005, "game not in playing state");

        if (buildingIds == null || buildingIds.length == 0) return err(1001, "no building ids given");

        // 建筑坐标从 tile 反查（buildingIds 用 id 而非坐标，这里用第一座建筑定位做范围校验）
        var buildings = new arc.struct.Seq<Building>();
        for (int id : buildingIds) {
            Building b = null;
            for (Building cand : Groups.build) { if (cand.id == id) { b = cand; break; } }
            if (b != null && b.team == team) buildings.add(b);
        }
        if (buildings.isEmpty()) return err(1002, "no valid buildings for " + team.name);

        for (Building b : buildings) {
            String bad = checkVisible(team, b.x, b.y, px(tx), px(ty), true);
            if (bad != null) return err(1005, bad);
        }

        Player shadow = Shadow.at(team, px(tx), px(ty));
        mindustry.gen.Call.commandBuilding(shadow, buildingIds, new Vec2(px(tx), px(ty)));
        return Actor.Result.ok("commanded " + buildingIds.length + " building(s)");
    }

    // ---------------------------------------------------------------- control

    /**
     * 进入 / 退出单位。
     *
     * 对应玩家按 Ctrl 接管单位的操作。引擎在三条路径上都要求
     * unit.team == player.team()（InputHandler.java:783 / :1006 / :2149），
     * 影子 Player 的队伍与 AI 一致，因此天然满足。
     */
    public static Actor.Result control(Team team, int unitId, boolean enter) {
        if (!Vars.state.isPlaying()) return err(1005, "game not in playing state");

        Player shadow = Shadow.of(team);

        if (!enter) {
            if (shadow.unit() != null) shadow.clearUnit();
            return Actor.Result.ok("released control");
        }

        Unit u = Groups.unit.getByID(unitId);
        if (u == null) return err(1002, "unit id " + unitId + " not found");
        if (u.team != team) return err(1005, "unit belongs to " + u.team.name);

        String bad = checkVisible(team, u.x, u.y, u.x, u.y, false);
        if (bad != null) return err(1005, bad);

        Shadow.at(team, u);
        mindustry.gen.Call.unitControl(shadow, u);
        return Actor.Result.ok("controlling " + u.type.name + " id=" + unitId);
    }

    /** 被控制的单位向目标点移动。仅在已进入单位时有效。 */
    public static Actor.Result moveControl(Team team, float tx, float ty) {
        if (!Vars.state.isPlaying()) return err(1005, "game not in playing state");

        Player shadow = Shadow.of(team);
        Unit u = shadow.unit();
        if (u == null) return err(1005, "not controlling any unit");

        String bad = checkVisible(team, u.x, u.y, px(tx), px(ty), true);
        if (bad != null) return err(1005, bad);

        // 玩家操纵时，移动是「在镜头内点击地面」—— 这里同样要求目标可见
        u.movePref(new Vec2(px(tx) - u.x, px(ty) - u.y).nor());
        return Actor.Result.ok("moving controlled unit toward (" + (int) tx + "," + (int) ty + ")");
    }

    /** 被控制的单位朝目标方向开火。 */
    public static Actor.Result fireControl(Team team, float tx, float ty, boolean on) {
        if (!Vars.state.isPlaying()) return err(1005, "game not in playing state");

        Player shadow = Shadow.of(team);
        Unit u = shadow.unit();
        if (u == null) return err(1005, "not controlling any unit");

        String bad = checkVisible(team, u.x, u.y, px(tx), px(ty), true);
        if (bad != null) return err(1005, bad);

        float angle = arc.math.Angles.angle(u.x, u.y, px(tx), px(ty));
        u.aimX = px(tx);
        u.aimY = px(ty);
        u.rotation = angle;
        if (on) u.isShooting = true;

        String msg = "aiming at (" + ((int) tx) + "," + ((int) ty) + ") shooting=" + u.isShooting;
        return Actor.Result.ok(msg);
    }

    // ---------------------------------------------------------------- inventory

    /** 从建筑取物品。引擎自带 player.within(build, 220f) 检查。 */
    public static Actor.Result requestItem(Team team, int bx, int by, String itemName, int amount) {
        if (!Vars.state.isPlaying()) return err(1005, "game not in playing state");

        var tile = Vars.world.tile(bx, by);
        if (tile == null || tile.build == null) return err(1002, "no building at (" + bx + "," + by + ")");

        mindustry.type.Item item = Vars.content.item(itemName);
        if (item == null) return err(1002, "unknown item: " + itemName);

        String bad = checkVisible(team, px(bx), px(by), px(bx), px(by), false);
        if (bad != null) return err(1005, bad);

        Player shadow = Shadow.at(team, tile.build);
        mindustry.gen.Call.requestItem(shadow, tile.build, item, amount);
        return Actor.Result.ok("requested " + amount + " " + item.name);
    }

    /** 把单位库存存入建筑。 */
    public static Actor.Result transferInventory(Team team, int bx, int by) {
        if (!Vars.state.isPlaying()) return err(1005, "game not in playing state");

        var tile = Vars.world.tile(bx, by);
        if (tile == null || tile.build == null) return err(1002, "no building at (" + bx + "," + by + ")");

        String bad = checkVisible(team, px(bx), px(by), px(bx), px(by), false);
        if (bad != null) return err(1005, bad);

        Player shadow = Shadow.at(team, tile.build);
        mindustry.gen.Call.transferInventory(shadow, tile.build);
        return Actor.Result.ok("transferred inventory to " + tile.block().name);
    }

    // ---------------------------------------------------------------- resolve

    /**
     * 引擎里全部可用的单位指令。
     *
     * UnitCommand 是 MappableContent，没有 all 数组 —— 它只暴露静态字段，
     * 而且这些字段由 init() 赋值，所以必须在运行时读取，不能在静态初始化块里缓存。
     */
    private static UnitCommand[] allCommands() {
        return new UnitCommand[]{
            UnitCommand.moveCommand, UnitCommand.repairCommand, UnitCommand.rebuildCommand,
            UnitCommand.assistCommand, UnitCommand.mineCommand, UnitCommand.enterPayloadCommand,
            UnitCommand.loadUnitsCommand, UnitCommand.loadBlocksCommand,
            UnitCommand.unloadPayloadCommand, UnitCommand.loopPayloadCommand,
        };
    }

    /** 引擎里全部可用的单位姿态。同上，静态字段在 init() 时赋值。 */
    private static UnitStance[] allStances() {
        return new UnitStance[]{
            UnitStance.stop, UnitStance.holdFire, UnitStance.pursueTarget,
            UnitStance.patrol, UnitStance.ram, UnitStance.boost,
            UnitStance.holdPosition, UnitStance.mineAuto,
        };
    }

    private static UnitCommand resolveCommand(String name) {
        if (name == null || name.isEmpty()) return null;
        for (UnitCommand c : allCommands()) {
            if (c != null && c.name != null && c.name.equalsIgnoreCase(name)) return c;
        }
        return null;
    }

    private static UnitStance resolveStance(String name) {
        if (name == null || name.isEmpty()) return null;
        for (UnitStance s : allStances()) {
            if (s != null && s.name != null && s.name.equalsIgnoreCase(name)) return s;
        }
        return null;
    }

    /** 列出可用的指令与姿态名，供 /content 端点使用。 */
    public static String[] commandNames() {
        arc.struct.Seq<String> out = new arc.struct.Seq<>();
        for (UnitCommand c : allCommands()) if (c != null && c.name != null) out.add(c.name);
        return out.toArray(String.class);
    }

    public static String[] stanceNames() {
        arc.struct.Seq<String> out = new arc.struct.Seq<>();
        for (UnitStance s : allStances()) if (s != null && s.name != null) out.add(s.name);
        return out.toArray(String.class);
    }

    private static Actor.Result err(int code, String msg) { return Actor.Result.err(code, msg); }
}
