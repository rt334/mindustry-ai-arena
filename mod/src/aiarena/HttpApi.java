package aiarena;

import arc.Core;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import mindustry.Vars;
import mindustry.game.Team;
import mindustry.world.Block;
import mindustry.world.Tile;

import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/**
 * HTTP 接口层。
 *
 * 端点：
 *   GET  /ping                                  存活探测（无鉴权）
 *   GET  /v1/{agent}/state                      只读快照（读快照，不回主线程）
 *   GET  /v1/{agent}/map?x=&y=&w=&h=            区域地图（回主线程取 tile）
 *   POST /v1/{agent}/place?x=&y=&block=&rot=&config=
 *   POST /v1/{agent}/break?x=&y=
 *   POST /v1/{agent}/config?x=&y=&value=
 *
 * 统一响应信封：
 *   成功 {"ok":true,"data":{...}}
 *   失败 {"ok":false,"code":1003,"error":"..."}
 *
 * 错误码：
 *   1001 bad_request    1002 not_found       1003 out_of_bounds
 *   1004 queue_full     1005 read_only       1006 cursor_expired
 *   1007 op_expired     1401 unauthorized    1403 forbidden
 *   1429 rate_limited   1500 internal_error
 *
 * 线程模型：
 *   只读端点直接读 Snapshot（主线程生成的不可变对象），零跨线程。
 *   需要触及世界的端点经 postToGame() 投递到主线程，带超时保护。
 */
public final class HttpApi {

    /** 单次 /map 请求允许的最大格数，超出要求分次请求。 */
    private static final int MAX_MAP_TILES = 64 * 64;

    /** 全图扫描时每块的宽度（配合高度 1，正好 MAX_MAP_TILES 格）。 */
    private static final int MAX_MAP_CHUNK_SIDE = MAX_MAP_TILES;

    /** 主线程任务等待上限。超时即放弃，避免 HTTP 线程被永久占住。 */
    private static final long POST_TIMEOUT_MS = 3000;

    private static HttpServer server;

    private HttpApi() {}

    // ---------------------------------------------------------------- start

    public static void start() {
        try {
            server = HttpServer.create(new InetSocketAddress(AIArena.bind, AIArena.port),
                                       AIArena.httpBacklog);

            server.createContext("/ping", ex -> {
                try {
                    Snapshot.State s = Snapshot.get();
                    respond(ex, 200, new Json.Obj()
                        .put("ok", true)
                        .putRaw("data", new Json.Obj()
                            .put("headless", Vars.headless)
            .put("apiVersion", AIArena.API_VERSION)
                            .put("tick", s.tick)
                            .put("agents", AIArena.agents.size())
                            .toString())
                        .toString());
                } catch (Throwable t) { respond(ex, 500, Json.error(1500, String.valueOf(t))); }
            });

            server.createContext("/v1/", HttpApi::route);

            server.setExecutor(Executors.newFixedThreadPool(AIArena.httpThreads, r -> {
                Thread t = new Thread(r, "AIARENA-HTTP");
                t.setDaemon(true);
                return t;
            }));
            server.start();

            AIArena.log("HTTP listening on " + AIArena.bind + ":" + AIArena.port
                        + "  (" + AIArena.agents.size() + " agent(s), "
                        + AIArena.httpThreads + " threads, backlog " + AIArena.httpBacklog + ")");
        } catch (Throwable t) {
            AIArena.log("HTTP FAILED to start: " + t);
            t.printStackTrace();
        }
    }

    public static void stop() {
        if (server != null) server.stop(0);
    }

    // ---------------------------------------------------------------- routing

    private static void route(HttpExchange ex) {
        try {
            String path = ex.getRequestURI().getPath();      // /v1/{agent}/{action}
            String[] parts = path.split("/");
            // parts = ["", "v1", agent, action, ...]
            if (parts.length < 4) {
                respond(ex, 400, Json.error(1001, "expected /v1/{agent}/{action}"));
                return;
            }
            String agentId = parts[2];
            String action  = parts[3];

            AIArena.Agent agent = AIArena.authenticate(ex.getRequestHeaders().getFirst("Authorization"));
            if (agent == null) {
                respond(ex, 401, Json.error(1401, "missing or invalid Authorization: Bearer <token>"));
                return;
            }
            if (!agent.id.equals(agentId)) {
                respond(ex, 403, Json.error(1403, "token does not belong to agent '" + agentId + "'"));
                return;
            }

            // 审计：谁、什么时候、要动哪一格。只记会改变世界的动作，
            // 读接口不记 —— 否则被 /map 刷爆，真出事时反而查不出东西。
            if (Audit.isMutating(action)) {
                Audit.log(agentId, agent.team() == null ? -1 : agent.team().id, action,
                          ex.getRequestURI().getRawQuery(), ex.getRequestMethod());
            }

            // 限流在鉴权之后、路由之前：过不了鉴权的请求不该消耗配额。
            if (!AIArena.takeToken(agent)) {
                respond(ex, 429, Json.error(1429, "rate limit exceeded: "
                    + AIArena.ratePerSecond + "/s (burst " + AIArena.rateBurst + ")"));
                return;
            }

            switch (action) {
                case "state"  -> handleState(ex, agent);
                case "map"    -> handleMap(ex, agent);
                case "place"  -> handlePlace(ex, agent);
                case "break"  -> handleBreak(ex, agent);
                case "config" -> handleConfig(ex, agent);
                case "setup"  -> handleSetup(ex, agent);
                case "maps"   -> handleMaps(ex, agent);
                case "units"  -> handleUnits(ex, agent);
                case "buildings" -> handleBuildings(ex, agent);
                case "content"   -> handleContent(ex, agent);
                case "intel"     -> handleIntel(ex, agent);
                case "command"   -> handleCommand(ex, agent);
                case "control"   -> handleControl(ex, agent);
                case "events"    -> handleEvents(ex, agent);
                case "stream"    -> handleStream(ex, agent);
                case "blueprint" -> handleBlueprint(ex, agent);
                case "spawn"     -> handleSpawn(ex, agent);
                case "factory"   -> handleFactory(ex, agent);
                case "mine"      -> handleMine(ex, agent);
                case "drill"     -> handleDrill(ex, agent);
                case "block"     -> handleBlock(ex, agent);
                case "database"  -> handleDatabase(ex, agent);
                case "rates"     -> handleRates(ex, agent);
                case "stalls"    -> handleStalls(ex, agent);
                case "ore"       -> handleOre(ex, agent);
                case "chat"      -> handleChat(ex, agent);
                case "queue"     -> handleQueue(ex, agent);
                case "observe"   -> handleObserve(ex, agent);
                case "record"    -> handleRecord(ex, agent);
                case "host"      -> handleHost(ex, agent);
                case "start"     -> handleStart(ex, agent);
                case "fog"       -> handleFog(ex, agent);
                case "admin"     -> handleAdmin(ex, agent);
                case "diag"      -> handleDiag(ex, agent);
                default       -> respond(ex, 404, Json.error(1002, "unknown action: " + action));
            }
        } catch (Throwable t) {
            // 打印完整堆栈 —— 只打印异常消息不足以定位（NoSuchElementException 的消息
            // 只是个索引数字，看不出是哪一行抛的）
            AIArena.log("route error on " + ex.getRequestURI() + ": " + t);
            t.printStackTrace();
            respond(ex, 500, Json.error(1500, String.valueOf(t)));
        }
    }

    // ---------------------------------------------------------------- handlers

    /**
     * 解析观察视角（DESIGN.md P5）。
     *
     * view 参数：
     *   own（默认）   自己的队伍视角
     *   <teamId>      指定队伍视角
     *   all           上帝视角 —— **仅 admin**
     *
     * 非 admin 请求别人的视角会被静默降级为自己的视角，而不是报错 ——
     * 这样 AI 无法通过试错探测到自己无权访问哪些视角。
     *
     * @return 视角队伍的 id；-1 表示全见（裁判）
     */
    private static int resolveView(AIArena.Agent agent, Params p) {
        Team own = agent.team();
        int ownId = own == null ? -1 : own.id;

        String v = p.get("view", null);
        if (v == null || v.isEmpty() || v.equalsIgnoreCase("own")) return ownId;

        if (v.equalsIgnoreCase("all")) {
            return agent.admin ? -1 : ownId;
        }

        try {
            int id = Integer.parseInt(v.trim());
            if (id < 0 || id >= Team.all.length) return ownId;
            if (!agent.admin && id != ownId) return ownId;
            return id;
        } catch (NumberFormatException e) {
            return ownId;
        }
    }

    /** 只读：直接读主线程生成的快照，不回主线程。 */
    private static void handleState(HttpExchange ex, AIArena.Agent agent) {
        Snapshot.State s = Snapshot.get();
        Team team = agent.team();

        Params vp = Params.of(ex);
        int viewId = resolveView(agent, vp);
        boolean seeAll = viewId < 0;

        Json.Obj data = new Json.Obj()
            .put("agent", agent.id)
            .put("team", team == null ? -1 : team.id)
            .put("tick", s.tick)
            .put("wave", s.wave)
            .put("playing", s.playing)
            .put("paused", s.paused)
            .put("gameOver", s.gameOver)
            .put("pvp", s.pvp)
            .put("fog", s.fog)
            .putRaw("world", new Json.Obj().put("w", s.worldWidth).put("h", s.worldHeight).toString());

        // 自己的队伍
        if (team != null) {
            Json.Obj self = new Json.Obj()
                .put("id", team.id).put("name", team.name)
                .put("isAI", team.isAI()).put("alive", team.isAlive())
                .put("cores", team.data().cores.size);
            data.putRaw("self", self.toString());
        }

        // 队伍列表：只给公开字段（core 数量是原版公开信息）
        StringBuilder teams = new StringBuilder("[");
        boolean first = true;
        for (Snapshot.TeamInfo t : s.teams) {
            if (!first) teams.append(',');
            first = false;
            teams.append(new Json.Obj()
                .put("id", t.id).put("name", t.name)
                .put("isAI", t.ai).put("alive", t.alive).put("cores", t.cores).toString());
        }
        teams.append(']');
        data.putRaw("teams", teams.toString());

        // 视野内的单位与建筑。视角由 view 参数决定（own / <teamId> / all）。
        int myTeam = viewId;
        data.putRaw("units", visibleUnits(s, myTeam, seeAll));
        data.putRaw("buildings", visibleBuildings(s, myTeam, seeAll));
        data.put("snapshotFresh", s.heavyFresh);
        if (seeAll) data.put("view", "all");
        else if (myTeam >= 0) data.put("view", Team.get(myTeam).name);

        // 接口自身的上限。写在响应里，免得靠反复试探才知道边界在哪。
        data.putRaw("limits", new Json.Obj()
            .put("mapWindowTiles", MAX_MAP_TILES)
            .put("batchMax", Operations.MAX_BATCH)
            .put("plansPerUnit", Operations.MAX_PLANS_PER_UNIT)
            .toString());

        // 视野：每个视野源的位置与半径。fogRadius 才是「能看多远」，
        // 不是 UnitType.buildRange（那是建造范围）。
        float maxR = 0f;
        StringBuilder vs = new StringBuilder("[");
        boolean vf = true;
        for (Snapshot.UnitInfo u : s.units) {
            if (u.team != myTeam && !seeAll) continue;
            if (u.fogRadius <= 0f) continue;
            if (u.fogRadius > maxR) maxR = u.fogRadius;
            if (!vf) vs.append(',');
            vf = false;
            vs.append(new Json.Obj().put("kind", "unit").put("id", u.id)
                .put("x", (int) (u.x / 8f)).put("y", (int) (u.y / 8f))
                .put("radius", u.fogRadius).toString());
        }
        for (Snapshot.BuildInfo b : s.builds) {
            if (b.team != myTeam && !seeAll) continue;
            if (b.fogRadius <= 0f) continue;
            if (b.fogRadius > maxR) maxR = b.fogRadius;
            if (!vf) vs.append(',');
            vf = false;
            vs.append(new Json.Obj().put("kind", "building").put("x", b.x).put("y", b.y)
                .put("radius", b.fogRadius).toString());
        }
        vs.append(']');
        data.putRaw("vision", new Json.Obj()
            .put("maxRadius", maxR).putRaw("sources", vs.toString()).toString());

        respond(ex, 200, Json.ok(data.toString()));
    }

    /**
     * 区域地图。需要 tile 数据，回主线程按需生成。
     *
     * 两种模式：
     *
     *   区域模式   /map?x=&y=&w=&h=      取指定矩形，w*h 不得超过 4096
     *   全图模式   /map                  从 (0,0) 开始按 4096 格分块扫描
     *              /map?cursor=<token>   续传（token 即上次响应的 cursor_next）
     *
     * 全图模式的响应里带 cursor_next；为 null 表示已扫完。
     * 之所以要有全图模式：250×250 地图有 62500 格，远超单次响应上限，
     * 而 AI 有时确实需要一次完整扫描（例如找资源点）。
     */
    private static void handleMap(HttpExchange ex, AIArena.Agent agent) {
        Params p = Params.of(ex);

        String cursor = p.get("cursor", null);
        boolean wholeMap = (cursor != null) || !p.has("x") && !p.has("y") && !p.has("w") && !p.has("h");

        int x, y, w, h;
        if (wholeMap) {
            int[] origin = decodeCursor(cursor);
            x = origin[0]; y = origin[1];
            w = MAX_MAP_CHUNK_SIDE; h = 1;          // 每块 4096 格，按行推进
        } else {
            x = p.getInt("x", 0); y = p.getInt("y", 0);
            w = p.getInt("w", 32); h = p.getInt("h", 32);
        }

        if (w <= 0 || h <= 0) { respond(ex, 400, Json.error(1001, "w and h must be positive")); return; }
        if ((long) w * h > MAX_MAP_TILES) {
            respond(ex, 400, Json.error(1004, "region too large: " + (w * h)
                + " tiles, max " + MAX_MAP_TILES + " — use /map?cursor= for whole-map scan"));
            return;
        }

        Params vp = Params.of(ex);
        int viewId = resolveView(agent, vp);
        boolean admin = viewId < 0;
        int myTeam = viewId;
        final int fx = x, fy = y, fw = w, fh = h;
        final boolean fWhole = wholeMap;

        postToGame(ex, () -> {
            int ww = Vars.world.width(), wh = Vars.world.height();
            StringBuilder tiles = new StringBuilder("[");
            boolean first = true;

            int lastX = fx, lastY = fy;

            for (int ty = fy; ty < fy + fh && ty < wh; ty++) {
                if (ty < 0) continue;
                for (int tx = fx; tx < fx + fw && tx < ww; tx++) {
                    if (tx < 0) continue;
                    lastX = tx; lastY = ty;

                    boolean visible = admin
                        || (myTeam >= 0 && safeVisibleTile(Team.get(myTeam), tx, ty));
                    boolean discovered = admin
                        || (myTeam >= 0 && safeDiscovered(Team.get(myTeam), tx, ty));

                    Tile t = Vars.world.tile(tx, ty);
                    if (t == null) continue;

                    if (!first) tiles.append(',');
                    first = false;

                    Json.Obj o = new Json.Obj().put("x", tx).put("y", ty);
                    if (visible) {
                        o.put("visible", true);
                        o.put("floor", t.floor().name);
                        // 矿石在 overlay 层，不在 block 层 —— Mindustry 用
                        // tile.setOverlay() 放 OreBlock，tile.block() 拿不到。
                        // 早期版本只返回 block，导致整张图上矿石完全消失。
                        var ov = t.overlay();
                        o.put("overlay", ov == null ? "air" : ov.name);
                        // drop = 在这里放矿机**实际会产出什么**。
                        // 这是 Drill.canMine 用的同一个 tile.drop()：
                        //   矿石 -> overlay.itemDrop
                        //   沙地 -> floor.itemDrop（darksand/sand-floor 给 sand）
                        // 只看 overlay 会漏掉沙地，而硅冶炼厂吃的正是 煤 + 沙。
                        var dr0 = t.drop();
                        o.put("drop", dr0 == null ? "" : dr0.name);
                        o.put("dropHardness", dr0 == null ? -1 : dr0.hardness);
                        o.put("block", t.block().name);
                        putLiquidInfo(o, t);
                        o.put("team", t.team().name);
                        o.put("build", t.build != null);
                    } else {
                        o.put("visible", false);
                        o.put("discovered", discovered);
                        if (discovered) {
                            // 地形、矿石、液体都是探索过的记忆，玩家能看到；
                            // 方块与队伍不给
                            o.put("floor", t.floor().name);
                            var ov2 = t.overlay();
                            o.put("overlay", ov2 == null ? "air" : ov2.name);
                            var dr1 = t.drop();
                            o.put("drop", dr1 == null ? "" : dr1.name);
                            o.put("dropHardness", dr1 == null ? -1 : dr1.hardness);
                            putLiquidInfo(o, t);
                            o.put("block", "<unknown>");
                        }
                    }
                    tiles.append(o.toString());
                }
            }
            tiles.append(']');

            Json.Obj out = new Json.Obj()
                .put("x", fx).put("y", fy).put("w", fw).put("h", fh)
                .put("agent", agent.id)
                .put("worldW", ww).put("worldH", wh)
                .putRaw("tiles", tiles.toString());

            if (fWhole) {
                // 全图模式：按行推进游标
                String next = null;
                if (lastY < wh - 1 || lastX < ww - 1) {
                    int nx = (lastX + 1 < ww) ? lastX + 1 : 0;
                    int ny = (lastX + 1 < ww) ? lastY : lastY + 1;
                    if (ny < wh) next = encodeCursor(nx, ny);
                }
                out.put("mode", "whole");
                if (next == null) out.putNull("cursor_next");
                else out.put("cursor_next", next);
            } else {
                out.put("mode", "region");
            }

            return Json.ok(out.toString());
        });
    }

    /** 游标编码：直接是 "x,y"。保持可读，便于人工调试。 */
    private static String encodeCursor(int x, int y) { return x + "," + y; }

    /** 游标解码。非法输入回落到 (0,0)。 */
    private static int[] decodeCursor(String cursor) {
        if (cursor == null || cursor.isEmpty()) return new int[]{0, 0};
        String[] parts = cursor.split(",");
        if (parts.length != 2) return new int[]{0, 0};
        try { return new int[]{Integer.parseInt(parts[0].trim()), Integer.parseInt(parts[1].trim())}; }
        catch (NumberFormatException e) { return new int[]{0, 0}; }
    }

    /** path 的逐格朝向，压缩成 `[x,y,rot, x,y,rot, ...]` —— 紧凑且够读。 */
    static String rotationsJson(Operations.PathPlan pp) {
        StringBuilder s = new StringBuilder("[");
        for (int i = 0; i < pp.points.size; i++) {
            if (i > 0) s.append(',');
            s.append('[').append(pp.points.get(i).x).append(',')
             .append(pp.points.get(i).y).append(',')
             .append(pp.rotations.get(i)).append(']');
        }
        return s.append(']').toString();
    }

    /**
     * 下单建造。支持单点与批量形状。
     *
     * POST /place?x=&y=&block=&rot=&config=                      单点
     * POST /place?shape=line&x1=&y1=&x2=&y2=&block=              直线
     * POST /place?shape=area&x1=&y1=&x2=&y2=&block=              实心矩形
     * POST /place?shape=outline&x1=&y1=&x2=&y2=&block=           矩形边框
     * POST /place?shape=circle&x=&y=&radius=&block=              实心圆
     * POST /place?shape=path&path=x1,y1;x2,y2;...&block=          折线路径
     *
     * `shape=path` 与其它形状的区别：**每一格的朝向由服务端按路径走向算**，
     * 把折线连成一条能流起来的传送带。不用再自己生成坐标再逐格 place。
     *
     * 批量不是「直接改一片世界」—— 每一格都走 Actor.place 的三步校验
     * （可见性 → 建造单位 → addBuild），由引擎决定哪些真的能建。
     */
    private static void handlePlace(HttpExchange ex, AIArena.Agent agent) {
        Params p = Params.of(ex);
        String block = p.get("block", null);
        if (block == null) { respond(ex, 400, Json.error(1001, "required: block")); return; }

        int rot = p.getInt("rot", 0);
        String config = p.get("config", null);

        Team team = agent.team();
        if (team == null) { respond(ex, 403, Json.error(1403, "agent has no team")); return; }

        String shapeName = p.get("shape", null);
        if (shapeName == null) {
            // 单点：保持 P1 的接口不变
            int x = p.getInt("x", Integer.MIN_VALUE);
            int y = p.getInt("y", Integer.MIN_VALUE);
            if (x == Integer.MIN_VALUE || y == Integer.MIN_VALUE) {
                respond(ex, 400, Json.error(1001, "required: x, y (or shape=...)"));
                return;
            }
            int unitId = p.getInt("unit", -1);
            postToGame(ex, () -> {
                Actor.Result r = Actor.place(team, x, y, block, rot, config, unitId);
                Json.Obj body = (r.extra == null) ? new Json.Obj() : r.extra;
                body.put("message", r.message);
                return r.ok ? Json.ok(body.toString()) : Json.error(r.code, r.message, body);
            });
            return;
        }

        Operations.Shape shape;
        try { shape = Operations.Shape.valueOf(shapeName.toLowerCase()); }
        catch (IllegalArgumentException e) {
            respond(ex, 400, Json.error(1001, "unknown shape: " + shapeName
                + " (point|line|rect|area|outline|circle|path)"));
            return;
        }

        // path 走单独的解析：它的输入是点列，并且逐格朝向由走向推出来
        if (shape == Operations.Shape.path) {
            Operations.PathPlan pp = Operations.path(p.get("path", null));
            if (pp.error != null) {
                respond(ex, 400, Json.error(1001, pp.error));
                return;
            }
            postToGame(ex, () -> {
                Actor.Result r = Operations.placeBatch(team, pp.points, pp.rotations,
                                                       block, rot, config);
                Json.Obj body = (r.extra == null) ? new Json.Obj() : r.extra;
                body.put("shape", "path")
                    .put("tiles", pp.points.size)
                    .putRaw("rotations", rotationsJson(pp))
                    .put("message", r.message);
                // 失败时也把 body 带上：skipped 分解就在里面，丢了只剩一句散文
                return r.ok ? Json.ok(body.toString()) : Json.error(r.code, r.message, body);
            });
            return;
        }

        int x1 = p.getInt("x1", p.getInt("x", 0));
        int y1 = p.getInt("y1", p.getInt("y", 0));
        int x2 = p.getInt("x2", x1);
        int y2 = p.getInt("y2", y1);
        int radius = p.getInt("radius", 3);

        postToGame(ex, () -> {
            var pts = Operations.shape(shape, x1, y1, x2, y2, radius);
            Actor.Result r = Operations.placeBatch(team, pts, block, rot, config);
            Json.Obj body = (r.extra == null) ? new Json.Obj() : r.extra;
            body.put("message", r.message).put("shape", shape.name()).put("tiles", pts.size);
            return r.ok ? Json.ok(body.toString()) : Json.error(r.code, r.message, body);
        });
    }

    /** 批量拆除。参数与 /place 一致（不需要 block）。 */
    private static void handleBreak(HttpExchange ex, AIArena.Agent agent) {
        Params p = Params.of(ex);
        Team team = agent.team();
        if (team == null) { respond(ex, 403, Json.error(1403, "agent has no team")); return; }

        String shapeName = p.get("shape", null);
        if (shapeName == null) {
            int x = p.getInt("x", Integer.MIN_VALUE);
            int y = p.getInt("y", Integer.MIN_VALUE);
            if (x == Integer.MIN_VALUE || y == Integer.MIN_VALUE) {
                respond(ex, 400, Json.error(1001, "required: x, y (or shape=...)"));
                return;
            }
            postToGame(ex, () -> {
                Actor.Result r = Actor.breakBlock(team, x, y);
                return r.ok ? Json.ok(new Json.Obj().put("message", r.message).toString())
                            : Json.error(r.code, r.message);
            });
            return;
        }

        Operations.Shape shape;
        try { shape = Operations.Shape.valueOf(shapeName.toLowerCase()); }
        catch (IllegalArgumentException e) {
            respond(ex, 400, Json.error(1001, "unknown shape: " + shapeName));
            return;
        }

        int x1 = p.getInt("x1", p.getInt("x", 0));
        int y1 = p.getInt("y1", p.getInt("y", 0));
        int x2 = p.getInt("x2", x1);
        int y2 = p.getInt("y2", y1);
        int radius = p.getInt("radius", 3);

        postToGame(ex, () -> {
            var pts = Operations.shape(shape, x1, y1, x2, y2, radius);
            Actor.Result r = Operations.breakBatch(team, pts);
            Json.Obj body = (r.extra == null) ? new Json.Obj() : r.extra;
            body.put("message", r.message).put("shape", shape.name()).put("tiles", pts.size);
            return r.ok ? Json.ok(body.toString()) : Json.error(r.code, r.message, body);
        });
    }

