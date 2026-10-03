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

    public enum Shape { point, line, rect, area, circle, outline }

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
        if (!Vars.state.isPlaying()) return Actor.Result.err(1005, "game not in playing state");
        if (points.isEmpty()) return Actor.Result.err(1001, "shape produced no tiles");
        if (points.size > MAX_BATCH) {
            return Actor.Result.err(1004, "batch too large: " + points.size + " tiles, max " + MAX_BATCH);
        }

        BatchResult r = new BatchResult();
        r.requested = points.size;

        for (Point2 p : points) {
            if (r.accepted >= MAX_PLANS_PER_UNIT) {
                r.firstErrors.add("plan queue limit reached at " + r.accepted + " plans");
                break;
            }

            Actor.Result one = Actor.place(team, p.x, p.y, blockName, rotation, config);
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
        if (!Vars.state.isPlaying()) return Actor.Result.err(1005, "game not in playing state");

        UnitType ut = Vars.content.unit(unitTypeName);
        if (ut == null) return Actor.Result.err(1002, "unknown unit type: " + unitTypeName);
        if (ut.isHidden()) return Actor.Result.err(1002, "unit type is hidden: " + unitTypeName);

        int tx = mindustry.core.World.toTile(x), ty = mindustry.core.World.toTile(y);

        // 约束 1：可见
        if (Vars.state.rules.fog && !Vars.fogControl.isVisible(team, x, y)) {
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

    /** 查看队伍所有建造单位的待办计划数。 */
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
