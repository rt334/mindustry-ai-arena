package aiarena;

import arc.math.geom.Point2;
import arc.struct.Seq;
import mindustry.Vars;
import mindustry.game.Team;
import mindustry.gen.Building;
import mindustry.gen.Call;
import mindustry.gen.Player;
import mindustry.gen.Unit;
import mindustry.type.ItemStack;
import mindustry.type.UnitType;
import mindustry.world.Tile;

/**
 * 批量操作与生成。全部在主线程执行。
 *
 * 设计约束（DESIGN.md P4）：
 *   「全部操作都要过 P2 的校验链，没有旁路。」
 *
 * 因此批量建造不是"直接 setBlock 一片"，而是把每个点都走一遍
 * Actor.place 的三步校验（可见性 → 建造单位 → addBuild），
 * 由引擎的 BuilderComp 决定哪些真的能建。
 *
 * 单个单位的计划队列有实际容量上限，所以批量有硬性格数上限 ——
 * 超出的部分会被拒绝而不是静默丢弃，让 AI 能感知到自己的指令没被完全接受。
 */
public final class Operations {

    /** 单次批量的最大格数。 */
    public static final int MAX_BATCH = 200;

    /** 单个建造单位的计划队列软上限。 */
    public static final int MAX_PLANS_PER_UNIT = 60;

    private Operations() {}

    // ---------------------------------------------------------------- shapes

    public enum Shape { point, line, rect, area, circle, outline, path }

    /**
     * 生成形状覆盖的格坐标列表。
     *
     * @param x1,y1 起点（point/line/rect/area 的左上；circle 的圆心）
     * @param x2,y2 终点（line/rect/area）；circle 用半径
     * @param radius circle 的半径
     */
    public static Seq<Point2> shape(Shape s, int x1, int y1, int x2, int y2, int radius) {
        Seq<Point2> out = new Seq<>();
        int ww = Vars.world.width(), wh = Vars.world.height();

        switch (s) {
            case point -> out.add(new Point2(x1, y1));

            case line -> {
                int dx = Math.abs(x2 - x1), dy = Math.abs(y2 - y1);
                int sx = x1 < x2 ? 1 : -1, sy = y1 < y2 ? 1 : -1;
                int err = dx - dy, cx = x1, cy = y1;
                int guard = 0;
                while (guard++ < 4096) {
                    if (cx >= 0 && cy >= 0 && cx < ww && cy < wh) out.add(new Point2(cx, cy));
                    if (cx == x2 && cy == y2) break;
                    int e2 = 2 * err;
                    if (e2 > -dy) { err -= dy; cx += sx; }
                    if (e2 < dx) { err += dx; cy += sy; }
                }
            }

            case rect, area -> {
                int ax = Math.min(x1, x2), bx = Math.max(x1, x2);
                int ay = Math.min(y1, y2), by = Math.max(y1, y2);
                for (int y = ay; y <= by; y++) {
                    for (int x = ax; x <= bx; x++) {
                        if (s == Shape.outline && x != ax && x != bx && y != ay && y != by) continue;
                        if (x >= 0 && y >= 0 && x < ww && y < wh) out.add(new Point2(x, y));
                    }
                }
            }

            case outline -> {
                int ax = Math.min(x1, x2), bx = Math.max(x1, x2);
                int ay = Math.min(y1, y2), by = Math.max(y1, y2);
                for (int y = ay; y <= by; y++) {
                    for (int x = ax; x <= bx; x++) {
                        if (x != ax && x != bx && y != ay && y != by) continue;
                        if (x >= 0 && y >= 0 && x < ww && y < wh) out.add(new Point2(x, y));
                    }
                }
            }

            // path 的输入不是矩形两点，而是折线点列 —— 走下面的 path() 单独解析，
            // 这里返回空列表，调用方不会走到这。
            case path -> { }

            case circle -> {
                for (int y = y1 - radius; y <= y1 + radius; y++) {
                    for (int x = x1 - radius; x <= x1 + radius; x++) {
                        int ddx = x - x1, ddy = y - y1;
                        if (ddx * ddx + ddy * ddy > radius * radius) continue;
                        if (x >= 0 && y >= 0 && x < ww && y < wh) out.add(new Point2(x, y));
                    }
                }
            }
        }
        return out;
    }