    /**
     * 生成单位。受人口上限与资源约束，与玩家从核心生产单位同规则。
     *
     * POST /spawn?type=<unitType>&x=&y=
     */
    /**
     * 生成单位。POST /spawn?type=<unit>&x=<tileX>&y=<tileY>
     *
     * x/y 是**格坐标**，与 /place、/command、/config 保持一致。
     *
     * 早期版本把 x/y 直接当世界像素传给 Operations.spawn，
     * 于是 /spawn?x=60&y=103 被 World.toTile(60) 解释成格 (8,13) ——
     * 在一张 350x200 的图上跑到了角落，报「not visible」。
     * 现在统一在入口处转换，Operations 仍收世界坐标（与引擎一致）。
     */
    private static void handleSpawn(HttpExchange ex, AIArena.Agent agent) {
        Params p = Params.of(ex);

        // 单位必须由工厂生产，不能凭空召唤。
        //
        // 直接 spawn 绕过了整套产能：没有建造时间、不需要电力、不需要工厂，
        // 于是「谁先攒出产能」这个维度直接消失，对局退化成两个脚本对撞。
        // 想调试时用 -Darena.allowspawn=true 显式打开。
        if (!AIArena.ALLOW_DIRECT_SPAWN) {
            respond(ex, 403, Json.error(1005,
                "direct unit spawning is disabled: units must be produced by a factory. "
              + "Build one (air-factory / ground-factory / naval-factory), give it power, "
              + "select a plan with /config?x=<tileX>&y=<tileY>&value=<unitName>, "
              + "then let it produce. "
              + "Server-side override: -Darena.allowspawn=true"));
            return;
        }

        String type = p.get("type", null);
        if (type == null) { respond(ex, 400, Json.error(1001, "required: type")); return; }

        float tx = p.getFloat("x", Float.NaN);
        float ty = p.getFloat("y", Float.NaN);

        // 队伍：默认是调用方自己的队。裁判可以用 team= 指定**替哪一队**生成 ——
        // 它自己属于 derelict，那队单位上限是 0，不指定的话连一个都放不出来。
        // 组织比赛本来就需要能在任意位置为任意队伍布置单位。
        Team team;
        String teamParam = p.get("team", null);
        if (agent.admin && teamParam != null) {
            try {
                team = Team.get(Integer.parseInt(teamParam.trim()));
            } catch (NumberFormatException nfe) {
                respond(ex, 400, Json.error(1001, "bad team id: " + teamParam));
                return;
            }
        } else {
            team = agent.team();
        }
        if (team == null) { respond(ex, 403, Json.error(1403, "agent has no team")); return; }

        postToGame(ex, () -> {
            float sx, sy;

            if (Float.isNaN(tx) || Float.isNaN(ty)) {
                // 未给坐标：在核心周围找一块空地。
                // 注意 core-nucleus 是 5x5，核心自身占据的格全是 solid，
                // 所以必须往外找，不能用 core.tileX()/tileY() 本身。
                var core = team.core();
                if (core == null) return Json.error(1005, "team " + team.name + " has no core");

                var ut0 = Vars.content.unit(type);
                boolean flying = ut0 != null && ut0.flying;
                int[] spot = findSpawnSpot(core.tileX(), core.tileY(), flying);
                if (spot == null) return Json.error(1004, "no free spawn tile near core");
                // 不能加 tilesize/2 取格中心：World.toTile 用的是 Math.round，
                // 加半格会被进位到下一格（59*8+4=476 → round(59.5)=60）。
                sx = spot[0] * Vars.tilesize + 1f;
                sy = spot[1] * Vars.tilesize + 1f;
            } else {
                // 格坐标 -> 世界坐标。
                // 注意不能加 tilesize/2：World.toTile 用 Math.round，加半格会进位到下一格。
                sx = tx * Vars.tilesize + 1f;
                sy = ty * Vars.tilesize + 1f;
            }

            // 裁判可强制生成（它属于 derelict 队，本身没有视野）
            Actor.Result r = Operations.spawn(team, type, sx, sy, agent.admin);
            return r.ok ? Json.ok(new Json.Obj().put("message", r.message).toString())
                        : Json.error(r.code, r.message);
        });
    }

    /**
     * 在给定格周围螺旋搜索一个可以生成单位的格子。
     *
     * 飞行单位只需不越界且不在建筑里；地面单位还要求该格非 solid 且不是深水。
     */
    private static int[] findSpawnSpot(int cx, int cy, boolean flying) {
        int w = Vars.world.width(), h = Vars.world.height();
        for (int r = 1; r < 40; r++) {
            for (int dy = -r; dy <= r; dy++) {
                for (int dx = -r; dx <= r; dx++) {
                    // 只检查当前这一圈的边框
                    if (Math.abs(dx) != r && Math.abs(dy) != r) continue;
                    int x = cx + dx, y = cy + dy;
                    if (x < 1 || y < 1 || x >= w - 1 || y >= h - 1) continue;
                    Tile t = Vars.world.tile(x, y);
                    if (t == null) continue;
                    if (t.solid()) continue;                       // 别生成在建筑里
                    if (!flying && t.floor().isDeep()) continue;   // 地面单位不能站深水
                    return new int[]{x, y};
                }
            }
        }
        return null;
    }

    /** 发送聊天消息。POST /chat?text=... */
    private static void handleChat(HttpExchange ex, AIArena.Agent agent) {
        Params p = Params.of(ex);
        String text = p.get("text", null);
        if (text == null) { respond(ex, 400, Json.error(1001, "required: text")); return; }

        Team team = agent.team();
        if (team == null) { respond(ex, 403, Json.error(1403, "agent has no team")); return; }

        postToGame(ex, () -> {
            Actor.Result r = Operations.chat(team, text);
            return r.ok ? Json.ok(new Json.Obj().put("message", r.message).toString())
                        : Json.error(r.code, r.message);
        });
    }

    /** 查看 / 清空建造队列。GET /queue ；POST /queue?clear=true */
    private static void handleQueue(HttpExchange ex, AIArena.Agent agent) {
        Params p = Params.of(ex);
        Team team = agent.team();
        if (team == null) { respond(ex, 403, Json.error(1403, "agent has no team")); return; }
        boolean clear = p.getBool("clear", false);

        postToGame(ex, () -> {
            if (clear) {
                Actor.Result r = Operations.clearQueue(team);
                Json.Obj body = (r.extra == null) ? new Json.Obj() : r.extra;
                body.put("message", r.message);
                return Json.ok(body.toString());
            }
            return Json.ok(new Json.Obj()
                .put("agent", agent.id).put("team", team.name)
                .putRaw("builders", Operations.queueReport(team))
                .toString());
        });
    }

    /**
     * 手动挖矿。走原版 MinerComp 路径。POST /v1/{agent}/mine
     *
     *   POST /mine?unit=<id>&x=<tileX>&y=<tileY>   让该单位去挖这一格
     *   POST /mine?unit=<id>&clear=true            停止挖矿
     *
     * 为什么是「原版实现」：mineTile 就是 MinerComp 里那个 @SyncLocal 字段，
     * 玩家用鼠标挖矿时输入处理器写的就是它。这里只是把它设上，剩下全交给
     * MinerComp.update() —— 挖矿速率、矿脉判定、硬度和 mineTier 的比较、
     * 以及 offloadImmediately()（玩家控制的单位会把矿直接送进 mineTransferRange
     * 内的核心）都是引擎自己的逻辑，没有一行是我模拟的。
     *
     * 这条路径存在的意义是**启动资金**：开局核心库存只够放几个建筑，
     * 想造矿机和传送带得先有料，而料只能从手动挖矿来。
     */
    /**
     * 矿机状态。GET /v1/{agent}/drill
     *
     * 为什么要单独一个端点：/buildings 只给通用的 items/efficiency，看不出
     * 「矿机到底在不在挖、挖的是什么、为什么挖不动」。实测两次卡死都是这个：
     *
     *   1. 矿机满仓推不出去 —— items=10 但看不出是 dump 失败
     *   2. 选到了 ore-thorium，mechanical-drill 的 tier=2 挖不动硬度 4 的钍
     *
     * 这里把 Drill.DrillBuild 的关键字段直接摊开：
     *   dominantItem   脚下占多数的矿种（null = 矿机上没有矿）
     *   dominantItems  脚下矿格数
     *   tier           方块可挖硬度上限
     *   oreHardness    脚下矿的硬度
     *   canMine        tier >= oreHardness
     *   progress       钻井进度（0..1，到 1 出一个矿）
     *   warmup         预热（0..1，刚放下的机器要爬升）
     *   lastDrillSpeed **每 tick** 速率（引擎字段，只两位小数，
     *                  0.01 可能对应真实 0.0062 —— 别当每秒读）
     *   itemsPerSecond  每秒产出（= lastDrillSpeed × 60）。**读这个**
     *   dominantItems   钻机脚印内的主矿格数。产率**正比于它**：
     *                   每秒 = 60 × dominantItems ÷ (drillTime + 50 × 硬度)
     *   full           缓冲区是否满了
     */
    /**
     * 方块资料 + 配方。GET /v1/{agent}/block?name=<blockName>
     *
     * 资料来自 UnlockableContent（localizedName / description / details），
     * 就是游戏内点开方块看到的那些文字。
     *
     * 配方从两个地方拼：
     *   输入 —— Block.consumers 数组，逐个判类型
     *     ConsumeItems        固定物品
     *     ConsumeItemDynamic  动态（UnitFactory 按当前产线变），静态查不出具体物品
     *     ConsumeItemFilter   按谓词过滤
     *     ConsumeLiquid(s)    液体
     *     ConsumePower        电力
     *   输出 —— GenericCrafter.outputItems / outputLiquids，
     *            UnitFactory.plans（单位 + 耗时 + 材料）
     *
     * 不带 name 时返回全部可建方块的精简版（只有名字和尺寸），避免响应过大。
     */
    /**
     * 物品速率。窗口内「产了多少 / 耗了多少」。
     *
     *   GET /rates?window=10          默认 10 秒
     *
     * 返回 core（核心库存变化，= 净产出）和 stored（全队建筑库存变化，含在途）。
     * 两者对照就能定位瓶颈：
     *   core 不涨 + stored 涨  -> 东西堵在产线里
     *   core 涨   + stored 平  -> 健康
     *   两者都不涨              -> 上游没在挖
     */
    private static void handleRates(HttpExchange ex, AIArena.Agent agent) {
        Params p = Params.of(ex);
        double window = p.getFloat("window", 10f);
        if (window < 0.5) window = 0.5;
        if (window > 110) window = 110;

        Team team = agent.team();
        if (team == null) { respond(ex, 403, Json.error(1403, "agent has no team")); return; }

        // 裁判可以指定队伍
        String teamParam = p.get("team", null);
        if (agent.admin && teamParam != null) {
            try { team = Team.get(Integer.parseInt(teamParam.trim())); } catch (Throwable ignored) {}
        }

        respond(ex, 200, Json.ok(new Json.Obj()
            .put("agent", agent.id)
            .putRaw("rates", RateTracker.ratesJson(team, window))
            .toString()));
    }

    /**
     * 传送带堵塞报警。
     *
     *   GET /stalls            当前所有堵住的传送带
     *
     * 判据是引擎自己的 clogHeat（涨到 1 约等于堵了 1 秒）。
     * 每条给出位置、朝向、压着的物品、堵了多久，以及**出料侧是什么方块、
     * 它是否接受物品** —— 后者才是定位堵塞原因的关键。
     *
     * 堵塞同时也会进事件流（type=stall），所以可以 /events?since= 增量拉。
     */
    private static void handleStalls(HttpExchange ex, AIArena.Agent agent) {
        respond(ex, 200, Json.ok(new Json.Obj()
            .put("agent", agent.id)
            .put("stalledCount", StallWatch.stalledCount())
            .putRaw("stalls", StallWatch.stallsJson())
            .toString()));
    }

    // ================================================================ 核心数据库
    //
    // 对应游戏内的「核心数据库」（Database）界面：查内容、看介绍、看配方，
    // 以及**反查** —— 「什么东西能产硅」「谁在吃煤」。
    //
    // 和 /content、/block 的分工：
    //   /content        全量清单，一次拿完，适合开局缓存
    //   /block?name=    单个方块的详情（配方 + 介绍）
    //   /database       **可检索** + **反查产线**，适合按需问
    //
    // 反查是这个接口真正的价值：AI 要决定「缺硅怎么办」，
    // 光知道 silicon-smelter 的配方没用，得知道「谁能产硅」；
    // 反过来要规划物料流向，又得知道「谁会吃铜」。

    private static void handleDatabase(HttpExchange ex, AIArena.Agent agent) {
        Params p = Params.of(ex);

        String q = p.get("q", null);
        String itemName = p.get("item", null);
        String blockName = p.get("block", null);
        String catName = p.get("cat", null);
        String type = p.get("type", null);        // block|item|unit|liquid
        int limit = Math.min(Math.max(p.getInt("limit", 60), 1), 400);

        ensureBundle();

        // ---- 反查：这个物品谁产、谁吃 ----
        if (itemName != null) {
            mindustry.type.Item it = Vars.content.item(itemName);
            if (it == null) { respond(ex, 404, Json.error(1002, "unknown item: " + itemName)); return; }

            StringBuilder producers = new StringBuilder("[");
            StringBuilder consumers = new StringBuilder("[");
            boolean pf = true, cf = true;
            int pn = 0, cn = 0;

            for (Block b : Vars.content.blocks()) {
                if (b.isHidden()) continue;
                if (blockProducesItem(b, it)) {
                    if (!pf) producers.append(',');
                    pf = false; pn++;
                    producers.append(new Json.Obj()
                        .put("name", b.name)
                        .put("localizedName", blockNameOf(b))
                        .put("category", b.category == null ? "" : b.category.name())
                        .put("size", b.size)
                        .put("how", productionKind(b, it))
                        .toString());
                }
                if (blockConsumesItem(b, it)) {
                    if (!cf) consumers.append(',');
                    cf = false; cn++;
                    consumers.append(new Json.Obj()
                        .put("name", b.name)
                        .put("localizedName", blockNameOf(b))
                        .put("category", b.category == null ? "" : b.category.name())
                        .put("size", b.size)
                        .put("how", consumptionKind(b, it))
                        .toString());
                }
            }
            producers.append(']');
            consumers.append(']');

            // 矿物的硬度决定要几级矿机 —— 这也是「谁产它」的一部分
            StringBuilder drills = new StringBuilder("[");
            boolean df = true;
            for (Block b : Vars.content.blocks()) {
                if (b instanceof mindustry.world.blocks.production.Drill dr && dr.tier >= it.hardness) {
                    if (!df) drills.append(',');
                    df = false;
                    drills.append(new Json.Obj()
                        .put("name", b.name).put("localizedName", blockNameOf(b))
                        .put("tier", dr.tier).put("size", dr.size).toString());
                }
            }
            drills.append(']');

            respond(ex, 200, Json.ok(new Json.Obj()
                .put("agent", agent.id)
                .put("item", it.name)
                .put("localizedName", itemNameOf(it))
                .put("description", itemDescOf(it))
                .put("hardness", it.hardness)
                .put("explosiveness", it.explosiveness)
                .put("flammability", it.flammability)
                .put("radioactivity", it.radioactivity)
                .put("charge", it.charge)
                .put("cost", it.cost)
                .put("producerCount", pn)
                .putRaw("producers", producers.toString())
                .put("consumerCount", cn)
                .putRaw("consumers", consumers.toString())
                .putRaw("drills", drills.toString())
                .toString()));
            return;
        }

        // ---- 搜索：名字或介绍里含关键词 ----
        if (q != null && !q.isEmpty()) {
            String needle = q.toLowerCase(java.util.Locale.ROOT);
            StringBuilder hits = new StringBuilder("[");
            boolean hf = true;
            int n = 0;

            java.util.function.BiConsumer<String, Object[]> consider = (kind, tuple) -> {};
            // 直接展开写，避免闭包里改外部变量
            for (Block b : Vars.content.blocks()) {
                if (b.isHidden() || n >= limit) continue;
                if (!matches(needle, b.name, blockNameOf(b), blockDescOf(b))) continue;
                if (!hf) hits.append(',');
                hf = false; n++;
                hits.append(new Json.Obj().put("type", "block").put("name", b.name)
                    .put("localizedName", blockNameOf(b))
                    .put("category", b.category == null ? "" : b.category.name())
                    .put("size", b.size).toString());
            }
            for (mindustry.type.Item i : Vars.content.items()) {
                if (n >= limit) break;
                if (!matches(needle, i.name, itemNameOf(i), itemDescOf(i))) continue;
                if (!hf) hits.append(',');
                hf = false; n++;
                hits.append(new Json.Obj().put("type", "item").put("name", i.name)
                    .put("localizedName", itemNameOf(i))
                    .put("hardness", i.hardness).toString());
            }
            for (mindustry.type.UnitType u : Vars.content.units()) {
                if (u.isHidden() || n >= limit) continue;
                if (!matches(needle, u.name, unitNameOf(u), unitDescOf(u))) continue;
                if (!hf) hits.append(',');
                hf = false; n++;
                hits.append(new Json.Obj().put("type", "unit").put("name", u.name)
                    .put("localizedName", unitNameOf(u))
                    .put("health", u.health).put("flying", u.flying)
                    .put("buildSpeed", u.buildSpeed).toString());
            }
            for (mindustry.type.Liquid l : Vars.content.liquids()) {
                if (l.isHidden() || n >= limit) continue;
                if (!matches(needle, l.name, liquidNameOf(l), liquidDescOf(l))) continue;
                if (!hf) hits.append(',');
                hf = false; n++;
                hits.append(new Json.Obj().put("type", "liquid").put("name", l.name)
                    .put("localizedName", liquidNameOf(l)).toString());
            }
            hits.append(']');

            respond(ex, 200, Json.ok(new Json.Obj()
                .put("agent", agent.id).put("query", q)
                .put("count", n).put("limit", limit)
                .putRaw("results", hits.toString())
                .toString()));
            return;
        }

        // ---- 按分类列方块 ----
        if (catName != null) {
            StringBuilder arr = new StringBuilder("[");
            boolean f = true;
            int n = 0;
            for (Block b : Vars.content.blocks()) {
                if (b.isHidden() || n >= limit) continue;
                if (b.category == null || !b.category.name().equalsIgnoreCase(catName)) continue;
                if (!f) arr.append(',');
                f = false; n++;
                arr.append(new Json.Obj().put("name", b.name)
                    .put("localizedName", blockNameOf(b))
                    .put("size", b.size)
                    .put("health", b.health)
                    .put("requirements", requirementsJson(b))
                    .toString());
            }
            arr.append(']');
            respond(ex, 200, Json.ok(new Json.Obj()
                .put("agent", agent.id).put("category", catName)
                .put("count", n).putRaw("blocks", arr.toString()).toString()));
            return;
        }

        // ---- 无参数：索引（分类清单 + 物品清单）----
        java.util.LinkedHashMap<String, Integer> cats = new java.util.LinkedHashMap<>();
        for (Block b : Vars.content.blocks()) {
            if (b.isHidden()) continue;
            String c = b.category == null ? "unknown" : b.category.name();
            cats.merge(c, 1, Integer::sum);
        }
        StringBuilder catArr = new StringBuilder("{");
        boolean cf2 = true;
        for (var e : cats.entrySet()) {
            if (!cf2) catArr.append(',');
            cf2 = false;
            catArr.append(Json.str(e.getKey())).append(':').append(e.getValue());
        }
        catArr.append('}');

        StringBuilder items = new StringBuilder("[");
        boolean if2 = true;
        for (mindustry.type.Item i : Vars.content.items()) {
            if (i.isHidden()) continue;
            if (!if2) items.append(',');
            if2 = false;
            items.append(new Json.Obj().put("name", i.name)
                .put("localizedName", itemNameOf(i))
                .put("hardness", i.hardness).toString());
        }
        items.append(']');

        respond(ex, 200, Json.ok(new Json.Obj()
            .put("agent", agent.id)
            .put("usage", "q=<关键词> 搜索 | item=<物品> 反查谁产谁吃 | cat=<分类> 列方块 | block=<方块> 详情")
            .put("categories", cats.size())
            .putRaw("categoryCounts", catArr.toString())
            .putRaw("items", items.toString())
            .toString()));
    }

    /** 名字 / 本地化名 / 介绍 任一命中即算匹配。 */
    private static boolean matches(String needle, String raw, String localized, String desc) {
        if (raw != null && raw.toLowerCase(java.util.Locale.ROOT).contains(needle)) return true;
        if (localized != null && localized.toLowerCase(java.util.Locale.ROOT).contains(needle)) return true;
        if (desc != null && desc.toLowerCase(java.util.Locale.ROOT).contains(needle)) return true;
        return false;
    }

    /** 这个方块是否产出该物品。 */
    private static boolean blockProducesItem(Block b, mindustry.type.Item it) {
        if (b instanceof mindustry.world.blocks.production.GenericCrafter gc) {
            if (gc.outputItem != null && gc.outputItem.item == it) return true;
            if (gc.outputItems != null) {
                for (var st : gc.outputItems) if (st.item == it) return true;
            }
        }
        if (b instanceof mindustry.world.blocks.production.Drill dr) {
            // 矿机能采它 —— 前提是硬度在 tier 之内
            if (it.hardness <= dr.tier) return true;
        }
        if (b instanceof mindustry.world.blocks.production.SolidPump sp) {
            // 抽水机那类：产的是液体，不算物品
        }
        return false;
    }

    /** 产出方式说明。 */
    private static String productionKind(Block b, mindustry.type.Item it) {
        if (b instanceof mindustry.world.blocks.production.Drill dr) {
            return "drill(tier " + dr.tier + ")";
        }
        return "crafter";
    }

    /** 这个方块是否消耗该物品。 */
    private static boolean blockConsumesItem(Block b, mindustry.type.Item it) {
        if (b.consumers == null) return false;
        for (var c : b.consumers) {
            if (c instanceof mindustry.world.consumers.ConsumeItems ci) {
                for (var st : ci.items) if (st.item == it) return true;
            }
            if (c instanceof mindustry.world.consumers.ConsumeItemFilter cif) {
                try { if (cif.filter.get(it)) return true; } catch (Throwable ignored) {}
            }
        }
        return false;
    }

    /** 消耗方式说明。 */
    private static String consumptionKind(Block b, mindustry.type.Item it) {
        if (b.consumers == null) return "unknown";
        for (var c : b.consumers) {
            if (c instanceof mindustry.world.consumers.ConsumeItems ci) {
                for (var st : ci.items) {
                    if (st.item == it) return "items x" + st.amount;
                }
            }
            if (c instanceof mindustry.world.consumers.ConsumeItemFilter) return "filter(动态)";
        }
        return "unknown";
    }

    private static String requirementsJson(Block b) {
        StringBuilder sb = new StringBuilder("{");
        boolean f = true;
        if (b.requirements != null) {
            for (var st : b.requirements) {
                if (!f) sb.append(',');
                f = false;
                sb.append(Json.str(st.item.name)).append(':').append(st.amount);
            }
        }
        return sb.append('}').toString();
    }

