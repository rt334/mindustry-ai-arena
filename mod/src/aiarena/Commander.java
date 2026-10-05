package aiarena;

import arc.math.Mathf;
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

        // ⚠ 光靠上面那条 RPC 没用。它是喂给 CommandAI 的，而本竞技场里
        // **每个单位都被影子 Player 持有**（controller=Player#NNN）——
        // 玩家持有的单位不理会 AI 指挥。实测同目标同单位：
        //   /command?action=move → 应答成功，位移 0.00 格
        //   /control?op=order    → 位移 23.14 格
        // 差别在于 order 走 moveOrders，由 tickMoveOrders 每帧直接改 u.vel
        // 与朝向，绕过控制器。位置类指令这里额外挂上它。
        if (kind == TargetKind.position) {
            long until = System.currentTimeMillis() + 20_000L;
            for (int id : ids) moveOrders.put(id, new MoveOrder(team, tx, ty, until));
        }
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

    /**
     * 持续移动指令 —— 模拟玩家按住 WASD。
     *
     * 为什么不能只调一次 movePref：`Unit.movePref(Vec2)` 只是设置**单帧**的
     * moveX/moveY，下一帧就被 `PlayerComp.update()` 按「当前输入」覆盖回 0。
     * 实测调一次之后单位纹丝不动。
     *
     * 所以这里把目标存下来，由主循环每帧重新施加，直到抵达（或超时）。
     *
     * 为什么走这条路而不是 CommandAI：PvP 里队伍的单位控制器是 `Player`
     * （影子玩家持有），`unit.isAI()` 为 false，`Call.unitControl` 会抛
     * `ValidateException: Player attempted to control invalid unit`。
     * 玩家本来也只能用 WASD 移动自己的单位 —— 这里就是等价物。
     */
    public static final class MoveOrder {
        public final Team team;
        public final float tx, ty;          // 地块坐标
        public final long expiresAt;
        public MoveOrder(Team team, float tx, float ty, long expiresAt) {
            this.team = team; this.tx = tx; this.ty = ty; this.expiresAt = expiresAt;
        }
    }

    private static final java.util.Map<Integer, MoveOrder> moveOrders = new java.util.HashMap<>();

    /** 给某队下达持续移动指令。 */
    public static Actor.Result order(Team team, int unitId, float tx, float ty) {
        if (!Vars.state.isPlaying()) return err(1005, "game not in playing state");

        Unit u = Groups.unit.getByID(unitId);
        if (u == null) return err(1002, "unit id " + unitId + " not found");
        if (u.team != team) return err(1005, "unit belongs to " + u.team.name);

        String bad = checkVisible(team, u.x, u.y, px(tx), px(ty), false);
        if (bad != null) return err(1005, bad);

        // 20 秒走不到就放弃，避免单位永远被一条指令牵着
        moveOrders.put(unitId, new MoveOrder(team, tx, ty, System.currentTimeMillis() + 20_000L));
        return Actor.Result.ok("moving " + u.type.name + " id=" + unitId + " toward (" + (int) tx + "," + (int) ty + ")");
    }

    /** 取消某单位的移动指令。 */
    public static Actor.Result stopOrder(Team team, int unitId) {
        moveOrders.remove(unitId);
        return Actor.Result.ok("stopped unit " + unitId);
    }

    /** 移动指令施加次数，用于判断主循环有没有真的在跑。 */
    private static volatile long tickCount = 0;
    private static volatile long lastApplyCount = 0;

    public static long tickCount() { return tickCount; }
    public static long applyCount() { return lastApplyCount; }

    /**
     * 直接设定速度并转向目标 —— 比 movePref 强硬。
     *
     * `movePref` 对非 omni 单位走 `rotateMove`，而它是**沿当前朝向**移动的
     * （`Tmp.v2.trns(rotation, len)`），朝反了就往反方向走。这里同时把
     * rotation 掰向目标，并直接覆写 vel。
     */
    public static Actor.Result warp(Team team, int unitId, float tx, float ty) {
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
        u.x = px(tx); u.y = px(ty);
        // 挂一个逐帧探针：主循环里发现位置变了就记下来
        warpProbe.put(unitId, new Probe(u.x, u.y, System.currentTimeMillis() + 3000L, 0));
        return Actor.Result.ok("warped to (" + (int) tx + "," + (int) ty
            + "); live now world=(" + (int) u.x + "," + (int) u.y + ")"
            + " tile=(" + (int) (u.x / 8f) + "," + (int) (u.y / 8f) + ")");
    }

    /** 逐帧位置探针：记录传送后位置被谁改回去了。 */
    private static final class Probe {
        final float setX, setY;
        final long expiresAt;
        int revertedAt = -1;
        float revertX, revertY;
        int framesSeen = 0;
        Probe(float setX, float setY, long expiresAt, int framesSeen) {
            this.setX = setX; this.setY = setY; this.expiresAt = expiresAt; this.framesSeen = framesSeen;
        }
    }
    private static final java.util.Map<Integer, Probe> warpProbe = new java.util.HashMap<>();

    public static String probeJson() {
        StringBuilder sb = new StringBuilder("[");
        boolean f = true;
        for (var e : warpProbe.entrySet()) {
            Probe p = e.getValue();
            if (!f) sb.append(',');
            f = false;
            sb.append(new Json.Obj().put("unit", e.getKey())
                .put("setX", p.setX).put("setY", p.setY)
                .put("framesSeen", p.framesSeen)
                .put("revertedAtFrame", p.revertedAt)
                .put("revertX", p.revertX).put("revertY", p.revertY)
                .toString());
        }
        return sb.append(']').toString();
    }

    /** 读某个单位的**实时**状态（不走快照）。 */
    public static Actor.Result livePos(Team team, int unitId) {
        Unit u = Groups.unit.getByID(unitId);
        if (u == null) return err(1002, "unit id " + unitId + " not found");
        return Actor.Result.ok("{\"unit\":" + unitId
            + ",\"type\":" + Json.str(u.type.name)
            + ",\"worldX\":" + u.x + ",\"worldY\":" + u.y
            + ",\"tileX\":" + (int) (u.x / 8f) + ",\"tileY\":" + (int) (u.y / 8f)
            + ",\"velX\":" + u.vel.x + ",\"velY\":" + u.vel.y
            + ",\"rotation\":" + u.rotation
            + ",\"added\":" + u.isAdded() + ",\"dead\":" + u.dead
            + ",\"typePhysics\":" + u.type.physics
            + ",\"hasPhysicsRef\":" + u.hasPhysicsRef
            + ",\"speed\":" + u.speed()
            + ",\"typeSpeed\":" + u.type.speed
            + ",\"mass\":" + u.mass()
            + ",\"hitSize\":" + u.hitSize()
            + ",\"flying\":" + u.isFlying()
            + ",\"dockedType\":" + Json.str(String.valueOf(u.dockedType))
            + ",\"spawnedByCore\":" + u.spawnedByCore
            + ",\"limitMapArea\":" + Vars.state.rules.limitMapArea
            + ",\"limitX\":" + Vars.state.rules.limitX
            + ",\"limitY\":" + Vars.state.rules.limitY
            + ",\"limitW\":" + Vars.state.rules.limitWidth
            + ",\"limitH\":" + Vars.state.rules.limitHeight
            + ",\"teamIsAI\":" + u.team.isAI()
            + ",\"controller\":" + Json.str(String.valueOf(u.controller()))
            + ",\"team\":" + Json.str(u.team.name) + "}");
    }

    /** 由主循环每帧调用：把存下来的目标重新施加到单位上。 */
    public static void tickMoveOrders() {
        tickCount++;

        // 探针：抓出传送后位置在哪一帧被改回去
        if (!warpProbe.isEmpty()) {
            long now = System.currentTimeMillis();
            var pit = warpProbe.entrySet().iterator();
            while (pit.hasNext()) {
                var pe = pit.next();
                Unit pu = Groups.unit.getByID(pe.getKey());
                Probe pr = pe.getValue();
                if (pu == null || now > pr.expiresAt) { pit.remove(); continue; }
                pr.framesSeen++;
                if (pr.revertedAt < 0 && (Math.abs(pu.x - pr.setX) > 0.5f || Math.abs(pu.y - pr.setY) > 0.5f)) {
                    pr.revertedAt = pr.framesSeen;
                    pr.revertX = pu.x;
                    pr.revertY = pu.y;
                }
            }
        }

        if (moveOrders.isEmpty()) return;
        if (Vars.state == null || !Vars.state.isPlaying()) { moveOrders.clear(); return; }

        long now = System.currentTimeMillis();
        var it = moveOrders.entrySet().iterator();
        while (it.hasNext()) {
            var e = it.next();
            Unit u = Groups.unit.getByID(e.getKey());
            MoveOrder o = e.getValue();

            if (u == null || u.dead || u.team != o.team || now > o.expiresAt) { it.remove(); continue; }

            float txp = px(o.tx), typ = px(o.ty);
            float dx = txp - u.x, dy = typ - u.y;
            float dist = (float) Math.sqrt(dx * dx + dy * dy);

            // 16 像素（2 格）以内算到达
            if (dist < 16f) { it.remove(); continue; }

            // 转向目标 + 直接覆写速度。
            //
            // 为什么还要直接写 x/y：实测只写 vel 时位置纹丝不动 ——
            // vel 能留住（说明 VelComp.update() 的 move() 确实调了），
            // 但实体坐标会在**下一帧内**被恢复到原值（探针实测 revertedAtFrame=1）。
            // 与其继续挖是谁恢复的，不如每帧重写，保证位移一定累积。
            float ang = Mathf.angle(dx, dy);
            u.rotation = Mathf.slerpDelta(u.rotation, ang, 0.3f);
            float sp = Math.max(u.speed(), 0.5f);
            u.vel.set(dx, dy).nor().scl(sp);

            // 每帧朝目标推进。
            //
            // 实测：只写 vel 时单位几乎不动（位置每帧被恢复，45 帧只累积了 8 像素）。
            // 所以这里每帧直接推进一个较大的步长 —— 被恢复吃掉一部分之后仍能稳定前进。
            // 步长取 6 像素/帧（≈ 45 格/秒），够快又不至于瞬移穿透地形。
            float step = Math.min(Math.max(sp, 6f), dist);
            u.x += dx / dist * step;
            u.y += dy / dist * step;
            lastApplyCount++;
        }
    }

    public static void clearMoveOrders() { moveOrders.clear(); }

    /** 当前挂着的移动指令，供 /control?op=orders 查看。 */
    public static String ordersJson() {
        StringBuilder sb = new StringBuilder("[");
        boolean f = true;
        for (var e : moveOrders.entrySet()) {
            Unit u = Groups.unit.getByID(e.getKey());
            if (!f) sb.append(',');
            f = false;
            sb.append(new Json.Obj()
                .put("unit", e.getKey())
                .put("type", u == null ? "?" : u.type.name)
                .put("targetX", e.getValue().tx)
                .put("targetY", e.getValue().ty)
                .put("worldX", u == null ? 0f : u.x)
                .put("worldY", u == null ? 0f : u.y)
                .toString());
        }
        return sb.append(']').toString();
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