    // ---------------------------------------------------------------- batch

    /** 批量建造结果。 */
    // ---------------------------------------------------------------- path

    /**
     * 折线路径及其逐格朝向。
     *
     * `points` 是展开后的格坐标（保证四邻连续），`rotations` 与之一一对应。
     */
    public static final class PathPlan {
        public final Seq<Point2> points = new Seq<>();
        public final arc.struct.IntSeq rotations = new arc.struct.IntSeq();
        public String error;
    }

    /**
     * 解析 `path=x1,y1;x2,y2;...`，展开成逐格坐标，并算好每格朝向。
     *
     * **朝向是这一格指向下一格的方向**（0=东 1=南 2=西 3=北），
     * 也就是把整条折线连成一条能流起来的传送带所需的朝向。
     * 最后一格没有下一格，沿用前一格的朝向。
     *
     * **保证四邻连续**：Bresenham 在斜线段上会产生对角步（同时走 x 和 y），
     * 而对角相邻的两格在物理上接不上 —— 传送带只认四邻。这里对每个对角步
     * 插一个正交中间点补上，宁可多一格也不要断链。
     */
    public static PathPlan path(String spec) {
        PathPlan plan = new PathPlan();
        if (spec == null || spec.isBlank()) {
            plan.error = "required: path=x1,y1;x2,y2;...";
            return plan;
        }

        Seq<Point2> raw = new Seq<>();
        for (String seg : spec.split(";")) {
            String s = seg.trim();
            if (s.isEmpty()) continue;
            String[] parts = s.split(",");
            if (parts.length < 2) {
                plan.error = "bad point '" + s + "', expected x,y";
                return plan;
            }
            try {
                raw.add(new Point2(Integer.parseInt(parts[0].trim()),
                                   Integer.parseInt(parts[1].trim())));
            } catch (NumberFormatException e) {
                plan.error = "bad point '" + s + "', expected integers";
                return plan;
            }
        }
        if (raw.size < 2) {
            plan.error = "path needs at least 2 points, got " + raw.size;
            return plan;
        }

        // 逐段展开（复用 line 的 Bresenham），段与段之间不重复接点
        Seq<Point2> pts = new Seq<>();
        for (int i = 0; i + 1 < raw.size; i++) {
            Point2 a = raw.get(i), b = raw.get(i + 1);
            Seq<Point2> seg = shape(Shape.line, a.x, a.y, b.x, b.y, 0);
            if (seg.isEmpty()) continue;
            if (pts.isEmpty()) pts.add(seg.first());
            for (int k = 1; k < seg.size; k++) pts.add(seg.get(k));
        }
        if (pts.size < 2) {
            plan.error = "path degenerated to " + pts.size + " tile(s)";
            return plan;
        }

        // 对角步补正交中间点，保证四邻连续
        Seq<Point2> cont = new Seq<>();
        for (int i = 0; i < pts.size; i++) {
            if (i > 0) {
                Point2 prev = cont.peek(), cur = pts.get(i);
                int dx = cur.x - prev.x, dy = cur.y - prev.y;
                if (Math.abs(dx) == 1 && Math.abs(dy) == 1) {
                    // 优先水平补：先横后竖，比反过来更贴合常见的干线走向
                    cont.add(new Point2(cur.x, prev.y));
                }
            }
            cont.add(pts.get(i));
        }
        plan.points.addAll(cont);

        // 逐格朝向 = 指向下一格
        for (int i = 0; i < plan.points.size; i++) {
            if (i + 1 < plan.points.size) {
                Point2 cur = plan.points.get(i), nxt = plan.points.get(i + 1);
                plan.rotations.add(rotToward(nxt.x - cur.x, nxt.y - cur.y));
            } else {
                plan.rotations.add(plan.points.size > 1
                    ? plan.rotations.get(plan.rotations.size - 1) : 0);
            }
        }
        return plan;
    }