    // 物品 / 单位 / 液体的文案，同样要走自建 bundle（无头服务端没有）
    private static String itemNameOf(mindustry.type.Item i) {
        ensureBundle();
        if (modBundle instanceof arc.util.I18NBundle bd) {
            String s = bd.get("item." + i.name + ".name", null);
            if (s != null && !s.isEmpty()) return s;
        }
        return i.localizedName != null && !i.localizedName.isEmpty() ? i.localizedName : i.name;
    }

    private static String itemDescOf(mindustry.type.Item i) {
        ensureBundle();
        if (modBundle instanceof arc.util.I18NBundle bd) {
            String s = bd.getOrNull("item." + i.name + ".description");
            if (s != null) return s;
        }
        return i.description == null ? "" : i.description;
    }

    private static String unitNameOf(mindustry.type.UnitType u) {
        ensureBundle();
        if (modBundle instanceof arc.util.I18NBundle bd) {
            String s = bd.get("unit." + u.name + ".name", null);
            if (s != null && !s.isEmpty()) return s;
        }
        return u.localizedName != null && !u.localizedName.isEmpty() ? u.localizedName : u.name;
    }

    private static String unitDescOf(mindustry.type.UnitType u) {
        ensureBundle();
        if (modBundle instanceof arc.util.I18NBundle bd) {
            String s = bd.getOrNull("unit." + u.name + ".description");
            if (s != null) return s;
        }
        return u.description == null ? "" : u.description;
    }

    private static String liquidNameOf(mindustry.type.Liquid l) {
        ensureBundle();
        if (modBundle instanceof arc.util.I18NBundle bd) {
            String s = bd.get("liquid." + l.name + ".name", null);
            if (s != null && !s.isEmpty()) return s;
        }
        return l.localizedName != null && !l.localizedName.isEmpty() ? l.localizedName : l.name;
    }

    private static String liquidDescOf(mindustry.type.Liquid l) {
        ensureBundle();
        if (modBundle instanceof arc.util.I18NBundle bd) {
            String s = bd.getOrNull("liquid." + l.name + ".description");
            if (s != null) return s;
        }
        return l.description == null ? "" : l.description;
    }

    // ---- 方块文案：无头服务端没有 bundle，得自己建 ----    //
    // ServerLauncher.java:44 写着 loadLocales = false —— 无头服务端主动关掉了
    // 本地化加载。于是 UnlockableContent.load() 里的
    //     localizedName = Core.bundle.get("block." + name + ".name", name)
    // 拿到的是空串，description 也是 null。游戏内点开方块看到的那些文字，
    // 在无头环境下必须自己从 bundles/ 里读。
    private static Object modBundle = null;
    private static boolean bundleTried = false;

    private static void ensureBundle() {
        if (bundleTried) return;
        bundleTried = true;
        // server-release.jar 里**没有** bundles/ 目录（只有客户端 jar 有），
        // 所以 internal() 一定失败。改成先读工作目录下的 bundles/，
        // 由部署脚本从客户端 jar 抽出来放好。
        String[] candidates = {"bundles/bundle", "bundles/bundle_zh_CN", "bundles/bundle_en"};
        for (String path : candidates) {
            try {
                var f = arc.Core.files.local(path);
                if (f == null || !f.exists()) continue;
                modBundle = arc.util.I18NBundle.createBundle(f, java.util.Locale.getDefault());
                AIArena.log("loaded bundle for block descriptions: " + path);
                return;
            } catch (Throwable t) {
                AIArena.log("bundle candidate " + path + " failed: " + t);
            }
        }
        // 兜底：万一 classpath 里有
        try {
            modBundle = arc.util.I18NBundle.createBundle(
                arc.Core.files.internal("bundles/bundle"), java.util.Locale.getDefault());
            AIArena.log("loaded bundle from classpath");
        } catch (Throwable t) {
            AIArena.log("no bundle available; block descriptions will be empty");
        }
    }

    private static String blockKey(Block b, String suffix) {
        return "block." + b.name + "." + suffix;
    }

    private static String blockNameOf(Block b) {
        // 先查 bundle。不能先看 b.localizedName —— 内容加载时它已被赋成
        // fallback（也就是 name 本身），非空但没用。bundle 才是权威文案。
        ensureBundle();
        if (modBundle instanceof arc.util.I18NBundle bd) {
            String s = bd.get(blockKey(b, "name"), null);
            if (s != null && !s.isEmpty()) return s;
        }
        return b.localizedName != null && !b.localizedName.isEmpty() ? b.localizedName : b.name;
    }

    private static String blockDescOf(Block b) {
        if (b.description != null && !b.description.isEmpty()) return b.description;
        ensureBundle();
        if (modBundle instanceof arc.util.I18NBundle bd) {
            String s = bd.getOrNull(blockKey(b, "description"));
            return s == null ? "" : s;
        }
        return "";
    }

    private static String blockDetailsOf(Block b) {
        if (b.details != null && !b.details.isEmpty()) return b.details;
        ensureBundle();
        if (modBundle instanceof arc.util.I18NBundle bd) {
            String s = bd.getOrNull(blockKey(b, "details"));
            return s == null ? "" : s;
        }
        return "";
    }
    private static void handleBlock(HttpExchange ex, AIArena.Agent agent) {
        Params p = Params.of(ex);
        String name = p.get("name", null);

        postToGame(ex, () -> {
            if (name == null) {
                StringBuilder arr = new StringBuilder("[");
                boolean first = true;
                for (Block b : Vars.content.blocks()) {
                    if (b.isHidden() || !b.isPlaceable()) continue;
                    if (!first) arr.append(',');
                    first = false;
                    arr.append(new Json.Obj()
                        .put("name", b.name)
                        .put("localizedName", blockNameOf(b))
                        .put("size", b.size)
                        .put("category", b.category == null ? "" : b.category.name())
                        .toString());
                }
                arr.append(']');
                return Json.ok(new Json.Obj().putRaw("blocks", arr.toString()).toString());
            }

            Block b = Vars.content.block(name);
            if (b == null) return Json.error(1002, "no block named " + name);

            // 材料
            StringBuilder req = new StringBuilder("{");
            boolean rf = true;
            if (b.requirements != null) {
                for (var stack : b.requirements) {
                    if (!rf) req.append(',');
                    rf = false;
                    req.append(Json.str(stack.item.name)).append(':').append(stack.amount);
                }
            }
            req.append('}');

            // 输入
            StringBuilder ins = new StringBuilder("[");
            boolean inf = true;
            for (var cons : b.consumers) {
                Json.Obj o = null;
                if (cons instanceof mindustry.world.consumers.ConsumeItems ci) {
                    StringBuilder its = new StringBuilder("[");
                    boolean f2 = true;
                    for (var st : ci.items) {
                        if (!f2) its.append(',');
                        f2 = false;
                        its.append(new Json.Obj().put("item", st.item.name).put("amount", st.amount).toString());
                    }
                    its.append(']');
                    o = new Json.Obj().put("kind", "items").putRaw("items", its.toString());
                } else if (cons instanceof mindustry.world.consumers.ConsumeItemDynamic) {
                    o = new Json.Obj().put("kind", "dynamic-item")
                         .put("note", "随方块配置变化，见 plans / 运行时 /factory");
                } else if (cons instanceof mindustry.world.consumers.ConsumeItemFilter) {
                    o = new Json.Obj().put("kind", "item-filter")
                         .put("note", "按谓词过滤，静态查不出具体物品");
                } else if (cons instanceof mindustry.world.consumers.ConsumeLiquid cl) {
                    o = new Json.Obj().put("kind", "liquid")
                         .put("liquid", cl.liquid.name).put("amount", cl.amount);
                } else if (cons instanceof mindustry.world.consumers.ConsumeLiquids cls) {
                    StringBuilder ls = new StringBuilder("[");
                    boolean f2 = true;
                    for (var st : cls.liquids) {
                        if (!f2) ls.append(',');
                        f2 = false;
                        ls.append(new Json.Obj().put("liquid", st.liquid.name).put("amount", st.amount).toString());
                    }
                    ls.append(']');
                    o = new Json.Obj().put("kind", "liquids").putRaw("liquids", ls.toString());
                } else if (cons instanceof mindustry.world.consumers.ConsumePower cp) {
                    o = new Json.Obj().put("kind", "power").put("amount", cp.usage);
                } else if (cons instanceof mindustry.world.consumers.ConsumePayloads) {
                    o = new Json.Obj().put("kind", "payload").put("note", "需要输入载荷");
                }
                if (o == null) continue;
                if (!inf) ins.append(',');
                inf = false;
                ins.append(o.toString());
            }
            ins.append(']');

            // 输出
            StringBuilder outs = new StringBuilder("[");
            boolean outf = true;
            if (b instanceof mindustry.world.blocks.production.GenericCrafter gc) {
                if (gc.outputItems != null) {
                    for (var st : gc.outputItems) {
                        if (!outf) outs.append(',');
                        outf = false;
                        outs.append(new Json.Obj().put("kind", "item")
                            .put("item", st.item.name).put("amount", st.amount).toString());
                    }
                }
                if (gc.outputLiquids != null) {
                    for (var st : gc.outputLiquids) {
                        if (!outf) outs.append(',');
                        outf = false;
                        outs.append(new Json.Obj().put("kind", "liquid")
                            .put("liquid", st.liquid.name).put("amount", st.amount).toString());
                    }
                }
            }
            if (b instanceof mindustry.world.blocks.units.UnitFactory uf) {
                for (var plan : uf.plans) {
                    if (!outf) outs.append(',');
                    outf = false;
                    StringBuilder pr = new StringBuilder("{");
                    boolean f2 = true;
                    for (var st : plan.requirements) {
                        if (!f2) pr.append(',');
                        f2 = false;
                        pr.append(Json.str(st.item.name)).append(':').append(st.amount);
                    }
                    pr.append('}');
                    outs.append(new Json.Obj().put("kind", "unit")
                        .put("unit", plan.unit.name)
                        .put("timeSeconds", plan.time / 60f)
                        .putRaw("requirements", pr.toString())
                        .toString());
                }
            }
            if (b instanceof mindustry.world.blocks.production.Drill dr) {
                if (!outf) outs.append(',');
                outf = false;
                outs.append(new Json.Obj().put("kind", "ore")
                    .put("tier", dr.tier)
                    .put("note", "产出取决于脚下矿脉，用 /ore 查具体坐标").toString());
            }
            float pp = (b instanceof mindustry.world.blocks.power.PowerGenerator pg) ? pg.powerProduction : 0f;
            if (pp > 0) {
                if (!outf) outs.append(',');
                outf = false;
                outs.append(new Json.Obj().put("kind", "power")
                    .put("amount", pp).toString());
            }
            outs.append(']');

            return Json.ok(new Json.Obj()
                .put("name", b.name)
                .put("localizedName", blockNameOf(b))
                .put("description", blockDescOf(b))
                .put("details", blockDetailsOf(b))
                .put("category", b.category == null ? "" : b.category.name())
                .put("size", b.size)
                .put("health", b.health)
                .put("hasPower", b.hasPower)
                .put("hasItems", b.hasItems)
                .put("hasLiquids", b.hasLiquids)
                .put("itemCapacity", b.itemCapacity)
                .put("powerProduction", (b instanceof mindustry.world.blocks.power.PowerGenerator pg2) ? pg2.powerProduction : 0f)
                .putRaw("requirements", req.toString())
                .putRaw("inputs", ins.toString())
                .putRaw("outputs", outs.toString())
                .toString());
        });
    }

    /**
     * 这一格放矿机会产出什么。GET /v1/{agent}/ore?x=&y=&block=<drillName>
     *
     * 这是 Drill.countOre() 的静态版本：按方块尺寸算出 footprint，
     * 数出各矿种的格子数，取最多的那个当 dominantItem，
     * 再拿 block.tier 和矿的 hardness 比 —— 和引擎运行时判定同一套规则。
     *
     * 不带 block 时默认用 mechanical-drill。
     */
    private static void handleOre(HttpExchange ex, AIArena.Agent agent) {
        Params p = Params.of(ex);
        int x = p.getInt("x", Integer.MIN_VALUE);
        int y = p.getInt("y", Integer.MIN_VALUE);
        if (x == Integer.MIN_VALUE || y == Integer.MIN_VALUE) {
            respond(ex, 400, Json.error(1001, "required: x, y (tile coords)"));
            return;
        }
        String blockName = p.get("block", "mechanical-drill");

        postToGame(ex, () -> {
            Block blk = Vars.content.block(blockName);
            if (blk == null) return Json.error(1002, "no block named " + blockName);
            if (!(blk instanceof mindustry.world.blocks.production.Drill dr)) {
                return Json.error(1001, blockName + " is not a drill");
            }

            Tile t = Vars.world.tile(x, y);
            if (t == null) return Json.error(1003, "tile out of bounds: (" + x + "," + y + ")");

            int size = blk.size;
            int off = -((size - 1) / 2);
            java.util.Map<String, Integer> counts = new java.util.LinkedHashMap<>();
            StringBuilder tiles = new StringBuilder("[");
            boolean first = true;
            int free = 0;

            for (int dx = 0; dx < size; dx++) {
                for (int dy = 0; dy < size; dy++) {
                    Tile tl = Vars.world.tile(x + off + dx, y + off + dy);
                    if (tl == null) continue;
                    if (tl.block() == mindustry.content.Blocks.air) free++;
                    var drop = tl.drop();
                    if (drop == null) continue;
                    counts.merge(drop.name, 1, Integer::sum);
                    if (!first) tiles.append(',');
                    first = false;
                    tiles.append(new Json.Obj()
                        .put("x", tl.x).put("y", tl.y)
                        .put("item", drop.name)
                        .put("hardness", drop.hardness)
                        .put("mineable", dr.tier >= drop.hardness)
                        .toString());
                }
            }
            tiles.append(']');

            String dominant = "";
            int best = 0;
            for (var e : counts.entrySet()) {
                if (e.getValue() > best) { best = e.getValue(); dominant = e.getKey(); }
            }
            var domItem = dominant.isEmpty() ? null : Vars.content.item(dominant);

            Team reqTeam = agent.team() == null ? Team.sharded : agent.team();
            boolean canPlace = mindustry.world.Build.validPlace(blk, reqTeam, x, y, 0);

            return Json.ok(new Json.Obj()
                .put("x", x).put("y", y)
                .put("block", blk.name)
                .put("tier", dr.tier)
                .put("dominantItem", dominant)
                .put("dominantItems", best)
                .put("oreHardness", domItem == null ? -1 : domItem.hardness)
                .put("canMine", domItem != null && dr.tier >= domItem.hardness)
                .put("freeTiles", free)
                .put("footprintTiles", size * size)
                .put("validPlace", canPlace)
                .putRaw("oreTiles", tiles.toString())
                .toString());
        });
    }
    private static void handleDrill(HttpExchange ex, AIArena.Agent agent) {
        Team team = agent.team();
        if (team == null) { respond(ex, 403, Json.error(1403, "agent has no team")); return; }

        postToGame(ex, () -> {
            StringBuilder arr = new StringBuilder("[");
            boolean first = true;

            for (mindustry.gen.Building b : team.data().buildings) {
                if (!(b instanceof mindustry.world.blocks.production.Drill.DrillBuild)) continue;
                if (Vars.state.rules.fog && !Vars.fogControl.isVisibleTile(team, b.tileX(), b.tileY())) continue;

                var d = (mindustry.world.blocks.production.Drill.DrillBuild) b;
                var blk = (mindustry.world.blocks.production.Drill) b.block;

                if (!first) arr.append(',');
                first = false;

                StringBuilder inv = new StringBuilder("{");
                boolean vf = true;
                for (mindustry.type.Item it : Vars.content.items()) {
                    int amt = b.items.get(it);
                    if (amt <= 0) continue;
                    if (!vf) inv.append(',');
                    vf = false;
                    inv.append(Json.str(it.name)).append(':').append(amt);
                }
                inv.append('}');

                // 脚下覆盖的格子，标出哪些有矿
                StringBuilder ore = new StringBuilder("[");
                boolean of = true;
                int size = blk.size;
                int off = -((size - 1) / 2);
                for (int dx = 0; dx < size; dx++) {
                    for (int dy = 0; dy < size; dy++) {
                        Tile tl = Vars.world.tile(b.tileX() + off + dx, b.tileY() + off + dy);
                        if (tl == null) continue;
                        String drop = tl.drop() == null ? "" : tl.drop().name;
                        if (drop.isEmpty()) continue;
                        if (!of) ore.append(',');
                        of = false;
                        ore.append(new Json.Obj()
                            .put("x", tl.x).put("y", tl.y)
                            .put("item", drop)
                            .put("hardness", tl.drop().hardness)
                            .toString());
                    }
                }
                ore.append(']');

                int oreH = d.dominantItem == null ? -1 : d.dominantItem.hardness;

                arr.append(new Json.Obj()
                    .put("x", b.tileX()).put("y", b.tileY())
                    .put("block", b.block.name)
                    .put("tier", blk.tier)
                    .put("dominantItem", d.dominantItem == null ? "" : d.dominantItem.name)
                    .put("dominantItems", d.dominantItems)
                    .put("oreHardness", oreH)
                    .put("canMine", d.dominantItem != null && blk.tier >= oreH)
                    .put("progress", d.progress())
                    .put("warmup", d.warmup)
                    .put("lastDrillSpeed", d.lastDrillSpeed)
                    .put("itemsPerSecond", d.lastDrillSpeed * 60f)
                    .put("dominantItems", d.dominantItems)
                    .put("efficiency", b.efficiency)
                    .put("enabled", b.enabled)
                    .put("full", b.items.total() >= b.block.itemCapacity)
                    .put("itemCapacity", b.block.itemCapacity)
                    .putRaw("items", inv.toString())
                    .putRaw("oreTiles", ore.toString())
                    .toString());
            }
            arr.append(']');

            return Json.ok(new Json.Obj()
                .put("agent", agent.id).put("team", team.name)
                .put("tick", (int) Vars.state.tick)
                .putRaw("drills", arr.toString())
                .toString());
        });
    }
    private static void handleMine(HttpExchange ex, AIArena.Agent agent) {
        Params p = Params.of(ex);
        int unitId = p.getInt("unit", -1);
        Team team = agent.team();
        if (team == null) { respond(ex, 403, Json.error(1403, "agent has no team")); return; }
        if (unitId < 0) { respond(ex, 400, Json.error(1001, "required: unit=<id>")); return; }

        postToGame(ex, () -> {
            var u = mindustry.gen.Groups.unit.getByID(unitId);
            if (u == null) return Json.error(1002, "no unit with id " + unitId);
            if (u.team != team) {
                return Json.error(1005, "unit " + unitId + " belongs to " + u.team.name);
            }

            if (p.getBool("clear", false)) {
                u.mineTile = null;
                return Json.ok(new Json.Obj()
                    .put("message", "unit " + unitId + " stopped mining").toString());
            }

            int x = p.getInt("x", Integer.MIN_VALUE);
            int y = p.getInt("y", Integer.MIN_VALUE);
            if (x == Integer.MIN_VALUE || y == Integer.MIN_VALUE) {
                return Json.error(1001, "required: x, y (tile coords) or clear=true");
            }

            Tile t = Vars.world.tile(x, y);
            if (t == null) return Json.error(1003, "tile out of bounds: (" + x + "," + y + ")");

            // 原版判定：单位能不能挖这种矿（mineTier vs 硬度）、够不够得着（mineRange）
            if (!u.canMine()) {
                return Json.error(1005, "unit type " + u.type.name + " cannot mine (mineSpeed/mineTier)");
            }
            if (!u.validMine(t)) {
                mindustry.type.Item drop = t.drop();
                return Json.error(1005,
                    "unit " + unitId + " cannot mine (" + x + "," + y + "): "
                  + "drop=" + (drop == null ? "none" : drop.name)
                  + " hardness=" + (drop == null ? "-" : drop.hardness)
                  + " mineTier=" + u.type.mineTier
                  + " dist=" + (int) (u.dst(t.worldx(), t.worldy()) / Vars.tilesize) + "t"
                  + " mineRange=" + (int) (u.type.mineRange / Vars.tilesize) + "t");
            }

            u.mineTile = t;
            return Json.ok(new Json.Obj()
                .put("message", "unit " + unitId + " mining (" + x + "," + y + ")")
                .put("drop", t.drop() == null ? "" : t.drop().name)
                .toString());
        });
    }
    /**
     * 单位工厂的生产状态。GET /v1/{agent}/factory
     *
     * 为什么要单独一个端点：单位现在必须由工厂生产，而「工厂在造什么、造到几成、
     * 缺不缺电」是 AI 做决策的必要输入。塞进 /buildings 会让每帧快照变重，
     * 而且工厂数量很少，单独查更省。
     *
     * 返回己方所有 unit factory / fabricator / assembler 的：
     *   plan       当前选中的产线（单位名），未选则为空
     *   progress   0..1
     *   efficiency 电力充足度，0 表示没电（生产会停）
     *   requirements 这条产线需要的物品
     *   items      工厂当前库存
     */
    private static void handleFactory(HttpExchange ex, AIArena.Agent agent) {
        Team team = agent.team();
        if (team == null) { respond(ex, 403, Json.error(1403, "agent has no team")); return; }

        postToGame(ex, () -> {
            StringBuilder arr = new StringBuilder("[");
            boolean first = true;

            for (mindustry.gen.Building b : team.data().buildings) {
                if (b == null) continue;
                boolean isFactory = b instanceof mindustry.world.blocks.units.UnitFactory.UnitFactoryBuild;
                boolean isAssembler = b instanceof mindustry.world.blocks.units.UnitAssembler.UnitAssemblerBuild;
                if (!isFactory && !isAssembler) continue;

                // 视野：己方建筑总是可见，这里只做一致性检查
                if (Vars.state.rules.fog && !Vars.fogControl.isVisibleTile(team, b.tileX(), b.tileY())) continue;

                if (!first) arr.append(',');
                first = false;

                Json.Obj o = new Json.Obj()
                    .put("x", b.tileX()).put("y", b.tileY())
                    .put("block", b.block.name)
                    .put("efficiency", b.efficiency)
                    .put("enabled", b.enabled)
                    .put("powered", b.power != null && b.power.status > 0f);

                if (isFactory) {
                    var uf = (mindustry.world.blocks.units.UnitFactory.UnitFactoryBuild) b;
                    var ut = uf.unit();
                    o.put("plan", ut == null ? "" : ut.name);
                    o.put("progress", uf.fraction());
                    o.put("planIndex", uf.currentPlan);
                    // 诊断：成品单位是以 payload 形式待在工厂里的，靠 moveOutPayload() 弹出。
                    // 弹不出去就 payload != null -> shouldConsume() 永久 false -> efficiency 0
                    // -> 工厂彻底卡死（实测就是产线爬到 100% 之后再也不动）。
                    o.put("payload", uf.payload == null ? "" : uf.payload.getClass().getSimpleName());
                    String puName = "";
                    if (uf.payload instanceof mindustry.world.blocks.payloads.UnitPayload) {
                        puName = ((mindustry.world.blocks.payloads.UnitPayload) uf.payload).unit.type.name;
                    }
                    o.put("payloadUnit", puName);
                    o.put("payloadVec", (int) uf.payVector.len());
                    o.put("rotation", uf.rotation);
                    o.put("shouldConsume", uf.shouldConsume());
                    o.put("activation", b.team.activateUnitFactories());
                    String frontName = "";
                    boolean frontSolid = false;
                    try {
                        mindustry.gen.Building fr = uf.front();
                        if (fr != null) {
                            frontName = fr.block.name;
                            frontSolid = fr.tile != null && fr.tile.solid();
                        }
                    } catch (Throwable ignored) {}
                    o.put("front", frontName);
                    o.put("frontSolid", frontSolid);

                    StringBuilder req = new StringBuilder("{");
                    boolean rf = true;
                    if (ut != null && uf.currentPlan >= 0 && uf.currentPlan < ((mindustry.world.blocks.units.UnitFactory) uf.block).plans.size) {
                        for (var stack : ((mindustry.world.blocks.units.UnitFactory) uf.block).plans.get(uf.currentPlan).requirements) {
                            if (!rf) req.append(',');
                            rf = false;
                            req.append(Json.str(stack.item.name)).append(':').append(stack.amount);
                        }
                    }
                    req.append('}');
                    o.putRaw("requirements", req.toString());

                    StringBuilder inv = new StringBuilder("{");
                    boolean vf = true;
                    for (mindustry.type.Item it : Vars.content.items()) {
                        int amt = b.items.get(it);
                        if (amt <= 0) continue;
                        if (!vf) inv.append(',');
                        vf = false;
                        inv.append(Json.str(it.name)).append(':').append(amt);
                    }
                    inv.append('}');
                    o.putRaw("items", inv.toString());
                }

                arr.append(o.toString());
            }
            arr.append(']');

            return Json.ok(new Json.Obj()
                .put("agent", agent.id).put("team", team.name)
                .put("tick", (int) Vars.state.tick)
                .putRaw("factories", arr.toString())
                .toString());
        });
    }
    private static void handleConfig(HttpExchange ex, AIArena.Agent agent) {
        Params p = Params.of(ex);
        int x = p.getInt("x", Integer.MIN_VALUE);
        int y = p.getInt("y", Integer.MIN_VALUE);
        String value = p.get("value", null);
        if (x == Integer.MIN_VALUE || y == Integer.MIN_VALUE || value == null) {
            respond(ex, 400, Json.error(1001, "required: x, y, value"));
            return;
        }
        Team team = agent.team();
        if (team == null) { respond(ex, 403, Json.error(1403, "agent has no team")); return; }

        postToGame(ex, () -> {
            Actor.Result r = Actor.configure(team, x, y, value);
            return r.ok ? Json.ok(new Json.Obj().put("message", r.message).toString())
                        : Json.error(r.code, r.message);
        });
    }

    /**
     * 录像控制（DESIGN.md P6）。仅 admin。
     *
     * GET  /v1/{admin}/record                 查看状态 + 已有录像列表
     * POST /v1/{admin}/record?action=start&label=<name>
     * POST /v1/{admin}/record?action=stop
     *
     * 录制内容写入 config/ai-arena-recordings/<时间戳>-<label>.jsonl，
     * 格式为 JSON Lines —— 客户端用与实时同一套解析器逐行读。
     */
    private static void handleRecord(HttpExchange ex, AIArena.Agent agent) {
        if (!agent.admin) {
            respond(ex, 403, Json.error(1403, "record control requires an admin token"));
            return;
        }
        Params p = Params.of(ex);
        String action = p.get("action", null);

        if (action == null) {
            respond(ex, 200, Json.ok(new Json.Obj()
                .put("recording", Recorder.isRecording())
                .put("status", Recorder.status())
                .putRaw("files", Recorder.listFiles())
                .toString()));
            return;
        }

        switch (action) {
            case "start" -> {
                String name = Recorder.start(p.get("label", "match"));
                if (name == null) respond(ex, 500, Json.error(1500, "failed to start recording"));
                else respond(ex, 200, Json.ok(new Json.Obj()
                    .put("message", "recording to " + name).toString()));
            }
            case "stop" -> {
                Recorder.stop();
                respond(ex, 200, Json.ok(new Json.Obj()
                    .put("message", "recording stopped").toString()));
            }
            case "download" -> {
                // 客户端回放需要取走录像文件。只允许读取 recordings 目录下的 .jsonl，
                // 文件名做严格过滤，避免路径穿越。
                String name = p.get("name", null);
                if (name == null || !name.matches("[A-Za-z0-9_.\\-]+\\.jsonl")) {
                    respond(ex, 400, Json.error(1001, "invalid recording name"));
                    return;
                }
                var dir = Core.settings.getDataDirectory().child("ai-arena-recordings");
                var f = dir.child(name);
                if (!f.exists()) {
                    respond(ex, 404, Json.error(1002, "recording not found: " + name));
                    return;
                }
                try {
                    byte[] data = f.readBytes();
                    ex.getResponseHeaders().set("Content-Type", "application/x-ndjson; charset=utf-8");
                    ex.getResponseHeaders().set("Content-Disposition", "attachment; filename=\"" + name + "\"");
                    ex.sendResponseHeaders(200, data.length);
                    try (var os = ex.getResponseBody()) { os.write(data); }
                } catch (Throwable t) {
                    respond(ex, 500, Json.error(1500, "failed to read recording: " + t));
                }
            }
            default -> respond(ex, 400, Json.error(1001, "unknown action: " + action));
        }
    }

    /**
     * 迷雾开关。仅 admin。
     *
     * 观战时有两套迷雾机制，各有各的问题：
     *
     *   静态迷雾（staticFog = true）
     *     服务器把「每队已探索的格位图」同步给客户端（FogControl.shouldWrite）。
     *     切队时位图跟着换，迷雾会正确更新。但观察者必须属于某个有视野的队，
     *     derelict 队的位图是空的，照样全黑。
     *
     *   动态迷雾（staticFog = false）
     *     客户端按「自己单位/建筑的视野半径」实时算。同样要求观察者有单位。
     *
     * 也就是说，**客户端侧的迷雾永远取决于观察者自己队伍的视野源**。
     * 想让观察者看到全图，要么给它一个单位，要么把 fog 整个关掉。
     *
     * 关掉 fog 会同时让 AI 看到全图（服务端 safeVisible 也读这个开关），
     * 也就是破坏对等约束 —— 所以这是裁判工具，不是常规观战手段。
     *
     * GET  /v1/{admin}/fog                  查看当前设置
     * POST /v1/{admin}/fog?fog=false        关掉迷雾
     * POST /v1/{admin}/fog?fog=true&static=true   打开（含静态位图同步）
     */
    private static void handleFog(HttpExchange ex, AIArena.Agent agent) {
        if (!agent.admin) {
            respond(ex, 403, Json.error(1403, "fog control requires an admin token"));
            return;
        }
        Params p = Params.of(ex);
        String fogParam = p.get("fog", null);

        postToGame(ex, () -> {
            var r = Vars.state.rules;

            if (fogParam == null) {
                return Json.ok(new Json.Obj()
                    .put("fog", r.fog)
                    .put("staticFog", r.staticFog)
                    .put("pvp", r.pvp)
                    .put("note", "client-side fog depends on the viewer team's own vision sources")
                    .toString());
            }

            boolean on = Boolean.parseBoolean(fogParam);
            boolean stat = p.get("static", null) == null || Boolean.parseBoolean(p.get("static", "true"));

            r.fog = on;
            r.staticFog = on && stat;

            // 位图需要重置，否则客户端拿到的是上一局的旧数据
            try { Vars.fogControl.resetFog(); } catch (Throwable ignored) {}

            // 让客户端重新加载世界状态（rules 变了），并重置迷雾位图
            try {
                for (var pl : mindustry.gen.Groups.player) {
                    // 玩家可能正在断开，con 会是 null —— sendWorldData 内部
                    // 直接读 player.con.hasConnected，不判空就抛 NPE
                    if (pl == null || pl.con == null) continue;
                    pl.sendMessage("[accent]裁判调整了迷雾: fog=" + r.fog + " staticFog=" + r.staticFog);
                    Vars.netServer.sendWorldData(pl);
                }
            } catch (Throwable ignored) {}

            return Json.ok(new Json.Obj()
                .put("message", "fog=" + r.fog + " staticFog=" + r.staticFog)
                .put("fog", r.fog)
                .put("staticFog", r.staticFog).toString());
        });
    }

    /**
     * 强制把对局切到 playing。仅 admin。
     *
     * Mindustry 在 host 之后会进入「等待玩家」状态，需要足够玩家才自动开始
     * （PvP 图要求每个核心队都有人）。这个端点跳过那个等待，直接开打，
     * 让 HTTP 驱动的 AI 可以在没有真人玩家的情况下对局。
     */
    private static void handleStart(HttpExchange ex, AIArena.Agent agent) {
        if (!agent.admin) {
            respond(ex, 403, Json.error(1403, "start requires an admin token"));
            return;
        }
        postToGame(ex, () -> {
            // 关掉所有会自动暂停的机制。
            //
            // 引擎有两处独立的「没玩家就暂停」：
            //   ServerControl:321  Config.autoPause —— Groups.player.isEmpty() 就暂停
            //   NetServer:1056     rules.pvpAutoPause —— PvP 图等待玩家就暂停
            //
            // 第二条是我们的 setup 自己触发的（它设了 pvp = true），
            // 所以 /start 把状态设成 playing 之后会立刻被它改回 paused。
            // 这个竞技场里没有真人玩家，AI 全走 HTTP，必须关掉。
            var r = Vars.state.rules;
            r.pvpAutoPause = false;
            r.pauseDisabled = true;

            // 还有 server.properties 里的 autoPause
            try {
                mindustry.net.Administration.Config.autoPause.set(false);
            } catch (Throwable ignored) {}

            if (Vars.state.getState() != mindustry.core.GameState.State.playing) {
                Vars.state.set(mindustry.core.GameState.State.playing);
            }

            // 切到 playing 同样会清掉实体。实测 start 之后单位从 3 变 0 ——
            // 玩家在 host 那一步已经没了，孤立的单位随后被清掉，于是整局没有
            // 任何单位，AI 无兵可用。这里再重建一次，保证开打时每个 agent
            // 都有玩家（玩家在 → PlayerComp 自动从核心生成单位）。
            StringBuilder log = new StringBuilder();
            int n = ensureAgentPlayers(log);

            return Json.ok(new Json.Obj()
                .put("message", "state=" + Vars.state.getState().name()
                                + " pvpAutoPause=false pauseDisabled=true autoPause=false"
                                + "; re-created " + n + " AI player(s)")
                .put("state", Vars.state.getState().name())
                .put("tick", (int) Vars.state.tick)
                .put("players", mindustry.gen.Groups.player.size())
                .put("units", mindustry.gen.Groups.unit.size())
                .put("agents", n)
                .put("pvpAutoPause", r.pvpAutoPause)
                .put("pauseDisabled", r.pauseDisabled).toString());
        });
    }

    /**
     * 打开游戏端口，让 Mindustry 客户端能连进来观战。仅 admin。
     *
     * headless 服务器默认**不会**自动监听游戏端口 —— NetServer.openServer()
     * 正常由控制台 `host` 命令触发，而这个服务器是用 -jar 起的、stdin 被重定向，
     * 所以从来没开过。结果是客户端根本连不进来。
     *
     * GET /v1/{admin}/host          查看状态
     * POST /v1/{admin}/host         打开端口
     */
    private static void handleHost(HttpExchange ex, AIArena.Agent agent) {
        if (!agent.admin) {
            respond(ex, 403, Json.error(1403, "host control requires an admin token"));
            return;
        }
        Params p = Params.of(ex);
        String action = p.get("action", "open");

        postToGame(ex, () -> {
            if (Vars.netServer == null) {
                return Json.error(1500, "netServer is not available");
            }

            int port;
            try {
                port = mindustry.net.Administration.Config.port.num();
            } catch (Throwable t) {
                port = 6567;
            }

            if (action.equals("status")) {
                boolean open = Vars.net != null && Vars.net.server();
                return Json.ok(new Json.Obj()
                    .put("open", open)
                    .put("port", port)
                    .put("players", mindustry.gen.Groups.player.size())
                    .put("state", Vars.state.getState().name()).toString());
            }

            if (Vars.net != null && Vars.net.server()) {
                return Json.ok(new Json.Obj()
                    .put("message", "already hosting on port " + port)
                    .put("port", port).toString());
            }

            try {
                Vars.netServer.openServer();

                // openServer() 会清空 Groups.player —— setup 里建的 AI 玩家全没了。
                // 实测（每秒采样）：
                //     setup 之后  玩家=3 单位=3
                //     host  之后  玩家=0 单位=3   ← 玩家被清掉
                //     start 之后  玩家=0 单位=0   ← 孤立单位随后也没了
                // 没有玩家就没有 PlayerComp 去 requestSpawn，AI 会一动不动。
                // 所以每次开端口之后都要把 AI 玩家重建一遍。
                StringBuilder log = new StringBuilder();
                int n = ensureAgentPlayers(log);

                return Json.ok(new Json.Obj()
                    .put("message", "opened server on port " + port
                                    + "; re-created " + n + " AI player(s) after openServer() cleared Groups.player")
                    .put("port", port)
                    .put("agents", n).toString());
            } catch (Throwable t) {
                return Json.error(1500, "host failed: " + t);
            }
        });
    }

    /**
     * 清掉本 mod 创建过的所有 AI 玩家。
     *
     * 每次 setup / host / start 都会重建，先清一遍可以避免同一个 agent 累积出
     * 好几个同名 Player（每个都还在 Groups.player 里跑 update）。
     */
    private static void clearAgentPlayers() {
        java.util.List<mindustry.gen.Player> stale = new java.util.ArrayList<>();
        for (mindustry.gen.Player p : mindustry.gen.Groups.player) {
            if (p != null && p.name != null && p.name.startsWith("[AI] ")) stale.add(p);
        }
        for (mindustry.gen.Player p : stale) {
            try { p.remove(); } catch (Throwable ignored) {}
        }
        for (AIArena.Agent a : AIArena.agents) a.bindPlayer(null);
    }

    /**
     * 为所有已绑定队伍、但当前**没有玩家对象**的 agent 补建玩家（非破坏性）。
     *
     * 只补缺，不动已经存在的玩家 —— 破坏性重建会连带清掉玩家手上的单位。
     *
     * 引擎的 PlayerComp.update() 会自动给「有核心但没单位的玩家」生成初始单位，
     * 所以只要玩家在、队伍有核心，单位就会自己出现，不需要手动 spawn。
     *
     * @return 新建的玩家数
     */
    static int ensureAgentPlayers(StringBuilder log) {
        int created = 0;

        // 先清掉同名重复的 AI 玩家。
        //
        // 早期版本只认 agent 里存的那个 player() 引用，引用一旦被覆盖
        // （clearAgentPlayers 置 null、或某次重建），旧玩家就变成在场上继续跑、
        // 继续从核心领单位的孤儿 —— 看门狗看不见它，于是又建一个。
        // 实测结果就是每个队两个 [AI] alpha，各自带一个 gamma，
        // 看起来像「开局白送单位」。
        dedupeAgentPlayers();

        for (AIArena.Agent a : AIArena.agents) {
            if (a.admin) continue;
            Team t = a.team();
            if (t == null) continue;

            String name = "[AI] " + a.id;

            // 判定依据是**场上的名字**，不是我们记着的引用
            mindustry.gen.Player found = null;
            for (mindustry.gen.Player p : mindustry.gen.Groups.player) {
                if (p != null && name.equals(p.name) && p.isAdded()) { found = p; break; }
            }
            if (found != null) {
                if (a.player() != found) a.bindPlayer(found);   // 顺手修正引用
                continue;
            }

            if (spawnAgentPlayer(a, t, log) != null) created++;
        }
        return created;
    }

    /**
     * 同名 AI 玩家只保留一个，多余的移除（含它们手上的单位）。
     *
     * ⚠ 保留**队伍正确的那一个**，不能只留先遇到的。
     *
     * 实测：看门狗每 500ms 跑一次，它在 setup 之前就会先用配置队（100/101）
     * 建出 [AI] alpha。setup 之后 alpha 被绑到 sharded 并新建了正确的玩家，
     * 此时场上同时存在两个 [AI] alpha —— 一个在 team#100、一个在 sharded。
     * 如果按遍历顺序留第一个，就会把正确那个删掉，等于绑定白做，
     * 结果是「AI 挂在没有核心的队上，既没单位也没视野」。
     */
    private static void dedupeAgentPlayers() {
        java.util.Map<String, mindustry.gen.Player> keep = new java.util.HashMap<>();
        java.util.List<mindustry.gen.Player> dupes = new java.util.ArrayList<>();

        for (mindustry.gen.Player p : mindustry.gen.Groups.player) {
            if (p == null || p.name == null || !p.name.startsWith("[AI] ")) continue;

            mindustry.gen.Player prev = keep.get(p.name);
            if (prev == null) { keep.put(p.name, p); continue; }

            // 已经有同名了：谁更该留下？
            // 名字形如 "[AI] <agentId>"，用它反查 agent 当前的绑定队伍。
            String agentId = p.name.substring("[AI] ".length());
            AIArena.Agent a = null;
            for (AIArena.Agent cand : AIArena.agents) {
                if (cand.id.equals(agentId)) { a = cand; break; }
            }
            boolean pOk = a != null && a.team() != null && p.team() == a.team();
            boolean prevOk = a != null && a.team() != null && prev.team() == a.team();

            if (pOk && !prevOk) {
                dupes.add(prev);
                keep.put(p.name, p);
            } else {
                dupes.add(p);
            }
        }

        for (mindustry.gen.Player p : dupes) {
            try {
                if (p.unit() != null) p.clearUnit();
                p.remove();
            } catch (Throwable ignored) {}
        }

        if (!dupes.isEmpty()) {
            AIArena.log("deduped " + dupes.size() + " duplicate AI player(s)");
        }
    }

    /**
     * 为所有已绑定队伍的 agent 强制重建玩家（破坏性）。
     * 只在 setup 这种「重新开局」的场合用。
     */
    private static int rebindAgentPlayers(StringBuilder log) {
        clearAgentPlayers();
        return ensureAgentPlayers(log);
    }

    /**
     * 管理已连接的客户端玩家。仅 admin。
     *
     * 观战需要一个「不会干扰对局」的身份：
     *   - 加入 derelict 队（无核心，不会被 PlayerComp 自动重生）
     *   - 给 admin 权限，这样能看到全图、可以随时切队
     *
     * GET  /v1/{admin}/admin                          列出在线玩家
     * POST /v1/{admin}/admin?action=observe&player=<id>  把玩家设为观察者
     * POST /v1/{admin}/admin?action=admin&player=<id>    给玩家 admin
     */
    /**
     * 运行时诊断快照。仅 admin。
     *
     * 一次拉齐排查「看不到单位 / 切队跳回 / 建筑延迟出现」所需要的全部事实：
     *   - 每个观战者的**视角队伍**（服务端认定的），以及它和实际队伍的差异
     *   - 每个队伍的实体数，用来和客户端 Groups.unit/build 对照
     *   - 连接事件时间线 + 断开原因直方图（closed / timeout / error）
     *   - 快照路由计数，验证视角真的被路由了
     *
     * GET /v1/{admin}/diag
     */
    /**
     * 服务端每队的迷雾数据状态。
     *
     * 观战切到某些队伍整屏全黑，而 UI 层正常。客户端那边测出来
     * getDiscovered(team) 返回的是**长度 0 的 Bits**（不是 null）——
     * FogRenderer 对 null 是「不画迷雾」（世界可见），对全零位图是
     * 「全部未探索」（全黑）。所以要看清服务端这份数据是什么样。
     */
    private static String fogStateJson() {
        StringBuilder sb = new StringBuilder("[");
        boolean first = true;
        try {
            for (Team t : Team.all) {
                if (t == null) continue;
                var bits = Vars.fogControl.getDiscovered(t);
                if (bits == null) continue;
                int len = bits.length();
                int set = 0;
                for (int i = 0; i < len; i++) if (bits.get(i)) set++;
                if (!first) sb.append(',');
                first = false;
                sb.append(new Json.Obj()
                    .put("team", t.id).put("name", t.name)
                    .put("bits", len).put("discovered", set).toString());
            }
        } catch (Throwable e) {
            sb.append(new Json.Obj().put("error", String.valueOf(e)).toString());
        }
        return sb.append(']').toString();
    }

    private static void handleDiag(HttpExchange ex, AIArena.Agent agent) {
        if (!agent.admin) {
            respond(ex, 403, Json.error(1403, "diag requires an admin token"));
            return;
        }
        postToGame(ex, () -> {
            var r = Vars.state.rules;

            StringBuilder players = new StringBuilder("[");
            boolean pf = true;
            for (var pl : mindustry.gen.Groups.player) {
                if (!pf) players.append(',');
                pf = false;
                players.append(new Json.Obj()
                    .put("name", pl.name)
                    .put("id", pl.id)
                    .put("team", pl.team().id)
                    .put("teamName", pl.team().name)
                    .put("view", AIArena.viewTeamOf(pl))
                    .put("spectator", pl.spectator)
                    .put("observer", AIArena.observers.contains(pl.uuid()))
                    .put("hasUnit", pl.unit() != null)
                    .put("unitType", pl.unit() == null ? "" : pl.unit().type.name)
                    .put("connected", pl.con != null && pl.con.hasConnected)
                    .toString());
            }
            players.append(']');

            StringBuilder teams = new StringBuilder("[");
            boolean tf = true;
            for (var td : Vars.state.teams.present) {
                if (!tf) teams.append(',');
                tf = false;
                teams.append(new Json.Obj()
                    .put("id", td.team.id)
                    .put("name", td.team.name)
                    .put("units", td.units.size)
                    .put("builds", td.buildings.size)
                    .put("cores", td.cores.size)
                    .put("players", td.players.size)
                    .toString());
            }
            teams.append(']');

            return Json.ok(new Json.Obj()
                .put("tick", (int) Vars.state.tick)
                .put("state", Vars.state.getState().name())
                .put("paused", Vars.state.isPaused())
                .put("fog", r.fog)
                .put("staticFog", r.staticFog)
                .put("pvp", r.pvp)
                .put("worldUnits", mindustry.gen.Groups.unit.size())
                .put("worldBuilds", mindustry.gen.Groups.build.size())
                .put("worldPlayers", mindustry.gen.Groups.player.size())
                .put("teamBatchSends", Diag.teamBatchSends())
                .put("fullViewSends", Diag.fullViewSends())
                .put("spectatorRouted", Diag.spectatorRouted())
                // 规则快照。setup 会临时改其中几项（关保护圈、清禁用表、关 staticFog），
                // 不暴露出来就只能靠读代码确认它有没有还原。
                .putRaw("rules", new Json.Obj()
                    .put("enemyCoreBuildRadius", r.enemyCoreBuildRadius)
                    .put("blockWhitelist", r.blockWhitelist)
                    .put("bannedBlocks", r.bannedBlocks.size)
                    .put("editor", r.editor)
                    .put("fog", r.fog)
                    .put("staticFog", r.staticFog)
                    .put("infiniteResources", r.infiniteResources)
                    .put("buildCostMultiplier", r.buildCostMultiplier)
                    .put("buildSpeedMultiplier", r.buildSpeedMultiplier)
                    .toString())
                .putRaw("fogState", fogStateJson())
                .putRaw("players", players.toString())
                .putRaw("teams", teams.toString())
                .putRaw("disconnectReasons", Diag.reasonHistogramJson())
                .putRaw("connectionEvents", Diag.eventsJson())
                .toString());
        });
    }
    private static void handleAdmin(HttpExchange ex, AIArena.Agent agent) {
        if (!agent.admin) {
            respond(ex, 403, Json.error(1403, "player administration requires an admin token"));
            return;
        }
        Params p = Params.of(ex);
        String action = p.get("action", null);

        postToGame(ex, () -> {
            if (action == null) {
                StringBuilder arr = new StringBuilder("[");
                boolean first = true;
                for (var pl : mindustry.gen.Groups.player) {
                    if (!first) arr.append(',');
                    first = false;
                    arr.append(new Json.Obj()
                        .put("id", pl.id)
                        .put("name", pl.name)
                        .put("uuid", pl.uuid())
                        .put("usid", pl.usid())
                        .put("team", pl.team().id)
                        .put("teamName", pl.team().name)
                        .put("admin", pl.admin)
                        .put("dead", pl.dead())
                        // 观察者的单位会被每 tick 清掉，这里能直接看出清没清干净
                        .put("hasUnit", pl.unit() != null)
                        .put("unitType", pl.unit() == null ? "" : pl.unit().type.name)
                        .put("observer", AIArena.observers.contains(pl.uuid()))
                        .toString());
                }
                arr.append(']');
                return Json.ok(new Json.Obj()
                    .put("count", mindustry.gen.Groups.player.size())
                    .putRaw("players", arr.toString()).toString());
            }

            int pid = (int) p.getLong("player", -1);
            var pl = pid >= 0 ? mindustry.gen.Groups.player.getByID(pid) : null;
            if (pl == null) return Json.error(1002, "player not found: " + pid);

            // 玩家可能正好在这个 tick 断开，con 会变成 null。
            // 直接往下走会抛 NPE（"Cannot read field hasConnected because p.con is null"），
            // 而那个异常发生在引擎的 player 遍历里，会把整个服务器打挂。
            if (pl.con == null) {
                return Json.error(1005, "player " + pid + " has no active connection (disconnected?)");
            }

            try {
                switch (action) {
                    case "observe" -> {
                        // 观战者 = spectator 标志（永不生成单位）+ admin + 指定视角。
                        //
                        // 视角由队伍决定，而且是**每客户端**的：
                        //   队伍 = 真实队伍 → 引擎按那个队的视野同步实体，客户端画那个队的迷雾
                        //   队伍 = derelict  → NetServer 判定为全图，发全部实体，客户端不画迷雾
                        //
                        // 关键：**不动 state.rules.fog**。关掉全局迷雾会让 AI 也失去
                        // 视野约束 —— 那是把「谁能看见」这个每客户端的问题当成了全局开关。
                        int view = (int) p.getLong("view", AIArena.DEFAULT_VIEW);
                        if (view >= Team.all.length) {
                            return Json.error(1001, "view team id out of range: " + view);
                        }
                        AIArena.makeObserver(pl, view);

                        return Json.ok(new Json.Obj()
                            .put("message", "player " + pl.name + " is now a spectator"
                                            + " (no units ever, admin, view="
                                            + (view < 0 ? "all" : Team.get(view).name) + ")")
                            .put("team", pl.team().id)
                            .put("view", view)
                            .put("spectator", pl.spectator).toString());
                    }
                    case "unobserve" -> {
                        AIArena.clearObserver(pl);
                        return Json.ok(new Json.Obj()
                            .put("message", "player " + pl.name + " is no longer a spectator")
                            .put("spectator", pl.spectator).toString());
                    }
                    case "referee" -> {
                        // 把观战者切到全图裁判视角（只影响这一个客户端）。
                        int view = "false".equalsIgnoreCase(p.get("on", "true")) ? -2 : -1;
                        if (view == -2) {
                            // 关掉裁判模式 = 切回自己所在队伍的视角
                            int fallback = -1;
                            for (var td : Vars.state.teams.present) {
                                if (td.cores.size > 0) { fallback = td.team.id; break; }
                            }
                            AIArena.setViewTeam(pl, fallback);
                            return Json.ok(new Json.Obj()
                                .put("message", "referee mode off")
                                .put("view", fallback)
                                .put("team", pl.team().name).toString());
                        }
                        AIArena.setViewTeam(pl, -1);
                        return Json.ok(new Json.Obj()
                            .put("message", "referee mode on (full map, this client only)")
                            .put("view", -1)
                            .put("team", pl.team().name).toString());
                    }
                    case "team" -> {
                        int tid = (int) p.getLong("team", -1);
                        if (tid < 0 || tid >= Team.all.length) {
                            return Json.error(1001, "required: team=<id>");
                        }
                        Team t = Team.get(tid);

                        if (pl.spectator) {
                            // 观战者换视角：服务端换队 + 重发世界数据，
                            // 否则客户端还拿着旧队伍过滤过的实体（Tab 切队没反应就是这个原因）
                            AIArena.setViewTeam(pl, tid);
                        } else {
                            pl.team(t);
                            // 换队后必须清掉旧单位，否则视野还挂在旧队伍上
                            pl.clearUnit();
                        }
                        return Json.ok(new Json.Obj()
                            .put("message", "player " + pl.name + " -> team " + t.name
                                            + (pl.spectator ? " (view)" : ""))
                            .put("team", t.id).put("teamName", t.name)
                            .put("spectator", pl.spectator).toString());
                    }
                    case "admin" -> {
                        Vars.netServer.admins.adminPlayer(pl.getInfo().id, pl.usid());
                        pl.admin = true;
                        return Json.ok(new Json.Obj()
                            .put("message", "player " + pl.name + " granted admin").toString());
                    }
                    default -> {
                        return Json.error(1001, "unknown action: " + action);
                    }
                }
            } catch (Throwable t) {
                return Json.error(1500, "player admin action failed: " + t);
            }
        });
    }