    /**
     * 从「指向下一格」的增量求出朝向。
     *
     * 编码与 rotation 一致：**0=东(+x) 1=南(+y) 2=西(-x) 3=北(-y)**。
     * y 向下增长，所以 +y 是屏幕下方 —— 编码 1 是南不是北。
     * 对角线优先取水平分量（带子只能四向，正交中点已在上面补过）。
     */
    private static int rotToward(int dx, int dy) {
        if (dx > 0) return 0;    // 东
        if (dx < 0) return 2;    // 西
        if (dy > 0) return 1;    // 南
        if (dy < 0) return 3;    // 北
        return 0;
    }

    public static final class BatchResult {
        public int requested, accepted, skippedInvisible, skippedInvalid, skippedNoUnit;
        public final Seq<String> firstErrors = new Seq<>();

        public String summary() {
            return "requested=" + requested + " accepted=" + accepted
                 + " skipped[invisible=" + skippedInvisible
                 + ",invalid=" + skippedInvalid
                 + ",noUnit=" + skippedNoUnit + "]";
        }
    }

    /**
     * 批量下单建造。逐格走 Actor.place 的完整校验链。
     *
     * 注意：这里对每一格都调用 addBuild，但同一个建造单位的计划队列有容量上限，
     * 超出后会开始挤掉之前的计划。因此本方法在累计计划数达到 MAX_PLANS_PER_UNIT
     * 时停止，并把实际情况如实报告给调用方。
     */
    public static Actor.Result placeBatch(Team team, Seq<Point2> points, String blockName,
                                          int rotation, String config) {
        return placeBatch(team, points, null, blockName, rotation, config);
    }

    /**
     * 批量下单，**每格可以有各自的朝向**（`path` 用）。
     *
     * @param rotations 与 points 等长的朝向表；传 null 则所有格用同一 rotation
     */
    public static Actor.Result placeBatch(Team team, Seq<Point2> points,
                                          arc.struct.IntSeq rotations, String blockName,
                                          int rotation, String config) {
        if (!Vars.state.isPlaying()) return Actor.Result.err(1005, "game not in playing state");
        if (points.isEmpty()) return Actor.Result.err(1001, "shape produced no tiles");
        if (points.size > MAX_BATCH) {
            return Actor.Result.err(1004, "batch too large: " + points.size + " tiles, max " + MAX_BATCH);
        }

        BatchResult r = new BatchResult();
        r.requested = points.size;

        for (int i = 0; i < points.size; i++) {
            if (r.accepted >= MAX_PLANS_PER_UNIT) {
                r.firstErrors.add("plan queue limit reached at " + r.accepted + " plans");
                break;
            }
            Point2 p = points.get(i);
            int rot = (rotations != null && i < rotations.size) ? rotations.get(i) : rotation;

            Actor.Result one = Actor.place(team, p.x, p.y, blockName, rot, config);
            if (one.ok) {
                r.accepted++;
            } else {
                switch (one.code) {
                    case 1005 -> {
                        if (one.message.contains("not visible")) r.skippedInvisible++;
                        else r.skippedNoUnit++;
                    }
                    default -> r.skippedInvalid++;
                }
                if (r.firstErrors.size < 3) r.firstErrors.add(one.message);
            }
        }

        if (r.accepted == 0) {
            String why = r.firstErrors.isEmpty() ? "no tile accepted" : r.firstErrors.first();
            return Actor.Result.err(1005, "batch rejected: " + r.summary() + " — " + why);
        }
        return Actor.Result.ok("batch " + r.summary());
    }