    /**
     * 观战信息（DESIGN.md P5）。
     *
     * GET /v1/{agent}/observe
     *
     * 返回可观察的队伍列表与当前视角。任何 agent 都能调用，但能看哪些队取决于身份：
     *   - 普通 agent：只能看自己的队
     *   - admin（裁判）：可看任意队 + all（上帝视角）
     *
     * 观察者本身不需要在服务器上有队伍 —— 观战走 HTTP，不占实体同步通道。
     * 这规避了 DESIGN.md P5 里记的风险：让裁判走引擎实体同步会与 hiddenIds
     * 机制打架（先删后建导致闪烁）。
     */
    private static void handleObserve(HttpExchange ex, AIArena.Agent agent) {
        Snapshot.State s = Snapshot.get();
        Params p = Params.of(ex);
        int viewId = resolveView(agent, p);

        StringBuilder teams = new StringBuilder("[");
        boolean first = true;
        for (Snapshot.TeamInfo t : s.teams) {
            if (t.cores == 0 && !t.alive) continue;      // 空队不列
            if (!first) teams.append(',');
            first = false;

            boolean allowed = agent.admin || t.id == (agent.team() == null ? -1 : agent.team().id);
            teams.append(new Json.Obj()
                .put("id", t.id).put("name", t.name)
                .put("cores", t.cores).put("alive", t.alive).put("isAI", t.ai)
                .put("viewable", allowed)
                .toString());
        }
        teams.append(']');

        respond(ex, 200, Json.ok(new Json.Obj()
            .put("agent", agent.id)
            .put("isReferee", agent.admin)
            .put("currentView", viewId < 0 ? "all" : Team.get(viewId).name)
            .put("canSeeAll", agent.admin)
            .putRaw("teams", teams.toString())
            .putRaw("hint", Json.str(agent.admin
                ? "append &view=all for god view, or &view=<teamId> for a specific team"
                : "append &view=own (default). Admin token required for view=all"))
            .toString()));
    }

    /**
     * 管理员专用：初始化一局对战。
     *
     * GET /v1/{admin}/setup?map=<name>&fog=true&units=true
     *
     * 步骤（顺序不可颠倒，每一步都是下一步的前提）：
     *   1. loadMap —— 只加载地形
     *   2. 显式设置 state.rules —— loadMap 会用地图自身规则覆盖传入对象
     *   3. state.set(playing) —— 只有 playing 状态 tick 才会前进，Time.run 才会触发
     *   4. 为每个非 admin agent 找空地放核心
     *   5. 为每个 agent 生成一个建造单位（否则无法建造）
     */
    /** 单位列表。只读快照 + 视野过滤。 */
    private static void handleUnits(HttpExchange ex, AIArena.Agent agent) {
        Snapshot.State s = Snapshot.get();
        int viewId = resolveView(agent, Params.of(ex));
        respond(ex, 200, Json.ok(new Json.Obj()
            .put("agent", agent.id).put("team", viewId).put("tick", s.tick)
            .putRaw("units", visibleUnits(s, viewId, viewId < 0))
            .toString()));
    }

    /** 建筑列表。只读快照 + 视野过滤。 */
    private static void handleBuildings(HttpExchange ex, AIArena.Agent agent) {
        Snapshot.State s = Snapshot.get();
        int viewId = resolveView(agent, Params.of(ex));
        respond(ex, 200, Json.ok(new Json.Obj()
            .put("agent", agent.id).put("team", viewId).put("tick", s.tick)
            .putRaw("buildings", visibleBuildings(s, viewId, viewId < 0))
            .toString()));
    }

    /**
     * 可用内容清单。
     *
     * 这是「AI 能知道什么」的一部分 —— 玩家打开建造菜单能看到全部可建方块，
     * 所以 AI 也应该能拿到同一份清单，包括每种方块的成本与尺寸。
     */
    /**
     * 单位工厂的可选产线，序列化成 JSON 数组；非工厂方块返回空数组。
     *
     * 有了它，AI 才能从 /content 自己发现「哪些方块能造兵、造什么、要什么料、要多久」，
     * 而不是把 air-factory + flare 这种知识硬编码进脚本 —— 换地图或换版本就失效。
     */
    private static String factoryPlansJson(Block b) {
        StringBuilder sb = new StringBuilder("[");
        if (b instanceof mindustry.world.blocks.units.UnitFactory uf) {
            boolean first = true;
            for (var plan : uf.plans) {
                if (!first) sb.append(',');
                first = false;

                StringBuilder req = new StringBuilder("{");
                boolean rf = true;
                for (var stack : plan.requirements) {
                    if (!rf) req.append(',');
                    rf = false;
                    req.append(Json.str(stack.item.name)).append(':').append(stack.amount);
                }
                req.append('}');

                sb.append(new Json.Obj()
                    .put("unit", plan.unit.name)
                    .put("timeTicks", (int) plan.time)
                    .put("timeSeconds", plan.time / 60f)
                    .put("flying", plan.unit.flying)
                    .put("health", plan.unit.health)
                    .putRaw("requirements", req.toString())
                    .toString());
            }
        }
        return sb.append(']').toString();
    }
    private static void handleContent(HttpExchange ex, AIArena.Agent agent) {
        postToGame(ex, () -> {
            StringBuilder blocks = new StringBuilder("[");
            boolean bf = true;
            for (Block b : Vars.content.blocks()) {
                if (b.isHidden() || !b.isPlaceable()) continue;
                if (!bf) blocks.append(',');
                bf = false;

                StringBuilder req = new StringBuilder("{");
                boolean rf = true;
                if (b.requirements != null) {
                    for (var stack : b.requirements) {
                        if (!rf) req.append(',');
                        rf = false;
                        req.append(Json.str(stack.item.name)).append(':').append(stack.amount);
                    }
                }
                req.append('}');

                blocks.append(new Json.Obj()
                    .put("name", b.name)
                    .put("size", b.size)
                    .put("health", b.health)
                    .put("category", b.category == null ? "" : b.category.name())
                    .put("hasPower", b.hasPower)
                    .putRaw("cost", req.toString())
                    .putRaw("plans", factoryPlansJson(b))
                    .toString());
            }
            blocks.append(']');

            StringBuilder items = new StringBuilder("[");
            boolean itf = true;
            for (mindustry.type.Item it : Vars.content.items()) {
                if (it.isHidden()) continue;
                if (!itf) items.append(',');
                itf = false;
                items.append(new Json.Obj()
                    .put("name", it.name)
                    .put("color", it.color.toString())
                    .put("hardness", it.hardness)
                    .put("flammability", it.flammability)
                    .toString());
            }
            items.append(']');

            StringBuilder cmds = new StringBuilder("[");
            boolean cf = true;
            for (String c : Commander.commandNames()) {
                if (!cf) cmds.append(',');
                cf = false;
                cmds.append(Json.str(c));
            }
            cmds.append(']');

            StringBuilder stances = new StringBuilder("[");
            boolean sf = true;
            for (String c : Commander.stanceNames()) {
                if (!sf) stances.append(',');
                sf = false;
                stances.append(Json.str(c));
            }
            stances.append(']');

            // 单位目录 —— 玩家能在地图上的敌方单位看到类型，也能从核心生产列表看到己方单位
            StringBuilder units = new StringBuilder("[");
            boolean uf = true;
            for (mindustry.type.UnitType ut : Vars.content.units()) {
                if (ut.isHidden()) continue;
                if (!uf) units.append(',');
                uf = false;
                units.append(new Json.Obj()
                    .put("name", ut.name)
                    .put("health", ut.health)
                    .put("flying", ut.flying)
                    .put("buildSpeed", ut.buildSpeed)
                    .put("fogRadius", ut.fogRadius)
                    .put("speed", ut.speed)
                    .put("hitSize", ut.hitSize)
                    .put("itemCapacity", ut.itemCapacity)
                    .toString());
            }
            units.append(']');

            StringBuilder liquids = new StringBuilder("[");
            boolean lf = true;
            for (mindustry.type.Liquid lq : Vars.content.liquids()) {
                if (lq.isHidden()) continue;
                if (!lf) liquids.append(',');
                lf = false;
                liquids.append(new Json.Obj()
                    .put("name", lq.name)
                    .put("color", lq.color.toString())
                    .put("flammability", lq.flammability)
                    .put("temperature", lq.temperature)
                    .toString());
            }
            liquids.append(']');

            return Json.ok(new Json.Obj()
                .put("agent", agent.id)
                .putRaw("blocks", blocks.toString())
                .putRaw("items", items.toString())
                .putRaw("units", units.toString())
                .putRaw("liquids", liquids.toString())
                .putRaw("unitCommands", cmds.toString())
                .putRaw("unitStances", stances.toString())
                .toString());
        });
    }

    /**
     * 核心数据情报（DESIGN.md 6.2）。
     *
     * 己方核心全知；敌方核心需要连续可见 600 tick 才确认，之后每次达成阈值追加一条
     * 快照并永久保留 —— 两次读数的差额直接给出对方在此期间的经济增长。
     */
    private static void handleIntel(HttpExchange ex, AIArena.Agent agent) {
        Snapshot.State s = Snapshot.get();
        Team team = agent.team();
        if (team == null) { respond(ex, 403, Json.error(1403, "agent has no team")); return; }

        StringBuilder cores = new StringBuilder("[");
        boolean first = true;

        for (Snapshot.TeamInfo t : s.teams) {
            if (t.id == team.id) continue;          // 己方核心走 /state，不走确认流程

            if (!first) cores.append(',');
            first = false;

            Intel.State st = Intel.get(team.id, t.id);
            Json.Obj o = new Json.Obj().put("team", t.name).put("teamId", t.id);

            if (st == null) {
                o.put("state", "unknown");
            } else if (st.confirmed) {
                o.put("state", "confirmed").put("confirmedAt", st.confirmedAt);
                StringBuilder snaps = new StringBuilder("[");
                boolean snf = true;
                for (Intel.Snap sn : st.snapshots) {
                    if (!snf) snaps.append(',');
                    snf = false;
                    StringBuilder its = new StringBuilder("{");
                    for (int i = 0; i < sn.itemNames.length; i++) {
                        if (i > 0) its.append(',');
                        its.append(Json.str(sn.itemNames[i])).append(':').append(sn.amounts[i]);
                    }
                    its.append('}');
                    snaps.append(new Json.Obj()
                        .put("tick", sn.tick)
                        .putRaw("items", its.toString())
                        .put("total", sn.total).toString());
                }
                snaps.append(']');
                o.putRaw("snapshots", snaps.toString());
            } else if (st.visibleTicks > 0) {
                o.put("state", "scouting")
                 .put("progress", st.progress())
                 .put("visibleTicks", st.visibleTicks)
                 .put("lastSeenTick", st.lastSeenTick);
            } else {
                o.put("state", "unknown");
            }
            cores.append(o.toString());
        }
        cores.append(']');

        respond(ex, 200, Json.ok(new Json.Obj()
            .put("agent", agent.id).put("team", team.name).put("tick", s.tick)
            .put("confirmTicks", Intel.CONFIRM_TICKS)
            .put("toleranceTicks", Intel.CLEAR_TOLERANCE_TICKS)
            .putRaw("cores", cores.toString())
            .toString()));
    }

    /**
     * 指挥操作。
     *
     * POST /v1/{agent}/command?action=<op>&units=1,2,3[&x=&y=&target=&cmd=&stance=&enable=&buildings=]
     *
     * action:
     *   move            单位前往 (x,y)
     *   attackUnit      单位攻击 target 单位 id
     *   assistBuilding  单位协助 (x,y) 处的建筑
     *   setCommand      设置指令，cmd=move|repair|rebuild|assist|mine|...
     *   setStance       设置姿态，stance=stop|holdFire|pursueTarget|patrol|...&enable=true
     *   commandBuilding 指挥建筑攻击 (x,y)
     *
     * 引擎对指挥本身没有距离检查，所以单位与目标都必须对己方可见 ——
     * 这是 DESIGN.md 4.6 里唯一必须自行实现的对等约束。
     */
    /** 哪些 /command action 必须带 units。 */
    private static boolean unitsRequired(String op) {
        return switch (op) {
            case "move", "attackUnit", "assistBuilding", "setCommand", "setStance" -> true;
            default -> false;
        };
    }

    private static void handleCommand(HttpExchange ex, AIArena.Agent agent) {
        Params p = Params.of(ex);
        String op = p.get("action", null);
        if (op == null) {
            respond(ex, 400, Json.error(1001, "required: action"));
            return;
        }
        Team team = agent.team();
        if (team == null) { respond(ex, 403, Json.error(1403, "agent has no team")); return; }

        int[] unitIds = p.getIntArray("units");
        int[] buildingIds = p.getIntArray("buildings");

        // 需要单位的 action：units 为空时给明确提示。
        // 不能让它落到 Commander 去报「no valid units for <team>」—— 那读起来
        // 像是「你给的 id 不属于这队」，而真实原因往往只是参数名写成了单数
        // unit=，或者忘了传。
        if (unitsRequired(op) && (unitIds == null || unitIds.length == 0)) {
            respond(ex, 400, Json.error(1001,
                "required: units=<id>[,<id>...] — 复数参数、逗号分隔；"
                + "本 action 需要至少一个己方单位"));
            return;
        }
        float x = p.getFloat("x", 0f);
        float y = p.getFloat("y", 0f);
        int target = p.getInt("target", -1);
        boolean queue = p.getBool("queue", false);

        postToGame(ex, () -> {
            Actor.Result r = switch (op) {
                case "move" -> Commander.command(team, unitIds, Commander.TargetKind.position, x, y, -1, queue);
                case "attackUnit" -> Commander.command(team, unitIds, Commander.TargetKind.unit, x, y, target, queue);
                case "assistBuilding" -> Commander.command(team, unitIds, Commander.TargetKind.building, x, y, -1, queue);
                case "setCommand" -> Commander.setCommand(team, unitIds, p.get("cmd", null));
                case "setStance" -> Commander.setStance(team, unitIds, p.get("stance", null), p.getBool("enable", true));
                case "commandBuilding" -> Commander.commandBuilding(team, buildingIds, x, y);
                case "requestItem" -> Commander.requestItem(team, (int) x, (int) y, p.get("item", null), p.getInt("amount", 1));
                case "transferInventory" -> Commander.transferInventory(team, (int) x, (int) y);
                default -> Actor.Result.err(1001, "unknown action: " + op);
            };
            return r.ok ? Json.ok(new Json.Obj().put("message", r.message).toString())
                        : Json.error(r.code, r.message);
        });
    }

    /**
     * 进入 / 退出单位，以及被控单位的移动与开火。
     *
     * POST /v1/{agent}/control?op=enter&unit=42
     * POST /v1/{agent}/control?op=release
     * POST /v1/{agent}/control?op=move&x=&y=
     * POST /v1/{agent}/control?op=fire&x=&y=&on=true
     *
     * 对应玩家按 Ctrl 接管单位的操作。引擎在三条接管路径上都要求
     * unit.team == player.team()（InputHandler.java:783 / :1006 / :2149），
     * 影子 Player 的队伍与 AI 一致，因此天然满足。
     */
    private static void handleControl(HttpExchange ex, AIArena.Agent agent) {
        Params p = Params.of(ex);
        String op = p.get("op", "enter");
        Team team = agent.team();
        if (team == null) { respond(ex, 403, Json.error(1403, "agent has no team")); return; }

        int unitId = p.getInt("unit", -1);
        float x = p.getFloat("x", 0f);
        float y = p.getFloat("y", 0f);

        postToGame(ex, () -> {
            Actor.Result r = switch (op) {
                case "enter"   -> Commander.control(team, unitId, true);
                case "release" -> Commander.control(team, unitId, false);
                case "move"    -> Commander.moveControl(team, x, y);
                case "order"   -> Commander.order(team, p.getInt("unit", -1), x, y);
                case "stopmove"-> Commander.stopOrder(team, p.getInt("unit", -1));
                case "orders"  -> Actor.Result.ok(Commander.ordersJson());
                case "warp"    -> Commander.warp(team, p.getInt("unit", -1), x, y);
                case "pos"     -> Commander.livePos(team, p.getInt("unit", -1));
                case "probe"   -> Actor.Result.ok(Commander.probeJson());
                case "ticks"   -> Actor.Result.ok("{\"tickMoveOrders\":" + Commander.tickCount()
                                     + ",\"applied\":" + Commander.applyCount() + "}");
                case "fire"    -> Commander.fireControl(team, x, y, p.getBool("on", true));
                default        -> Actor.Result.err(1001, "unknown op: " + op);
            };
            return r.ok ? Json.ok(new Json.Obj().put("message", r.message).toString())
                        : Json.error(r.code, r.message);
        });
    }

    /**
     * 事件流轮询（DESIGN.md 6.3）。
     *
     * GET /v1/{agent}/events?since=<seq>&limit=<n>
     *
     * 响应里的 nextSince 用于下次轮询。首次调用传 since=0 即可从缓冲区起点开始。
     * 若游标已过期（事件被环形缓冲淘汰），返回 code 1006 cursor_expired，
     * 调用方应重置 since=0 重新同步。
     *
     * 视野约束：事件按观察方过滤 —— 玩家只能看到自己视野内发生的事，AI 也一样。
     * 己方队伍的事件无条件可见。
     */
    private static void handleEvents(HttpExchange ex, AIArena.Agent agent) {
        Params p = Params.of(ex);
        long since = p.getLong("since", 0L);
        int limit = Math.min(Math.max(p.getInt("limit", 256), 1), 1024);

        Team team = agent.team();
        Params vp = Params.of(ex);
        int viewId = resolveView(agent, vp);
        Team viewer = viewId < 0 ? null : Team.get(viewId);

        // 游标过期：请求的事件已被环形缓冲淘汰，让调用方重置重新同步
        if (EventLog.cursorExpired(since)) {
            respond(ex, 410, Json.error(1006,
                "cursor expired: events before seq " + since + " have been discarded; resync with since=0"));
            return;
        }

        var evs = EventLog.since(since, limit, viewer);

        StringBuilder arr = new StringBuilder("[");
        for (int i = 0; i < evs.size; i++) {
            if (i > 0) arr.append(',');
            arr.append(evs.get(i).toJson());
        }
        arr.append(']');

        respond(ex, 200, Json.ok(new Json.Obj()
            .put("agent", agent.id)
            .put("tick", Snapshot.get().tick)
            .put("since", since)
            .put("nextSince", EventLog.lastSeq())
            .put("count", evs.size)
            .put("buffered", EventLog.size())
            .putRaw("events", arr.toString())
            .toString()));
    }