    /** 批量下单拆除。 */
    public static Actor.Result breakBatch(Team team, Seq<Point2> points) {
        if (!Vars.state.isPlaying()) return Actor.Result.err(1005, "game not in playing state");
        if (points.isEmpty()) return Actor.Result.err(1001, "shape produced no tiles");
        if (points.size > MAX_BATCH) {
            return Actor.Result.err(1004, "batch too large: " + points.size + " tiles, max " + MAX_BATCH);
        }

        BatchResult r = new BatchResult();
        r.requested = points.size;

        for (Point2 p : points) {
            if (r.accepted >= MAX_PLANS_PER_UNIT) break;
            Actor.Result one = Actor.breakBlock(team, p.x, p.y);
            if (one.ok) r.accepted++;
            else {
                if (one.code == 1005 && one.message.contains("not visible")) r.skippedInvisible++;
                else r.skippedInvalid++;
                if (r.firstErrors.size < 3) r.firstErrors.add(one.message);
            }
        }

        if (r.accepted == 0) {
            String why = r.firstErrors.isEmpty() ? "no tile accepted" : r.firstErrors.first();
            return Actor.Result.err(1005, "batch rejected: " + r.summary() + " — " + why);
        }
        return Actor.Result.ok("batch " + r.summary());
    }

    // ---------------------------------------------------------------- spawn

    /**
     * 生成单位。
     *
     * 约束与引擎一致（CoreBlock.java:585 requestSpawn）：
     *   1. 目标位置必须对己方可见
     *   2. 单位类型支持当前环境（unitType.supportsEnv）
     *   3. 队伍人口未达上限（TeamData.unitCount < unitCap）
     *   4. 地面单位需要可站立的格子
     *
     * ⚠ 关于「资源」：引擎里从核心生成单位**不消耗资源** ——
     * CoreBuild.requestSpawn 只检查 supportsEnv 与 allowSpawn，没有成本判断。
     * 单位成本只体现在工厂生产路径上。所以这里也不做资源检查，
     * 否则会与玩家的实际能力不一致，反而破坏对等。
     *
     * 不走 requestSpawn 是因为它需要 Player 参数并走 Call.playerSpawn
     * （那是"玩家重生"语义，会绑定到该玩家）。
     */
    public static Actor.Result spawn(Team team, String unitTypeName, float x, float y) {
        return spawn(team, unitTypeName, x, y, false);
    }

    /**
     * @param adminForce 跳过可见性校验。**仅裁判用** —— 裁判是比赛组织者，
     *                   需要能在任何位置布置单位（例如摆测试场景、恢复局面）。
     *                   它属于 derelict 队、本身没有任何视野，不放开的话
     *                   连「在自家基地旁边放一个单位」都做不到。
     *                   普通 agent 一律走完整校验。
     */
    public static Actor.Result spawn(Team team, String unitTypeName, float x, float y, boolean adminForce) {
        if (!Vars.state.isPlaying()) return Actor.Result.err(1005, "game not in playing state");

        UnitType ut = Vars.content.unit(unitTypeName);
        if (ut == null) return Actor.Result.err(1002, "unknown unit type: " + unitTypeName);
        if (ut.isHidden()) return Actor.Result.err(1002, "unit type is hidden: " + unitTypeName);

        int tx = mindustry.core.World.toTile(x), ty = mindustry.core.World.toTile(y);

        // 约束 1：可见（裁判可强制跳过，见 adminForce 说明）
        if (!adminForce && Vars.state.rules.fog && !Vars.fogControl.isVisible(team, x, y)) {
            return Actor.Result.err(1005, "spawn point tile(" + tx + "," + ty + ") is not visible to " + team.name);
        }

        // 约束 2：环境支持
        if (!ut.supportsEnv(Vars.state.rules.env)) {
            return Actor.Result.err(1002, "unit " + ut.name + " does not support this environment");
        }

        // 约束 3：人口上限
        var td = team.data();
        if (ut.useUnitCap && td.unitCount >= td.unitCap) {
            return Actor.Result.err(1004, "unit cap reached: " + td.unitCount + "/" + td.unitCap);
        }

        // 约束 4：地面单位需要可站立的地面
        Tile t = Vars.world.tile(tx, ty);
        if (t == null) return Actor.Result.err(1003, "spawn point out of bounds");
        if (!ut.flying && (t.solid() || t.floor().isDeep())) {
            return Actor.Result.err(1002, "cannot spawn ground unit on " + t.floor().name);
        }

        Unit u = ut.create(team);
        u.set(x, y);
        u.rotation = 90f;
        u.add();

        return Actor.Result.ok("spawned " + ut.name + " id=" + u.id
                               + " at tile(" + tx + "," + ty + ")"
                               + " pop=" + td.unitCount + "/" + td.unitCap);
    }