    /**
     * 蓝图导入 / 导出。
     *
     *   GET  /v1/{agent}/blueprint?x=&y=&w=&h=        导出该矩形区域
     *   POST /v1/{agent}/blueprint?x=&y=&data=<base64> 把蓝图放在 (x,y)
     *
     * 格式是我们自己的显式 JSON（见本文件顶部说明与 API.md），
     * **不是 Mindustry 的 .msch 二进制** —— 后者在没有参考实现的情况下
     * 照猜写解析器，产出的是「看着像对、其实错位」的东西。
     *
     * 为什么值得做：这张图每局重新随机，布局本来没法跨局复用。
     * 有了它，一局调好的产线能存下来、下一局搬到新地形上。
     */
    private static void handleBlueprint(HttpExchange ex, AIArena.Agent agent) {
        Params p = Params.of(ex);
        Team team = agent.team();
        if (team == null) { respond(ex, 403, Json.error(1403, "agent has no team")); return; }

        String data = p.get("data", null);

        // ── 导出 ──────────────────────────────────────────────────────
        if (data == null) {
            int x = p.getInt("x", Integer.MIN_VALUE);
            int y = p.getInt("y", Integer.MIN_VALUE);
            int w = p.getInt("w", 0), h = p.getInt("h", 0);
            if (x == Integer.MIN_VALUE || y == Integer.MIN_VALUE) {
                respond(ex, 400, Json.error(1001, "required: x, y, w, h (for export)"));
                return;
            }
            if (w <= 0 || h <= 0 || w * h > MAX_MAP_TILES) {
                respond(ex, 400, Json.error(1004, "w*h must be in 1.." + MAX_MAP_TILES));
                return;
            }
            postToGame(ex, () -> {
                StringBuilder blocks = new StringBuilder("[");
                int n = 0;
                for (int dy = 0; dy < h; dy++) {
                    for (int dx = 0; dx < w; dx++) {
                        var tile = Vars.world.tile(x + dx, y + dy);
                        if (tile == null || tile.build == null) continue;
                        // 多格方块只在锚点记一次，否则导入时会重复放
                        if (tile.build.tileX() != x + dx || tile.build.tileY() != y + dy) continue;
                        if (n > 0) blocks.append(',');
                        blocks.append(new Json.Obj()
                            .put("dx", dx).put("dy", dy)
                            .put("block", tile.build.block.name)
                            .put("rot", tile.build.rotation)
                            .toString());
                        n++;
                    }
                }
                blocks.append(']');
                String plain = new Json.Obj()
                    .put("v", 1).put("w", w).put("h", h).put("count", n)
                    .putRaw("blocks", blocks.toString()).toString();
                String b64 = java.util.Base64.getEncoder()
                    .encodeToString(plain.getBytes(java.nio.charset.StandardCharsets.UTF_8));
                return Json.ok(new Json.Obj()
                    .put("x", x).put("y", y).put("w", w).put("h", h)
                    .put("count", n).put("data", b64)
                    .put("format", "ai-arena-blueprint-json/1")
                    .put("message", "exported " + n + " block(s)").toString());
            });
            return;
        }

        // ── 导入 ──────────────────────────────────────────────────────
        int x = p.getInt("x", Integer.MIN_VALUE);
        int y = p.getInt("y", Integer.MIN_VALUE);
        if (x == Integer.MIN_VALUE || y == Integer.MIN_VALUE) {
            respond(ex, 400, Json.error(1001, "required: x, y (top-left anchor for import)"));
            return;
        }
        postToGame(ex, () -> {
            String plain;
            try {
                plain = new String(java.util.Base64.getDecoder().decode(data.trim()),
                                   java.nio.charset.StandardCharsets.UTF_8);
            } catch (IllegalArgumentException bad) {
                return Json.error(1001, "data is not valid base64");
            }
            arc.util.serialization.Jval root;
            try {
                root = arc.util.serialization.Jval.read(plain);
            } catch (Throwable t) {
                return Json.error(1001, "blueprint is not valid JSON: " + t);
            }
            var arr = root.get("blocks");
            if (arr == null || !arr.isArray()) {
                return Json.error(1001, "blueprint has no blocks[] array");
            }

            int ok = 0, skipped = 0, firstBad = -1;
            StringBuilder reasons = new StringBuilder();
            int idx = 0;
            for (arc.util.serialization.Jval b : arr.asArray()) {
                String block = b.getString("block", null);
                if (block == null) { skipped++; idx++; continue; }
                int dx = b.getInt("dx", 0), dy = b.getInt("dy", 0);
                int rot = b.getInt("rot", 0);
                Actor.Result r = Actor.place(team, x + dx, y + dy, block, rot, null);
                if (r.ok) {
                    ok++;
                } else {
                    skipped++;
                    if (firstBad < 0) firstBad = (x + dx) * 100000 + (y + dy);
                    if (reasons.length() < 240)
                        reasons.append('(').append(x + dx).append(',').append(y + dy)
                               .append(")=").append(r.code).append(' ');
                }
                idx++;
            }
            Json.Obj body = new Json.Obj()
                .put("placed", ok).put("skipped", skipped).put("total", idx)
                .put("format", "ai-arena-blueprint-json/1");
            if (firstBad >= 0) body.put("firstFailureTile", firstBad);
            if (reasons.length() > 0) body.put("failureCodes", reasons.toString());
            body.put("message", "blueprint: placed " + ok + "/" + idx
                + (skipped > 0 ? ", skipped " + skipped + " (see failureCodes)" : ""));
            return ok > 0 ? Json.ok(body.toString())
                          : Json.error(1005, "blueprint placed nothing: " + body);
        });
    }

    /** 同时在流的 SSE 连接数上限。每个 handler 占一个 HTTP 线程。 */
    private static final java.util.concurrent.atomic.AtomicInteger liveStreams =
        new java.util.concurrent.atomic.AtomicInteger();
    private static final int MAX_LIVE_STREAMS = 8;

    /**
     * SSE 事件推送（DESIGN.md 41/731/853）。
     *
     * GET /v1/{agent}/stream?since=<seq>&limit=<n>&seconds=<s>
     *
     * 与 /events 轮询**共用同一套游标语义** —— since / nextSince /
     * cursor_expired(1006) 完全一致，所以客户端从轮询切过来不必改状态机。
     *
     * 事件的 JSON 直接复用 EventLog.Ev.toJson()，不另写一份序列化 ——
     * 两份序列化迟早会漂移，而 SSE 与轮询说的必须是同一件事。
     */
    private static void handleStream(HttpExchange ex, AIArena.Agent agent) {
        Params p = Params.of(ex);
        long since = p.getLong("since", 0L);
        int limit = Math.min(Math.max(p.getInt("limit", 256), 1), 1024);
        double seconds = Math.max(1.0, Math.min(p.getFloat("seconds", 60f), 600f));

        int live = liveStreams.incrementAndGet();
        if (live > MAX_LIVE_STREAMS) {
            liveStreams.decrementAndGet();
            respond(ex, 503, Json.error(1007, "too many live streams (" + MAX_LIVE_STREAMS
                + " max); use /events polling instead"));
            return;
        }

        Team team = agent.team();
        Params vp = Params.of(ex);
        int viewId = resolveView(agent, vp);
        Team viewer = viewId < 0 ? null : Team.get(viewId);

        java.io.OutputStream os = null;
        try {
            ex.getResponseHeaders().set("Content-Type", "text/event-stream; charset=utf-8");
            ex.getResponseHeaders().set("Cache-Control", "no-cache");
            ex.sendResponseHeaders(200, 0);          // 0 = chunked，长度未知
            os = ex.getResponseBody();

            send(os, ":ok\n\n");
            send(os, "event: hello\ndata: {\"since\":" + since
                + ",\"agent\":" + Json.str(agent.id) + "}\n\n");

            long deadline = System.currentTimeMillis() + (long) (seconds * 1000);
            long lastBeat = System.currentTimeMillis();

            while (System.currentTimeMillis() < deadline) {
                // 游标过期：和轮询同样回 1006，并提示 resync —— 只是走流内事件
                if (EventLog.cursorExpired(since)) {
                    send(os, "event: error\ndata: {\"code\":1006,\"error\":"
                        + Json.str("cursor expired: events before seq " + since
                            + " have been discarded; resync with since=0") + "}\n\n");
                    since = 0;
                }

                var evs = EventLog.since(since, limit, viewer);
                if (evs.size > 0) {
                    for (int i = 0; i < evs.size; i++) {
                        var ev = evs.get(i);
                        send(os, "event: ev\ndata: " + ev.toJson() + "\n\n");
                        if (ev.seq > since) since = ev.seq;
                    }
                    send(os, "event: cursor\ndata: {\"nextSince\":" + since
                        + ",\"buffered\":" + EventLog.size() + "}\n\n");
                    lastBeat = System.currentTimeMillis();
                } else if (System.currentTimeMillis() - lastBeat > 10_000) {
                    send(os, ":hb\n\n");             // 保活，不占序号
                    lastBeat = System.currentTimeMillis();
                }
                Thread.sleep(120);                   // 采样间隔，不是「等待」
            }
            send(os, "event: end\ndata: {\"reason\":\"lifetime reached\","
                + "\"nextSince\":" + since + "}\n\n");
        } catch (Throwable t) {
            // 客户端断开是常态，不记日志
        } finally {
            liveStreams.decrementAndGet();
            try { if (os != null) os.close(); } catch (Throwable ignored) { }
            try { ex.close(); } catch (Throwable ignored) { }
        }
    }