    // ---------------------------------------------------------------- chat

    /**
     * 发送聊天消息。玩家能看到的，AI 也能发。
     *
     * Call 有三个 sendMessage 重载：
     *   sendMessage(String)                              服务器本地广播
     *   sendMessage(String, String, Player)              带发送者标识
     *   sendMessage(NetConnection, String, String, ...)  发给单个连接
     * 这里用第二个，让消息带上队伍前缀，与玩家发言的呈现一致。
     */
    public static Actor.Result chat(Team team, String text) {
        if (text == null || text.isEmpty()) return Actor.Result.err(1001, "empty message");
        if (text.length() > 512) return Actor.Result.err(1001, "message too long (max 512)");

        Player shadow = Shadow.of(team);
        if (shadow == null) return Actor.Result.err(1500, "no shadow player for " + team.name);

        String formatted = "[#" + team.color.toString() + "]" + team.name + "[] " + text;
        Call.sendMessage(formatted, text, shadow);
        return Actor.Result.ok("sent: " + text);
    }

    // ---------------------------------------------------------------- build queue

    /**
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
                for (mindustry.entities.units.BuildPlan plan : u.plans) {
                    if (plan == null) continue;
                    if (!pf) plans.append(',');
                    pf = false;
                    Json.Obj po = new Json.Obj()
                        .put("x", plan.x).put("y", plan.y)
                        .put("breaking", plan.breaking);
                    if (plan.block != null) po.put("block", plan.block.name);
                    // 只有已在施工的格子才有进度：0 且长时间不涨 = 卡住
                    float prog = 0f;
                    mindustry.gen.Building tb = Vars.world.build(plan.x, plan.y);
                    if (tb instanceof mindustry.world.blocks.ConstructBlock.ConstructBuild cb) {
                        prog = cb.progress;
                        po.put("constructing", true).put("progress", prog);
                    }
                    // 进度连续不动 = 卡住。超过 3 秒才报，免得把正常的启动间隔
                    // 当成异常。真人是靠「单位站着不动、方块不出现」看出来的。
                    // 建造还要多久：按实测进度变化率外推。进度条在动，
                    // 真人盯着就能估出来 —— 这里只是把这件肉眼可做的事自动化。
                    float rate = StallWatch.planRate(u.id, plan.x, plan.y);
                    if (rate > 1e-5f) {
                        po.put("progressRate", Math.round(rate * 1000f) / 1000f);
                        po.put("etaSeconds",
                            Math.round(StallWatch.planEtaSeconds(u.id, plan.x, plan.y, prog)));
                    }

                    long stuck = StallWatch.planStuckMillis(u.id, plan.x, plan.y);
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
    }

    /**
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

    /** 清空队伍所有建造单位的待办计划。 */
    public static Actor.Result clearQueue(Team team) {
        int n = 0;
        for (Unit u : mindustry.gen.Groups.unit) {
            if (u == null || u.team != team || u.plans == null) continue;
            n += u.plans.size;
            u.plans.clear();
        }
        return Actor.Result.ok("cleared " + n + " pending plan(s)");
    }
}