    private static void send(java.io.OutputStream os, String s) throws java.io.IOException {
        os.write(s.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        os.flush();
    }

    /**
     * 列出所有地图的真实属性。
     *
     * PvP 地图的判定标准是 map.teams.size > 1（Gamemode.pvp 的 map 判定条件），
     * 以及 Maps.pvp() 里的 tag 判定。spawns 是「玩家出生点」，与核心无关。
     */    private static void handleMaps(HttpExchange ex, AIArena.Agent agent) {
        postToGame(ex, () -> {
            StringBuilder arr = new StringBuilder("[");
            boolean first = true;
            int pvpCapable = 0;

            for (mindustry.maps.Map m : Vars.maps.all()) {
                if (m.teams.size > 1) pvpCapable++;

                if (!first) arr.append(',');
                first = false;

                // 注意：不能直接用 m.teams.iterator()。
                // Map.teams 是引擎维护的 IntSet，地图解析/重载过程中会被改写，
                // 并发读会抛 NoSuchElementException（实测在压力测试中出现）。
                // 这里先快照成数组，再做后续处理，并对异常兜底。
                int[] teamIds;
                try {
                    // IntSet 没有 toArray()，只有 each(Intc) 与 iterator()。
                    // 两者在集合被并发改写时都会抛异常，所以这里整体兜底。
                    java.util.List<Integer> tmp = new java.util.ArrayList<>();
                    m.teams.each(tmp::add);
                    teamIds = new int[tmp.size()];
                    for (int ti = 0; ti < teamIds.length; ti++) teamIds[ti] = tmp.get(ti);
                } catch (Throwable t) {
                    teamIds = new int[0];
                }

                StringBuilder teamList = new StringBuilder("[");
                boolean tf = true;
                for (int id : teamIds) {
                    if (!tf) teamList.append(',');
                    tf = false;
                    Team t = Team.get(id);
                    teamList.append(new Json.Obj()
                        .put("id", id).put("name", t == null ? "?" : t.name).toString());
                }
                teamList.append(']');

                arr.append(new Json.Obj()
                    .put("name", m.name())
                    .put("w", m.width).put("h", m.height)
                    .put("teams", teamIds.length)
                    .putRaw("teamList", teamList.toString())
                    .put("spawns", m.spawns)
                    .put("custom", m.custom)
                    .put("pvpTag", m.tags.get("pvp", ""))
                    .put("author", m.author())
                    .toString());
            }
            arr.append(']');

            return Json.ok(new Json.Obj()
                .put("total", Vars.maps.all().size)
                .put("pvpCapable", pvpCapable)
                .putRaw("maps", arr.toString())
                .toString());
        });
    }

    private static void handleSetup(HttpExchange ex, AIArena.Agent agent) {
        if (!agent.admin) {
            respond(ex, 403, Json.error(1403, "setup requires an admin token"));
            return;
        }
        Params p = Params.of(ex);
        String mapName = p.get("map", null);
        boolean wantFog = !"false".equalsIgnoreCase(p.get("fog", "true"));
        boolean wantUnits = !"false".equalsIgnoreCase(p.get("units", "true"));

        // setup 必须跨帧执行。
        //
        // 原因：state.set(playing) 之后，队伍数据（含地图自带核心的归属）并不是
        // 同一帧内就填充好的 —— 实测在 post 里立刻读 state.teams.present 得到的是
        // 上一局甚至空的残留数据。因此第一阶段在主线程 post 里完成地图与规则设置，
        // 第二阶段用 Time.run 延后一帧再读队伍、分配核心、生成单位。
        final java.util.concurrent.CompletableFuture<String> future = new java.util.concurrent.CompletableFuture<>();

        Core.app.post(() -> {
          try {
            StringBuilder log = new StringBuilder();

            // ---- 1. 选地图并加载 ----
            mindustry.maps.Map chosen = null;
            if (mapName != null) {
                for (mindustry.maps.Map m : Vars.maps.all()) {
                    if (m.name().equalsIgnoreCase(mapName)) { chosen = m; break; }
                }
                if (chosen == null) { future.complete(Json.error(1002, "map not found: " + mapName)); return; }
            } else {
                for (mindustry.maps.Map m : Vars.maps.all()) { chosen = m; break; }
            }
            if (chosen == null) { future.complete(Json.error(1002, "no maps available")); return; }

            // 换图前必须回到菜单状态 —— 引擎不允许在 playing 状态下直接 loadMap。
            if (Vars.state.isPlaying()) {
                Vars.state.set(mindustry.core.GameState.State.menu);
            }

            // 影子 Player 与情报状态都属于上一局，一并清空
            Shadow.clear();
            Intel.clearAll();

            // 清理所有队伍的残留数据。
            //
            // loadMap 会重建世界，但 TeamData 的 cores / buildings 列表仍持有上一张
            // 地图的 Building 引用。不清理的话，换图后 /state 会报告上一张地图的
            // 坐标 —— 实测在 150 宽的 Glacier 上报出了 289 这样的越界坐标。
            // TeamData 没有 reset()，直接清空这两个列表。
            for (Team t : Team.all) {
                if (t == null) continue;
                var td = t.data();
                if (td == null) continue;
                td.cores.clear();
                td.buildings.clear();
            }

            Vars.world.loadMap(chosen, new mindustry.game.Rules());
            log.append("map=").append(chosen.name())
               .append("(").append(Vars.world.width()).append("x").append(Vars.world.height()).append("); ");

            // 判断是否为官方 PvP 图（Maps.pvpMaps = veins/glacier/passage）
            boolean officialPvp = chosen.file != null
                && !chosen.custom
                && java.util.Arrays.asList("veins", "glacier", "passage")
                       .contains(chosen.file.nameWithoutExtension());

            // ---- 2. 显式设置规则 ----
            var r = Vars.state.rules;
            r.pvp = true;
            r.fog = wantFog;
            r.staticFog = true;
            r.canGameOver = false;
            r.waves = false;
            r.attackMode = false;
            r.infiniteResources = false;
            r.editor = false;
            r.cleanupDeadTeams = true;
            // polygonCoreProtection 会用 enemyCoreBuildRadius(400 单位 ≈ 50 格) 在敌方核心
            // 周围圈出禁建区。初始放置核心时这会挡住所有候选点（小地图上全图都在圈内），
            // 因此保持关闭。PvP 的真正防线由核心自身的射程与单位承担。
            r.polygonCoreProtection = false;
            r.enemyCoreBuildRadius = 0f;
            // 资源和建造都不免费 —— 这是竞技场的基本前提。
            //
            // 早期为了打通链路把这里设成 true，结果整套经济被抹掉：建造不要材料、
            // 工厂不要物料，「谁先攒出产能」这个维度直接消失，对局退化成两个脚本对撞。
            // 现在必须靠真实产能：挖矿 → 矿机/传送带 → 工厂 → 出兵。
            //
            // 核心的初始库存来自地图定义，够放下第一批建筑；不够时可以让核心单位
            // 手动挖矿（原版 MinerComp 路径，见 /mine），挖到的矿在 mineTransferRange
            // 内会直接进核心。
            r.infiniteResources = false;
            r.buildCostMultiplier = 1f;
            r.buildSpeedMultiplier = 1f;

            // 地图 tags 可能带进来「方块白名单/黑名单」设置。
            // Rules.isBanned 的实现是 blockWhitelist != bannedBlocks.contains(block)，
            // 若 blockWhitelist=true 而 bannedBlocks 为空，则每个方块都被判为 banned，
            // 导致 isPlaceable() 为 false、validPlace 一律失败。这里显式重置。
            r.blockWhitelist = false;
            r.bannedBlocks.clear();
            r.unitWhitelist = false;
            r.bannedUnits.clear();

            log.append("rules pvp=").append(r.pvp).append(" fog=").append(r.fog)
               .append(" coreProtect=").append(r.polygonCoreProtection)
               .append(" blockWhitelist=").append(r.blockWhitelist)
               .append(" bannedBlocks=").append(r.bannedBlocks.size)
               .append(" env=").append(r.env).append("; ");

            // ---- 3. 进入 playing ----
            Vars.state.set(mindustry.core.GameState.State.playing);
            log.append("playing=").append(Vars.state.isPlaying())
               .append(", stateMap=").append(Vars.state.map == null ? "null" : Vars.state.map.name())
               .append("; ");

            // ---- 阶段 2 起点：延后一帧，等队伍数据填充完成 ----
            final mindustry.maps.Map fChosen = chosen;
            final boolean fOfficialPvp = officialPvp;
            final StringBuilder fLog = log;

            final int[] attempt = {0};
            final Runnable[] phase2 = new Runnable[1];
            phase2[0] = () -> {
              try {
                StringBuilder lg = fLog;

                // 队伍数据（含核心归属）只在进入 playing 之后、且通常要下一帧才填充，
                // 因此地图自带核心的检测必须放在这里。
                java.util.List<Team> mapCoreTeams = new java.util.ArrayList<>();
                for (var td : Vars.state.teams.present) {
                    if (td.cores.size > 0 && td.team != Team.derelict) {
                        mapCoreTeams.add(td.team);
                    }
                }

                // ⚠ 地图自带核心还没填充时**必须重试，不能回落**。
                //
                // 回落意味着 alpha/beta 绑到配置里的 team 100/101 —— 那两队在这张图上
                // 没有核心，于是 PlayerComp.checkSpawn() 找不到 core、永远不给单位；
                // 没有单位也没有核心，队伍视野就是零，什么都看不见。
                // 表现出来正是「AI 开局没视野、完全不动」。实测根因在此，不是迷雾本身。
                //
                // 官方 PvP 图一定有核心队，所以「空」只可能是还没填充完。
                if (mapCoreTeams.isEmpty() && fOfficialPvp && attempt[0] < 40) {
                    attempt[0]++;
                    if (attempt[0] == 1 || attempt[0] % 10 == 0) {
                        lg.append("waiting for map core teams (attempt ").append(attempt[0]).append("); ");
                    }
                    arc.util.Time.run(2f, phase2[0]);
                    return;
                }
                if (mapCoreTeams.isEmpty()) {
                    lg.append("WARN: no map core teams after ").append(attempt[0])
                      .append(" attempts; falling back to config teams; ");
                }
                StringBuilder coreTeamNames = new StringBuilder("[");
                for (int k = 0; k < mapCoreTeams.size(); k++) {
                    if (k > 0) coreTeamNames.append(',');
                    coreTeamNames.append(mapCoreTeams.get(k).name);
                }
                coreTeamNames.append(']');
                lg.append("officialPvp=").append(fOfficialPvp)
                  .append(", mapCoreTeams=").append(coreTeamNames).append("; ");

            // ---- 4. 为每个非 admin agent 放核心 ----
            // 全新服务器没有存档，内容全部处于未解锁状态。
            // Block.isVisible() 的第一步就是 !isHidden()，而 isHidden() 依赖解锁状态，
            // 所以不解锁的话 isPlaceable() 恒为 false，validPlace 一律失败。
            {
                int unlocked = 0;
                for (Block b : Vars.content.blocks()) {
                    if (!b.unlockedNow()) {
                        b.unlock();
                        unlocked++;
                    }
                }
                log.append("unlocked=").append(unlocked).append("; ");
            }

            // 明确按尺寸升序挑选：核心越小越容易找到落脚点。
            Block coreBlock = Vars.content.block("core-shard");         // 3x3
            if (coreBlock == null) coreBlock = Vars.content.block("core-foundation");
            if (coreBlock == null) {
                Block smallest = null;
                for (Block b : Vars.content.blocks()) {
                    if (!(b instanceof mindustry.world.blocks.storage.CoreBlock) || b.isHidden()) continue;
                    if (smallest == null || b.size < smallest.size) smallest = b;
                }
                coreBlock = smallest;
            }
            if (coreBlock == null) {
                future.complete(Json.error(1500, "no CoreBlock available"));
                return;
            }

            // 让核心「可见」，从而通过 validPlace 的第一关。
            //
            // 核心的 buildVisibility 是 BuildVisibility.coreZoneOnly，其 visible() 判定为
            // Vars.indexer.isBlockPresent(Blocks.coreZone) —— 依赖方块索引，而索引不会
            // 因为运行时铺地板而刷新，所以仅靠 layCoreZone() 不足以让 isHidden() 变 false。
            //
            // Block.isHidden() 的完整语义是：
            //   return !buildVisibility.visible() && !state.rules.revealedBlocks.contains(this);
            // revealedBlocks 正是绕过 buildVisibility 的正规出口，这里使用它。
            // 同时仍保留 layCoreZone() —— CoreBlock.canPlaceOn 要求地板 allowCorePlacement。
            r.revealedBlocks.add(coreBlock);

            log.append("coreBlock=").append(coreBlock.name)
               .append("(").append(coreBlock.size).append("x").append(coreBlock.size).append(")")
               .append("[hidden=").append(coreBlock.isHidden())
               .append(",unlocked=").append(coreBlock.unlockedNow())
               .append(",editor=").append(r.editor)
               .append(",hideBanned=").append(r.hideBannedBlocks)
               .append(",visible=").append(coreBlock.isVisible())
               .append(",placeable=").append(coreBlock.isPlaceable()).append("]; ");

            // 核心放置最终采用 editor 路径。
            //
            // 原因：Block.isVisible() 在非 editor 模式下对核心类方块返回 false
            // （isHidden() 受 UnlockableContent 的解锁/可见性语义影响，与是否 unlock
            // 无直接关系），导致 isPlaceable() 恒为 false、validPlace 一律失败。
            //
            // editor=true 时 Build.validPlaceIgnoreUnits 的第一个检查整段跳过
            // （Build.java:185），这是引擎提供的、用于「地图编辑器」的正规后门。
            // setup 是管理员操作，语义上与地图初始化一致，使用它是合适的。
            // 放置完成后立即恢复 editor=false，不影响后续的正常游玩约束。
            boolean prevEditor = r.editor;
            r.editor = true;

            // 放核心需要「该格已被探索」，而探索又需要视野源 —— 视野源又需要核心。
            // Build.validPlaceIgnoreUnits 的逐格检查里有：
            //   (state.rules.staticFog && state.rules.fog && !fogControl.isDiscovered(team, wx, wy))
            // 新队伍从未探索过任何格子，这一条会拒绝全图。
            // 放置期间临时关闭 staticFog 打破循环，放完立即恢复。
            boolean prevStaticFog = r.staticFog;
            r.staticFog = false;

            // 下面还会临时关掉核心保护圈、清空禁用方块表 —— 同样必须先存原值。
            // 漏了恢复的后果比 staticFog 更重：
            //   enemyCoreBuildRadius 默认 400f（≈50 格），Rules.java:295 是
            //       protectCores ? enemyCoreBuildRadius + extraCoreBuildRadius : 0
            //   归零之后再没人拦得住「贴着别人核心造炮塔」。
            //   bannedBlocks 则可能被地图用来禁方块，清空后那些方块变成可建。
            float prevCoreRadius = r.enemyCoreBuildRadius;
            boolean prevBlockWhitelist = r.blockWhitelist;
            arc.struct.ObjectSet<mindustry.world.Block> prevBanned = new arc.struct.ObjectSet<>();
            prevBanned.addAll(r.bannedBlocks);

            StringBuilder placed = new StringBuilder("[");
            boolean firstPlaced = true;
            java.util.List<int[]> takenSpots = new java.util.ArrayList<>();
            // 本次 setup 已经自建的核心位置 —— 后续 findCoreSpot 要靠它把核心拉开
            java.util.List<int[]> takenCoreSpots = new java.util.ArrayList<>();

            // ---- 4a. 优先接管地图自带的 PvP 核心 ----
            //
            // 官方 PvP 地图（Maps.pvpMaps = veins/glacier/passage）自带两个对称核心，
            // 分属 sharded 与 crux。直接让 agent 接管这些队伍，比另造核心更符合
            // 地图设计意图，也省掉一整套核心放置的坑。
            java.util.List<AIArena.Agent> waiting = new java.util.ArrayList<>();
            int bindIndex = 0;
            for (AIArena.Agent a : AIArena.agents) {
                if (a.admin) continue;

                if (bindIndex < mapCoreTeams.size()) {
                    Team t = mapCoreTeams.get(bindIndex++);
                    a.bindTeam(t.id);
                    // 地图自带的 PvP 核心带着满库存，这里立刻换成启动资源
                    resetCoreItems(t);

                    // 不预置任何单位。
                    //
                    // 引擎的 PlayerComp.update() 会自动给「没有单位的玩家」从核心
                    // 生成初始单位（core.requestSpawn(self())），所以只要给 agent
                    // 建一个真实的 Player 并加入队伍，它就会像真人玩家一样拿到单位。
                    // 早期版本在这里手动 spawnBuilder 塞了一个 poly，等于白送 AI
                    // 一个建造单位 —— 那是玩家没有的优势。
                    String pname = spawnAgentPlayer(a, t, log);

                    log.append("bind[").append(a.id).append("]->").append(t.name);
                    if (pname != null) log.append(" as ").append(pname);
                    log.append("; ");

                    if (!firstPlaced) placed.append(',');
                    firstPlaced = false;

                    var core = t.core();
                    Json.Obj o = new Json.Obj()
                        .put("agent", a.id).put("team", t.id)
                        .put("teamName", t.name)
                        .put("coreSource", "map")
                        .put("player", pname == null ? "" : pname);
                    if (core != null) o.put("coreX", core.tileX()).put("coreY", core.tileY());
                    placed.append(o.toString());
                } else {
                    a.resetTeam();
                    waiting.add(a);
                }
            }

            // ---- 4b. 地图核心不够时，为剩余 agent 自建核心 ----
            for (AIArena.Agent a : waiting) {
                Team t = a.team();
                if (t == null) continue;

                // 地图核心不够时，为剩余 agent 自建核心（cores=auto，默认）。
                //
                // 官方 PvP 图只给两个核心队（veins/glacier 是 2 个，passage 是 2 队
                // 共 5 个核心），而配置里可以有 4 个 agent。要么只跑 2 个 AI
                // （cores=none），要么给多出来的队伍补核心。
                //
                // 补核心时位置必须拉开 —— 见 findCoreSpot 的注释，早期版本把它们
                // 堆在了地图正中央。
                if (!"auto".equalsIgnoreCase(p.get("cores", "auto"))) {
                    log.append("skip core for ").append(a.id).append(" (cores=none); ");
                    a.resetTeam();
                    continue;
                }

                // 候选点按评分排序，逐个试到引擎点头为止。
                //
                // 每次尝试都会先铲掉自然方块、再铺 coreZone，然后问 validPlace。
                // 只要有一条引擎内部的检查不通过就换下一个候选 —— 这比在外面
                // 复刻 validPlace 的每一条分支可靠得多。
                java.util.List<int[]> candidates = findCoreSpot(coreBlock, t, takenCoreSpots);
                if (candidates.isEmpty()) {
                    log.append("no core spot for ").append(a.id).append("; ");
                    continue;
                }

                int[] spot = null;
                int[] firstTried = null;
                for (int[] cand : candidates) {
                    if (firstTried == null) firstTried = cand;

                    clearNaturalBlocks(cand[0], cand[1], coreBlock.size);
                    layCoreZone(cand[0], cand[1], coreBlock.size);

                    if (mindustry.world.Build.validPlace(coreBlock, t, cand[0], cand[1], 0)) {
                        spot = cand;
                        break;
                    }
                }

                if (spot == null) {
                    // 全部候选都被引擎否掉了 —— 把第一个候选的失败细节留下，便于定位
                    Tile ft = Vars.world.tile(firstTried[0], firstTried[1]);
                    log.append("no core spot for ").append(a.id)
                       .append(" (tried ").append(candidates.size()).append(" candidates; first ")
                       .append(firstTried[0]).append(",").append(firstTried[1])
                       .append("{canPlaceOn=").append(coreBlock.canPlaceOn(ft, t, 0))
                       .append(",noUnitOverlap=").append(mindustry.world.Build.checkNoUnitOverlap(coreBlock, firstTried[0], firstTried[1]))
                       .append(",ignoreUnits=").append(mindustry.world.Build.validPlaceIgnoreUnits(coreBlock, t, firstTried[0], firstTried[1], 0, true, true))
                       .append(",floor=").append(ft == null ? "null" : ft.floor().name)
                       .append(",polyProtect=").append(r.polygonCoreProtection)
                       .append("}); ");
                    continue;
                }

                takenCoreSpots.add(spot);
                Tile tile = Vars.world.tile(spot[0], spot[1]);
                tile.setBlock(coreBlock, t, 0);
                // 核心一落地就把库存设成启动资源。
                // 不能只靠最后遍历 teams.present —— 刚 setBlock 出来的核心
                // 所属的 TeamData 还没进 present，实测那样会漏掉 agent3/agent4。
                resetCoreItems(t);
                log.append("core[").append(a.id).append("]@")
                   .append(spot[0]).append(",").append(spot[1]).append("; ");

                if (!firstPlaced) placed.append(',');
                firstPlaced = false;
                placed.append(new Json.Obj()
                    .put("agent", a.id).put("team", t.id)
                    .put("coreX", spot[0]).put("coreY", spot[1]).toString());

                // ---- 5. 不预置单位 ----
                //
                // 自建核心的 agent 同样只建 Player，单位交给引擎自动生成。
                // 之前这里手搓了一个 poly，等于白送 AI 一个建造单位。
                spawnAgentPlayer(a, t, log);
            }

            // ---- 6. 统一启动资源 ----
            //
            // 地图自带的 PvP 核心会带满一整套库存（veins 上每种 2000），
            // 等于把经济起点抬到「什么都有」—— 建造不花钱、冶炼不用建、
            // 整条产线形同虚设。竞技场要的是公平且有限的起手。
            //
            // 只给铜和铅各 500，其余全部归零。够放：矿机(铜12)、传送带(铜1)、
            // 冶炼厂(铜30+铅25)、发电机(铜25+铅15)、节点(铜2+铅6)、炮塔(铜35)。
            // 硅、石墨、钛、钍一律为 0 —— 想要就得自己挖、自己炼。
            log.append(applyStartingItems(log));

            placed.append(']');

            // 恢复 editor / staticFog / 核心保护圈 / 禁用方块表
            r.editor = prevEditor;
            r.staticFog = prevStaticFog;
            r.enemyCoreBuildRadius = prevCoreRadius;
            r.blockWhitelist = prevBlockWhitelist;
            r.bannedBlocks.clear();
            r.bannedBlocks.addAll(prevBanned);

            // ⚠ 必须**在恢复 staticFog 之后**补推一次迷雾事件。
            //
            // 上面为了绕开 validPlace 的「该格必须已探索」死循环，把 staticFog 临时
            // 关掉了。而 FogControl 的 TileChangeEvent 处理器里有一道
            //     if(state.rules.staticFog){ pushEvent(...); }
            // 所以整个放置期间，新核心的迷雾事件**全被静默丢弃**。
            // 等这里恢复成 true，事件早没了 —— 结果是 team#102/103 的
            // staticData 永远是全零位图。
            //
            // 后果不止是「自己基地看不见」：客户端切到这一队时
            // FogRenderer 拿到的是一张全零的探索位图，于是整屏全黑，
            // 而 UI 层（队伍名、核心库存）却完全正常 —— 非常容易被误判成
            // 「视角绑定错了」或「相机问题」。
            //
            // 地图自带的核心不受影响，因为它们的迷雾是 WorldLoadEvent 时
            // pushStaticBlocks() 一次性推的，走的不是这条路径。
            if (r.fog && r.staticFog) {
                // 标记：让逐帧循环在接下来一段时间里持续补推。
                //
                // 不能就地做，也不能只 Time.run 一次 —— 实测核心放进世界之后，
                // 它要过一会儿才真正出现在 Groups.build 里（就地和 30 帧后都只
                // 数到地图自带的那 2 个核心）。而 forceUpdate 是幂等的：
                // 重复推只是把同一个圆重画一遍，没有副作用。
                // 所以这里挂个时间窗，由 update 循环反复补，直到世界稳定。
                AIArena.FOG_REPUSH_UNTIL = arc.util.Time.millis() + 20_000L;
            }

            // 诊断：单位是否真的进入了世界
            log.append("worldUnits=").append(mindustry.gen.Groups.unit.size())
               .append(",worldBuilds=").append(mindustry.gen.Groups.build.size())
               .append("; ");
            for (mindustry.gen.Unit u : mindustry.gen.Groups.unit) {
                log.append("  unit ").append(u.type.name)
                   .append(" team=").append(u.team.name)
                   .append(" pos=(").append((int)u.x).append(",").append((int)u.y).append(")")
                   .append(" added=").append(u.isAdded())
                   .append(" build=").append(u.canBuild())
                   .append("; ");
            }
            log.append("editorRestored=").append(r.editor).append("; ");

            future.complete(Json.ok(new Json.Obj()
                .put("message", log.toString())
                .put("map", fChosen.name())
                .put("width", Vars.world.width())
                .put("height", Vars.world.height())
                .putRaw("cores", placed.toString())
                .toString()));

              } catch (Throwable t) {
                AIArena.log("setup phase2 failed: " + t);
                future.complete(Json.error(1500, "setup phase2: " + t));
              }
            };
            arc.util.Time.run(2f, phase2[0]);

          } catch (Throwable t) {
            AIArena.log("setup phase1 failed: " + t);
            future.complete(Json.error(1500, "setup phase1: " + t));
          }
        });

        // HTTP 线程等待两阶段完成。setup 涉及换图与整帧调度，给足 8 秒。
        try {
            String json = future.get(8000, TimeUnit.MILLISECONDS);
            // 只认开头，不能全文搜。成功响应里也会出现 "ok":false ——
            // /place 在材料不足时，materials.requirements 每一项都带着
            // {"ok":false,"short":N}，全文匹配会把「计划已排上」判成错误，
            // 回出 HTTP 400 配 body {"ok":true,...}，调用方按状态码分流就中招。
            boolean isError = json != null && json.startsWith("{\"ok\":false");
            respond(ex, isError ? statusFor(json) : 200, json);
        } catch (java.util.concurrent.TimeoutException te) {
            respond(ex, 504, Json.error(1007, "setup did not finish within 8000 ms"));
        } catch (Throwable t) {
            respond(ex, 500, Json.error(1500, String.valueOf(t)));
        }
    }

    /**
     * 搜索一块能放下核心的空地。
     *
     * 核心的 buildVisibility 是 BuildVisibility.coreZoneOnly，其可见性判定为
     * Vars.indexer.isBlockPresent(Blocks.coreZone) —— 也就是「地图上存在 coreZone 地板」。
     * 没有该地板时 Block.isHidden() 返回 true，导致 isVisible()/isPlaceable() 全为 false，
     * validPlace 从第一个检查就失败。
     *
     * 因此正确流程是：先铺 coreZone 地板，再走正常的 validPlace 放核心。
     * 见 CoreBlock.canPlaceOn（CoreBlock.java:184）与 BuildVisibility.java:14。
     */
    /**
     * 给 agent 创建一个真实玩家并绑定。
     *
     * 为什么这样做：
     *   Mindustry 的 PlayerComp.update() 会自动给「没有单位的玩家」从核心生成
     *   初始单位（core.requestSpawn(self())，见 PlayerComp.java:233-241）。
     *   所以只要 agent 对应一个真实 Player 并加入队伍，引擎就会像对待真人玩家
     *   一样给它单位 —— 不需要手动 spawn，也不该预置任何兵和建筑。
     *
     * 这个 Player 没有网络连接（con == null），也就是 Player.isLocal() 为 true。
     * 对本竞技场没有影响：AI 全走 HTTP，不依赖网络同步；而服务端逻辑
     * （PlayerComp、BuilderComp、权限检查）对 local 玩家一样生效。
     *
     * @return 玩家名，失败返回 null
     */
    static String spawnAgentPlayer(AIArena.Agent a, Team t, StringBuilder log) {
        try {
            var p = mindustry.gen.Player.create();
            String name = "[AI] " + a.id;
            p.name = name;
            p.team(t);
            p.admin = a.admin;
            p.add();

            a.bindPlayer(p);

            // 立刻让它尝试生成一次，不用等 deathTimer 走完
            try { p.checkSpawn(); } catch (Throwable ignored) {}

            return name;
        } catch (Throwable e) {
            log.append("player[").append(a.id).append("] failed: ").append(e).append("; ");
            return null;
        }
    }

    /** 在队伍的核心附近生成一个建造单位。返回生成的格坐标，失败时返回 null。 */
    private static int[] spawnBuilder(Team t, String agentId, java.util.List<int[]> takenSpots,
                                      StringBuilder log) {
        mindustry.type.UnitType ut = pickBuilderUnit();
        if (ut == null) { log.append("no builder type for ").append(agentId).append("; "); return null; }

        // 优先贴着核心放，其次全图找空地
        int[] spot = null;
        var core = t.core();
        if (core != null) {
            int cx = core.tileX(), cy = core.tileY();
            outer:
            for (int r = 2; r < 24; r++) {
                for (int dy = -r; dy <= r; dy++) {
                    for (int dx = -r; dx <= r; dx++) {
                        int x = cx + dx, y = cy + dy;
                        if (isClearArea(x, y, 1, Vars.world.width(), Vars.world.height())
                            && !isTaken(takenSpots, x, y)) { spot = new int[]{x, y}; break outer; }
                    }
                }
            }
        }
        if (spot == null) spot = findUnitSpot(t, takenSpots);
        if (spot == null) { log.append("no unit spot for ").append(agentId).append("; "); return null; }

        takenSpots.add(spot);
        mindustry.gen.Unit u = ut.create(t);
        u.set(spot[0] * Vars.tilesize + Vars.tilesize / 2f,
              spot[1] * Vars.tilesize + Vars.tilesize / 2f);
        u.add();
        log.append("unit[").append(agentId).append("]=").append(ut.name)
           .append("@").append(spot[0]).append(",").append(spot[1]).append("; ");
        return spot;
    }

    private static boolean isTaken(java.util.List<int[]> taken, int x, int y) {
        for (int[] p : taken) {
            if (Math.abs(p[0] - x) < 8 && Math.abs(p[1] - y) < 8) return true;
        }
        return false;
    }

    /** 自建核心之间、以及自建核心与地图自带核心之间的最小间距（格）。 */
    private static final float MIN_CORE_SEP_TILES = 55f;

    /**
     * 给额外队伍找一块放核心的地方。
     *
     * 早期版本从**地图中心**向外螺旋搜索，结果 veins 上两个自建核心落在
     * (175,100) 和 (178,97) —— 也就是地图正中央、彼此相距 3 格。看着像凭空
     * 冒出来的一堆建筑，而且位置完全不对等。
     *
     * 现在改成全局择优：候选点必须离所有已有核心至少 MIN_CORE_SEP_TILES 格，
     * 评分同时奖励「离最近的核心远」和「离地图中心远」，于是额外核心自然被
     * 推到空旷的角落，彼此拉开。
     */
    private static java.util.List<int[]> findCoreSpot(Block coreBlock, Team team, java.util.List<int[]> placed) {
        int size = Math.max(1, coreBlock.size);
        int w = Vars.world.width(), h = Vars.world.height();

        // 已有核心：地图自带的 + 本次 setup 已经放下的
        java.util.List<int[]> existing = new java.util.ArrayList<>();
        for (Team tt : Team.all) {
            try {
                for (var core : tt.cores()) {
                    if (core != null) existing.add(new int[]{core.tileX(), core.tileY()});
                }
            } catch (Throwable ignored) {}
        }
        existing.addAll(placed);

        // 返回**排序后的候选列表**，由调用方逐个试到 validPlace 通过为止。
        //
        // 早期这里是「挑一个最优的，然后祈祷它能过」。但 validPlace 内部的检查
        // 分支很多（核心半径、暗度、地形、浅水……），想在外面完整镜像每一条
        // 不现实，漏掉任何一条就会像 agent4 那样拿不到核心 —— 表现是
        // canPlaceOn=true / noUnitOverlap=true 但 ignoreUnits=false，
        // 光看这三个布尔值根本看不出是哪一步否掉的。
        //
        // 与其猜，不如让引擎自己裁决：按评分从好到坏试。
        java.util.List<int[]> spots = new java.util.ArrayList<>();
        collectCoreSpots(size, w, h, existing, false, spots);
        if (spots.isEmpty()) {
            // 自然地形挡路时允许推平一小块 —— 给一个队伍开辟出生点是必要的，
            // 但绝不碰任何已有建筑。
            collectCoreSpots(size, w, h, existing, true, spots);
        }
        return spots;
    }

    /**
     * 收集候选位置并按评分排序（离其他核心越远、离地图中心越远越好）。
     *
     * @param allowClearing 是否允许候选点上有自然方块（会被推平）
     */
    private static void collectCoreSpots(int size, int w, int h,
                                         java.util.List<int[]> existing, boolean allowClearing,
                                         java.util.List<int[]> out) {
        arc.struct.Seq<int[]> scored = new arc.struct.Seq<>();

        for (int y = 3; y < h - size - 3; y += 3) {
            for (int x = 3; x < w - size - 3; x += 3) {
                if (!areaFree(x, y, size, w, h, allowClearing)) continue;

                float nearest = Float.MAX_VALUE;
                for (int[] c : existing) {
                    float d = (float) Math.hypot(x - c[0], y - c[1]);
                    if (d < nearest) nearest = d;
                }

                // 离其他核心越远越好，也离地图正中央越远越好 ——
                // 核心堆在中路既难看也不公平
                float fromCenter = (float) Math.hypot(x - w / 2f, y - h / 2f);
                float score = nearest + fromCenter * 0.5f;

                scored.add(new int[]{x, y, (int) (score * 10f)});
            }
        }

        scored.sort((a, b) -> Integer.compare(b[2], a[2]));

        // 上限：试太多个会让 setup 变慢，而且每次尝试都会改动地图
        int limit = Math.min(scored.size, 24);
        for (int i = 0; i < limit; i++) {
            int[] s = scored.get(i);
            out.add(new int[]{s[0], s[1]});
        }
    }


    /**
     * 区域是否可用作核心位置。
     *
     * allowClearing = false：要求全是空地。
     * allowClearing = true ：允许有自然方块（会被推平），但不允许有建筑。
     */
    private static boolean areaFree(int x, int y, int size, int w, int h, boolean allowClearing) {
        if (x < 1 || y < 1 || x + size > w - 1 || y + size > h - 1) return false;
        for (int dy = 0; dy < size; dy++) {
            for (int dx = 0; dx < size; dx++) {
                Tile t = Vars.world.tile(x + dx, y + dy);
                if (t == null) return false;
                // 任何情况下都不动别人的建筑
                if (t.build != null) return false;
                if (!allowClearing) {
                    if (t.block() != mindustry.content.Blocks.air) return false;
                    if (t.solid()) return false;
                }
            }
        }
        return true;
    }

    /** 把区域内的自然方块铲平，给核心腾地方。不动任何建筑。 */
    private static void clearNaturalBlocks(int x, int y, int size) {
        for (int dy = 0; dy < size; dy++) {
            for (int dx = 0; dx < size; dx++) {
                Tile t = Vars.world.tile(x + dx, y + dy);
                if (t == null) continue;
                if (t.build != null) continue;
                if (t.block() != mindustry.content.Blocks.air) {
                    t.setBlock(mindustry.content.Blocks.air);
                }
            }
        }
    }

    /**
     * 在指定区域铺 coreZone 地板。
     * 这是核心能够通过 validPlace 的前提，也是自制 PvP 地图必须做的事。
     */
    /** 统一启动资源：铜 500 + 铅 500，其余归零。 */
    public static final int START_COPPER = 500;
    public static final int START_LEAD = 500;

    /**
     * 把每个有核心的队伍库存重置成统一的启动资源。
     *
     * 地图自带的 PvP 核心带着满库存（veins 上每种 2000），不清掉的话
     * 「经济」这一层根本不存在。这里按物品表逐项清零再补铜铅，
     * 不依赖 ItemModule.clear() 的具体实现，避免漏掉某项。
     *
     * @return 写进 setup 日志的一段摘要
     */
    private static String applyStartingItems(StringBuilder log) {
        StringBuilder sb = new StringBuilder();
        for (var td : Vars.state.teams.present) {
            if (td.team == Team.derelict) continue;
            if (resetCoreItems(td.team)) {
                sb.append("startItems[").append(td.team.name).append("]=")
                  .append(START_COPPER).append("c/").append(START_LEAD).append("l; ");
            }
        }
        return sb.toString();
    }

    /**
     * 把一支队伍的核心库存重置成启动资源。
     *
     * ⚠ 必须**核心一建好就调用**，不能只靠最后遍历 teams.present。
     * 自建核心是直接 tile.setBlock() 出来的，那一刻它所属的 TeamData
     * 还没进 teams.present —— 实测最后统一清点时只清到了地图自带的
     * sharded/crux，agent3/agent4 的核心库存仍是空的。
     *
     * @return 是否真的找到了核心并重置
     */
    private static boolean resetCoreItems(Team team) {
        if (team == null || team == Team.derelict) return false;
        var core = team.core();
        if (core == null || core.items == null) return false;

        core.items.clear();
        for (mindustry.type.Item it : Vars.content.items()) core.items.set(it, 0);
        core.items.set(mindustry.content.Items.copper, START_COPPER);
        core.items.set(mindustry.content.Items.lead, START_LEAD);
        return true;
    }
    private static void layCoreZone(int x, int y, int size) {
        mindustry.world.Block zone = Vars.content.block("core-zone");
        if (zone == null || !(zone instanceof mindustry.world.blocks.environment.Floor floor)) return;
        for (int dy = -1; dy <= size; dy++) {
            for (int dx = -1; dx <= size; dx++) {
                Tile t = Vars.world.tile(x + dx, y + dy);
                if (t != null) t.setFloor(floor);
            }
        }
    }

    /** size×size 区域内是否全为空地。 */
    private static boolean isClearArea(int x, int y, int size, int w, int h) {
        if (x < 1 || y < 1 || x + size > w - 1 || y + size > h - 1) return false;
        for (int dy = 0; dy < size; dy++) {
            for (int dx = 0; dx < size; dx++) {
                Tile t = Vars.world.tile(x + dx, y + dy);
                if (t == null) return false;
                if (t.block() != mindustry.content.Blocks.air) return false;
                if (t.solid()) return false;
            }
        }
        return true;
    }

    /** 找一块能生成单位的空地：非固体、无方块、不在敌方核心保护圈内即可。 */
    private static int[] findUnitSpot(Team team, java.util.List<int[]> taken) {
        int w = Vars.world.width(), h = Vars.world.height();
        int cx = w / 2, cy = h / 2;
        for (int radius = 0; radius < Math.max(w, h); radius += 4) {
            for (int dy = -radius; dy <= radius; dy += 4) {
                for (int dx = -radius; dx <= radius; dx += 4) {
                    int x = cx + dx, y = cy + dy;
                    if (x < 4 || y < 4 || x >= w - 4 || y >= h - 4) continue;
                    // 避开已被其它 agent 占用的点，否则两个单位重叠会互相顶掉
                    boolean used = false;
                    for (int[] p : taken) {
                        if (Math.abs(p[0] - x) < 8 && Math.abs(p[1] - y) < 8) { used = true; break; }
                    }
                    if (used) continue;

                    Tile t = Vars.world.tile(x, y);
                    if (t == null) continue;
                    if (t.solid() || t.block().solid) continue;
                    if (t.block() != mindustry.content.Blocks.air) continue;
                    return new int[]{x, y};
                }
            }
        }
        return null;
    }

    /** 选一个能建造的单位类型。优先用专职建造机。 */
    private static mindustry.type.UnitType pickBuilderUnit() {
        // 明确按名字取标准建造机，避免选中攻击机（如 nova 虽有 buildSpeed 但会飞走/被击落）
        for (String name : new String[]{"mono", "poly", "mega"}) {
            mindustry.type.UnitType u = Vars.content.unit(name);
            if (u != null && !u.isHidden() && u.buildSpeed > 0f) return u;
        }
        // 兜底：任何 buildSpeed > 0 且非飞行的单位
        for (mindustry.type.UnitType u : Vars.content.units()) {
            if (u.isHidden() || u.buildSpeed <= 0f || u.flying) continue;
            return u;
        }
        // 再兜底：任何 buildSpeed > 0 的单位
        for (mindustry.type.UnitType u : Vars.content.units()) {
            if (!u.isHidden() && u.buildSpeed > 0f) return u;
        }
        return null;
    }

    // ---------------------------------------------------------------- filtering

    /**
     * 安全的视野查询。
     *
     * FogControl 由主线程维护，其内部数据结构不是线程安全的。HTTP 线程直接调用
     * 会在并发下抛 NoSuchElementException（实测 32 线程时约 1.5% 的请求失败）。
     *
     * 这里保守兜底：查询失败时返回「不可见」。这个方向是安全的 ——
     * 宁可少看到一格，也不能因为异常而多看到东西，否则就破坏了对等约束。
     *
     * 注意只对**敌方**实体走这条路径（己方实体不查视野），所以失败时
     * 隐藏的都是敌方信息，不会影响 AI 对自己局面的判断。
     */
    private static boolean safeVisible(Team team, float x, float y) {
        if (!Vars.state.rules.fog) return true;
        try { return Vars.fogControl.isVisible(team, x, y); }
        catch (Throwable t) { return false; }
    }

    private static boolean safeVisibleTile(Team team, int x, int y) {
        if (!Vars.state.rules.fog) return true;
        try { return Vars.fogControl.isVisibleTile(team, x, y); }
        catch (Throwable t) { return false; }
    }

    private static boolean safeDiscovered(Team team, int x, int y) {
        if (!Vars.state.rules.fog) return true;
        try { return Vars.fogControl.isDiscovered(team, x, y); }
        catch (Throwable t) { return false; }
    }

    /**
     * 写入液体信息。
     *
     * Mindustry 里「液体」不是独立的一层 —— 液体本身就是一种 Floor
     * （water / deep-water / oil / slag / cryofluid / arkycite），
     * 靠 Floor.isLiquid 标记。地板还能声明 liquidDrop，那是抽水机的产出。
     *
     * 所以 /map 只给 floor 名字是不够的：调用方无法判断那到底是地面还是水面，
     * 也拿不到深水标记（drownTime > 0，地面单位不能站）。
     */
    private static void putLiquidInfo(Json.Obj o, Tile t) {
        var fl = t.floor();
        if (fl == null) { o.put("liquid", "air"); return; }
        if (fl.isLiquid) o.put("liquid", fl.name);
        if (fl.liquidDrop != null) o.put("liquidDrop", fl.liquidDrop.name);
        if (fl.drownTime > 0f) o.put("deep", true);
    }

    /**
     * 取某个频道当前帧的 JSON。供 WebSocket 推送使用。
     *
     * 返回 null 表示「这个频道此刻没有内容」。
     * 必须在**游戏主线程**调用 —— 它读 Vars.state / Groups，和 HTTP handler 一样。
     */
    static String channelJson(String channel, AIArena.Agent agent) {
        if (agent == null) return null;
        Team team = agent.team();
        if (team == null) return null;
        Snapshot.State s = Snapshot.get();

        switch (channel) {
            case "state" -> {
                return new Json.Obj()
                    .put("tick", s.tick)
                    .put("playing", Vars.state.isPlaying())
                    .put("paused", Vars.state.isPaused())
                    .put("fog", Vars.state.rules.fog)
                    .put("team", team.name).put("teamId", team.id)
                    .put("worldW", Vars.world.width()).put("worldH", Vars.world.height())
                    .put("units", s.units.length).put("buildings", s.builds.length)
                    .toString();
            }
            case "units" -> {
                return visibleUnits(s, team.id, false);
            }
            case "buildings" -> {
                return visibleBuildings(s, team.id, false);
            }
            case "factory" -> {
                return factoryJson(team);
            }
            case "drill" -> {
                return drillJson(team);
            }
            case "events" -> {
                return EventLog.recentJson(40);
            }
            default -> {
                return null;
            }
        }
    }

    /** 单位工厂的生产状态，JSON 数组。REST 的 /factory 与 WS 的 factory 频道共用。 */
    static String factoryJson(Team team) {
        StringBuilder arr = new StringBuilder("[");
        boolean first = true;
        for (mindustry.gen.Building b : team.data().buildings) {
            boolean isFactory = b instanceof mindustry.world.blocks.units.UnitFactory.UnitFactoryBuild;
            boolean isAssembler = b instanceof mindustry.world.blocks.units.UnitAssembler.UnitAssemblerBuild;
            if (!isFactory && !isAssembler) continue;
            if (Vars.state.rules.fog && !Vars.fogControl.isVisibleTile(team, b.tileX(), b.tileY())) continue;

            if (!first) arr.append(',');
            first = false;

            Json.Obj o = new Json.Obj()
                .put("x", b.tileX()).put("y", b.tileY())
                .put("block", b.block.name)
                .put("efficiency", b.efficiency)
                .put("enabled", b.enabled)
                .put("powered", b.power != null && b.power.status > 0f);

            if (isFactory) {
                var uf = (mindustry.world.blocks.units.UnitFactory.UnitFactoryBuild) b;
                var ut = uf.unit();
                o.put("plan", ut == null ? "" : ut.name);
                o.put("progress", uf.fraction());
                o.put("planIndex", uf.currentPlan);
                o.put("payload", uf.payload == null ? "" : uf.payload.getClass().getSimpleName());
                String puName = "";
                if (uf.payload instanceof mindustry.world.blocks.payloads.UnitPayload) {
                    puName = ((mindustry.world.blocks.payloads.UnitPayload) uf.payload).unit.type.name;
                }
                o.put("payloadUnit", puName);
                o.put("rotation", uf.rotation);
                o.put("shouldConsume", uf.shouldConsume());
                o.put("activation", b.team.activateUnitFactories());
                String frontName = "";
                boolean frontSolid = false;
                try {
                    mindustry.gen.Building fr = uf.front();
                    if (fr != null) {
                        frontName = fr.block.name;
                        frontSolid = fr.tile != null && fr.tile.solid();
                    }
                } catch (Throwable ignored) {}
                o.put("front", frontName);
                o.put("frontSolid", frontSolid);

                StringBuilder req = new StringBuilder("{");
                boolean rf = true;
                if (ut != null && uf.currentPlan >= 0
                    && uf.currentPlan < ((mindustry.world.blocks.units.UnitFactory) uf.block).plans.size) {
                    for (var stack : ((mindustry.world.blocks.units.UnitFactory) uf.block).plans.get(uf.currentPlan).requirements) {
                        if (!rf) req.append(',');
                        rf = false;
                        req.append(Json.str(stack.item.name)).append(':').append(stack.amount);
                    }
                }
                req.append('}');
                o.putRaw("requirements", req.toString());
            }

            StringBuilder inv = new StringBuilder("{");
            boolean vf = true;
            for (mindustry.type.Item it : Vars.content.items()) {
                int amt = b.items.get(it);
                if (amt <= 0) continue;
                if (!vf) inv.append(',');
                vf = false;
                inv.append(Json.str(it.name)).append(':').append(amt);
            }
            inv.append('}');
            o.putRaw("items", inv.toString());

            arr.append(o.toString());
        }
        return arr.append(']').toString();
    }

    /** 矿机状态，JSON 数组。REST 的 /drill 与 WS 的 drill 频道共用。 */
    static String drillJson(Team team) {
        StringBuilder arr = new StringBuilder("[");
        boolean first = true;
        for (mindustry.gen.Building b : team.data().buildings) {
            if (!(b instanceof mindustry.world.blocks.production.Drill.DrillBuild)) continue;
            if (Vars.state.rules.fog && !Vars.fogControl.isVisibleTile(team, b.tileX(), b.tileY())) continue;

            var d = (mindustry.world.blocks.production.Drill.DrillBuild) b;
            var blk = (mindustry.world.blocks.production.Drill) b.block;

            if (!first) arr.append(',');
            first = false;

            StringBuilder inv = new StringBuilder("{");
            boolean vf = true;
            for (mindustry.type.Item it : Vars.content.items()) {
                int amt = b.items.get(it);
                if (amt <= 0) continue;
                if (!vf) inv.append(',');
                vf = false;
                inv.append(Json.str(it.name)).append(':').append(amt);
            }
            inv.append('}');

            int oreH = d.dominantItem == null ? -1 : d.dominantItem.hardness;

            arr.append(new Json.Obj()
                .put("x", b.tileX()).put("y", b.tileY())
                .put("block", b.block.name)
                .put("tier", blk.tier)
                .put("dominantItem", d.dominantItem == null ? "" : d.dominantItem.name)
                .put("dominantItems", d.dominantItems)
                .put("oreHardness", oreH)
                .put("canMine", d.dominantItem != null && blk.tier >= oreH)
                .put("progress", d.progress())
                .put("warmup", d.warmup)
                .put("lastDrillSpeed", d.lastDrillSpeed)
                .put("itemsPerSecond", d.lastDrillSpeed * 60f)
                .put("dominantItems", d.dominantItems)
                .put("efficiency", b.efficiency)
                .put("enabled", b.enabled)
                .put("full", b.items.total() >= b.block.itemCapacity)
                .put("itemCapacity", b.block.itemCapacity)
                .putRaw("items", inv.toString())
                .toString());
        }
        return arr.append(']').toString();
    }
    static String visibleUnits(Snapshot.State s, int myTeam, boolean admin) {
        Team team = Team.get(myTeam);
        StringBuilder sb = new StringBuilder("[");
        boolean first = true;
        for (Snapshot.UnitInfo u : s.units) {
            if (u.team != myTeam && !admin) {
                // 对称于引擎的 isSyncHidden：敌方单位需在当前视野内
                if (!safeVisible(team, u.x, u.y)) continue;
            }
            if (!first) sb.append(',');
            first = false;

            StringBuilder stack = new StringBuilder("{");
            for (int i = 0; i < u.stackItems.length; i++) {
                if (i > 0) stack.append(',');
                stack.append(Json.str(u.stackItems[i])).append(':').append(u.stackAmounts[i]);
            }
            stack.append('}');

            Json.Obj o = new Json.Obj()
                .put("id", u.id).put("type", u.type).put("team", u.team)
                .put("x", u.x).put("y", u.y)
                .put("health", u.health).put("maxHealth", u.maxHealth)
                .put("rotation", u.rotation).put("canBuild", u.canBuild)
                .putRaw("stack", stack.toString());

            // 正在建哪一格。轮询这个字段的 progress 就能知道它还要多久、
            // 或者是不是卡住了（progress 长时间不动）。
            if (u.fogRadius > 0f) o.put("fogRadius", u.fogRadius);

            if (u.buildX >= 0) {
                o.putRaw("buildingAt", new Json.Obj()
                    .put("x", u.buildX).put("y", u.buildY)
                    .put("progress", u.buildProgress)
                    .put("block", u.buildBlock == null ? "" : u.buildBlock)
                    .toString());
            }

            // 开火状态：玩家看得见单位在射击（枪口火光、弹道）
            if (u.shooting) o.put("shooting", true);

            // 交战目标：位置是可见的（弹道往哪飞），但目标的身份要看它自己是否可见。
            // 目标在雾里时只给方向、不给它是谁 —— 和玩家看到的一致。
            if (!Float.isNaN(u.targetX)) {
                o.put("targetX", u.targetX).put("targetY", u.targetY);
                boolean tVisible = admin
                    || u.targetTeam == myTeam
                    || safeVisible(team, u.targetX, u.targetY);
                if (tVisible) {
                    if (u.targetId >= 0) o.put("targetId", u.targetId);
                    if (u.targetType != null && !u.targetType.isEmpty()) o.put("targetType", u.targetType);
                    if (u.targetTeam >= 0) o.put("targetTeam", u.targetTeam);
                } else {
                    o.put("targetHidden", true);
                }
            }

            // 弹药。UnitType.ammoCapacity 默认 1、ammof() 对普通单位恒为 1，
            // 所以 flare/gamma 这类永远显示 1/1；只有方块单位会真的变化。
            o.put("ammo", u.ammo).put("ammoCapacity", u.ammoCapacity);

            if (u.controllerId >= 0) o.put("controller", u.controllerId);
            if (!u.command.isEmpty()) o.put("command", u.command);
            sb.append(o.toString());
        }
        return sb.append(']').toString();
    }

    /** Point2.pack 的数组 → `[[x,y],...]`。 */
    static String points(int[] packed) {
        StringBuilder s = new StringBuilder("[");
        for (int i = 0; i < packed.length; i++) {
            if (i > 0) s.append(',');
            arc.math.geom.Point2 pt = arc.math.geom.Point2.unpack(packed[i]);
            s.append('[').append(pt.x).append(',').append(pt.y).append(']');
        }
        return s.append(']').toString();
    }

    static String visibleBuildings(Snapshot.State s, int myTeam, boolean admin) {
        Team team = Team.get(myTeam);
        StringBuilder sb = new StringBuilder("[");
        boolean first = true;
        for (Snapshot.BuildInfo b : s.builds) {
            if (b.team != myTeam && !admin) {
                if (!safeVisibleTile(team, b.x, b.y)) continue;
            }
            if (!first) sb.append(',');
            first = false;

            // 库存只给自己的队（DESIGN.md 4.4 的刻意偏离，也是 6.2 的前提）：
            // 原版把每队核心库存无条件广播，本项目改为「按视野 + 需确认」——
            // 敌方库存要连续可见 600 tick 才由 Intel 状态机放出快照。
            // 这里如果照样输出，等于让 AI 一进视野就读到对面核心有多少铜，
            // 整套确认机制被绕过。
            //
            // 其余字段不动：朝向、效率、电力条都是画在屏幕上的，玩家看得见。
            boolean ownTeam = (b.team == myTeam) || admin;

            StringBuilder its = new StringBuilder("{");
            if (ownTeam) {
                for (int i = 0; i < b.items.length; i++) {
                    if (i > 0) its.append(',');
                    its.append(Json.str(b.items[i])).append(':').append(b.itemAmounts[i]);
                }
            }
            its.append('}');

            StringBuilder lqs = new StringBuilder("{");
            if (ownTeam) {
                for (int i = 0; i < b.liquids.length; i++) {
                    if (i > 0) lqs.append(',');
                    lqs.append(Json.str(b.liquids[i])).append(':').append(b.liquidAmounts[i]);
                }
            }
            lqs.append('}');

            Json.Obj o = new Json.Obj()
                .put("x", b.x).put("y", b.y).put("team", b.team).put("id", b.id).put("block", b.block)
                .put("health", b.health).put("maxHealth", b.maxHealth)
                .put("enabled", b.enabled).put("efficiency", b.efficiency)
                // 朝向：玩家看得见任何可见建筑的朝向（传送带流向、炮塔朝向、工厂出口）
                .put("rotation", b.rotation)
                .putRaw("items", its.toString())
                .putRaw("liquids", lqs.toString());

            // 电力：满足度无条件可见（就是屏幕上那根电力条）；
            // 连线按「激光线可见、对端方块未必可见」处理 ——
            // PowerNode.draw() 只对通过迷雾检查的建筑调用，但可见节点的激光线
            // 会一直画到对端真实坐标，所以位置是玩家能看到的；
            // 而雾里那一端是黑的，只知道位置、不知道是什么方块。
            if (b.powerStatus >= 0f) {
                o.put("powerStatus", b.powerStatus);
                StringBuilder lk = new StringBuilder("[");
                boolean lf = true;
                int hidden = 0;
                if (b.powerLinks != null) {
                    for (int packed : b.powerLinks) {
                        arc.math.geom.Point2 pt = arc.math.geom.Point2.unpack(packed);
                        boolean vis = admin || safeVisibleTile(team, pt.x, pt.y);
                        if (!vis) hidden++;
                        if (!lf) lk.append(',');
                        lf = false;
                        Json.Obj lo = new Json.Obj().put("x", pt.x).put("y", pt.y).put("visible", vis);
                        if (vis) {
                            var tb = Vars.world.build(pt.x, pt.y);
                            if (tb != null) lo.put("block", tb.block.name).put("team", tb.team.id);
                        }
                        lk.append(lo.toString());
                    }
                }
                lk.append(']');
                o.putRaw("powerLinks", lk.toString());
                o.put("powerLinksHidden", hidden);
            }

            if (b.fogRadius > 0f) o.put("fogRadius", b.fogRadius);
            if (b.config != null) o.put("config", b.config);
            if (b.constructing) o.put("constructing", true).put("buildProgress", b.buildProgress);

            // 物流接口：这一格能从哪收货、把货推到哪。
            // 只暴露**规则**，不暴露结论 —— 说清楚接口在哪，不替 AI 判断这条链会不会堵。
            if (b.acceptsFrom != null) o.putRaw("acceptsFrom", points(b.acceptsFrom));
            if (b.sendsTo != null) o.putRaw("sendsTo", points(b.sendsTo));

            sb.append(o.toString());
        }
        return sb.append(']').toString();
    }

    // ---------------------------------------------------------------- plumbing

    /** 主线程任务：返回响应 JSON。 */
    private interface GameTask { String run() throws Exception; }

    /**
     * 把任务投递到游戏主线程并等待结果。
     *
     * 超时是必需的 —— 若主线程因大战场卡住，没有超时会让 HTTP 线程池被占满，
     * 整个接口失去响应；有超时则最多丢几个请求，服务仍可用。
     */
    /**
     * 写队列每 tick 的执行预算（DESIGN.md 662「参考 MindustryX 的 1ms」）。
     *
     * 没有它时，一批 /place 会把主线程按住不放：那几毫秒本该用来跑对局，
     * 却被 HTTP 请求吃掉，全场 tick 跟着抖。这是**别人的操作拖慢我**的典型
     * 来源，竞技场里不可接受。
     *
     * 在主线程里计量任务真正执行的时间，按 tick 累计，tick 一变清零。
     * 预算用完后直接拒（1007），不排队 —— 排队只会让积压更深。
     */
    private static long budgetNanos = 1_000_000L;      // 默认 1ms
    private static long budgetTick = -1L;
    private static long budgetUsed = 0L;

    public static void setWriteBudgetMillis(double ms) {
        budgetNanos = (long) (Math.max(0.05, ms) * 1_000_000L);
    }

    private static void postToGame(HttpExchange ex, GameTask task) {
        CompletableFuture<String> future = new CompletableFuture<>();

        Core.app.post(() -> {
            long nowTick;
            try { nowTick = Vars.state == null ? -1L : (long) Vars.state.tick; }
            catch (Throwable t) { nowTick = -1; }

            if (nowTick != budgetTick) {          // 新 tick 清零
                budgetTick = nowTick;
                budgetUsed = 0L;
            }
            if (budgetUsed >= budgetNanos) {
                future.complete(Json.error(1007, "write queue budget exhausted for tick "
                    + nowTick + " (" + (budgetNanos / 1_000_000.0) + " ms/tick); retry next tick"));
                return;
            }

            long t0 = System.nanoTime();
            try { future.complete(task.run()); }
            catch (Throwable t) { future.complete(Json.error(1500, String.valueOf(t))); }
            finally { budgetUsed += System.nanoTime() - t0; }
        });

        try {
            String json = future.get(POST_TIMEOUT_MS, TimeUnit.MILLISECONDS);
            // 只认开头，不能全文搜。成功响应里也会出现 "ok":false ——
            // /place 在材料不足时，materials.requirements 每一项都带着
            // {"ok":false,"short":N}，全文匹配会把「计划已排上」判成错误，
            // 回出 HTTP 400 配 body {"ok":true,...}，调用方按状态码分流就中招。
            boolean isError = json != null && json.startsWith("{\"ok\":false");
            respond(ex, isError ? statusFor(json) : 200, json);
        } catch (java.util.concurrent.TimeoutException te) {
            respond(ex, 504, Json.error(1007, "game thread did not respond within "
                + POST_TIMEOUT_MS + " ms (op_expired)"));
        } catch (Throwable t) {
            respond(ex, 500, Json.error(1500, String.valueOf(t)));
        }
    }

    /**
     * 从错误码推 HTTP 状态，便于 AI 侧按状态码分流。
     *
     * 用解析而不是 `contains` 子串匹配 —— 子串匹配会把错误消息里偶然出现的
     * `"code":1005` 当成分错码。缺映射的码一律 400：调用方**必须**以 body 里的
     * `code` 为准，HTTP 状态只是给代理 / 日志看的粗分类。
     */
    private static int statusFor(String json) {
        return switch (codeOf(json)) {
            case 1001, 1003, 1009 -> 400;
            case 1002 -> 404;
            case 1004 -> 429;
            case 1005, 1403 -> 403;     // forbidden：admin-only 端点、token 与队伍不符
            case 1006 -> 410;
            case 1007 -> 504;
            case 1008 -> 409;           // conflict：footprint 被别的建筑或固体地形占住
            case 1429 -> 429;           // too many requests：令牌桶空了
            default -> 400;
        };
    }

    /** 取响应里第一个 `"code":N` 的 N；取不到返回 -1。 */
    private static int codeOf(String json) {
        if (json == null) return -1;
        int i = json.indexOf("\"code\":");
        if (i < 0) return -1;
        int j = i + 7, k = j;
        while (k < json.length() && Character.isDigit(json.charAt(k))) k++;
        if (k == j) return -1;
        try { return Integer.parseInt(json.substring(j, k)); }
        catch (NumberFormatException e) { return -1; }
    }

    private static void respond(HttpExchange ex, int status, String json) {
        try {
            byte[] b = json.getBytes(StandardCharsets.UTF_8);
            ex.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
            ex.sendResponseHeaders(status, b.length);
            try (OutputStream os = ex.getResponseBody()) { os.write(b); }
        } catch (Throwable ignored) {
            // 客户端提前断开是常态，不需要处理
        }
    }

    // ---------------------------------------------------------------- params

    private static final class Params {
        private final java.util.Map<String, String> map = new java.util.HashMap<>();

        static Params of(HttpExchange ex) {
            Params p = new Params();
            String q = ex.getRequestURI().getQuery();
            if (q != null) {
                for (String kv : q.split("&")) {
                    if (kv.isEmpty()) continue;
                    int eq = kv.indexOf('=');
                    if (eq < 0) { p.map.put(decode(kv), ""); continue; }
                    p.map.put(decode(kv.substring(0, eq)), decode(kv.substring(eq + 1)));
                }
            }
            return p;
        }

        String get(String k, String def) { return map.getOrDefault(k, def); }

        boolean has(String k) { return map.containsKey(k); }

        int getInt(String k, int def) {
            String v = map.get(k);
            if (v == null || v.isEmpty()) return def;
            try { return Integer.parseInt(v.trim()); }
            catch (NumberFormatException e) { return def; }
        }

        float getFloat(String k, float def) {
            String v = map.get(k);
            if (v == null || v.isEmpty()) return def;
            try { return Float.parseFloat(v.trim()); }
            catch (NumberFormatException e) { return def; }
        }

        long getLong(String k, long def) {
            String v = map.get(k);
            if (v == null || v.isEmpty()) return def;
            try { return Long.parseLong(v.trim()); }
            catch (NumberFormatException e) { return def; }
        }

        boolean getBool(String k, boolean def) {
            String v = map.get(k);
            if (v == null || v.isEmpty()) return def;
            return "true".equalsIgnoreCase(v.trim()) || "1".equals(v.trim());
        }

        /** 逗号分隔的 id 列表，如 units=1,2,3。 */
        int[] getIntArray(String k) {
            String v = map.get(k);
            if (v == null || v.isEmpty()) return new int[0];
            String[] parts = v.split(",");
            java.util.List<Integer> out = new java.util.ArrayList<>();
            for (String s : parts) {
                String t = s.trim();
                if (t.isEmpty()) continue;
                try { out.add(Integer.parseInt(t)); }
                catch (NumberFormatException ignored) { }
            }
            int[] arr = new int[out.size()];
            for (int i = 0; i < arr.length; i++) arr[i] = out.get(i);
            return arr;
        }

        private static String decode(String s) {
            try { return java.net.URLDecoder.decode(s, "UTF-8"); }
            catch (Exception e) { return s; }
        }
    }
}
