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
                case "spawn"     -> handleSpawn(ex, agent);
                case "chat"      -> handleChat(ex, agent);
                case "queue"     -> handleQueue(ex, agent);
                case "observe"   -> handleObserve(ex, agent);
                case "record"    -> handleRecord(ex, agent);
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
                        o.put("block", t.block().name);
                        o.put("team", t.team().name);
                        o.put("build", t.build != null);
                    } else {
                        o.put("visible", false);
                        o.put("discovered", discovered);
                        if (discovered) {
                            // 地形是探索过的记忆，玩家能看到；方块与队伍不给
                            o.put("floor", t.floor().name);
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

    /**
     * 下单建造。支持单点与批量形状。
     *
     * POST /place?x=&y=&block=&rot=&config=                      单点
     * POST /place?shape=line&x1=&y1=&x2=&y2=&block=              直线
     * POST /place?shape=area&x1=&y1=&x2=&y2=&block=              实心矩形
     * POST /place?shape=outline&x1=&y1=&x2=&y2=&block=           矩形边框
     * POST /place?shape=circle&x=&y=&radius=&block=              实心圆
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
            postToGame(ex, () -> {
                Actor.Result r = Actor.place(team, x, y, block, rot, config);
                return r.ok ? Json.ok(new Json.Obj().put("message", r.message).toString())
                            : Json.error(r.code, r.message);
            });
            return;
        }

        Operations.Shape shape;
        try { shape = Operations.Shape.valueOf(shapeName.toLowerCase()); }
        catch (IllegalArgumentException e) {
            respond(ex, 400, Json.error(1001, "unknown shape: " + shapeName
                + " (point|line|rect|area|outline|circle)"));
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
            return r.ok ? Json.ok(new Json.Obj()
                              .put("message", r.message)
                              .put("shape", shape.name())
                              .put("tiles", pts.size).toString())
                        : Json.error(r.code, r.message);
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
            return r.ok ? Json.ok(new Json.Obj()
                              .put("message", r.message)
                              .put("shape", shape.name())
                              .put("tiles", pts.size).toString())
                        : Json.error(r.code, r.message);
        });
    }

    /**
     * 生成单位。受人口上限与资源约束，与玩家从核心生产单位同规则。
     *
     * POST /spawn?type=<unitType>&x=&y=
     */
    private static void handleSpawn(HttpExchange ex, AIArena.Agent agent) {
        Params p = Params.of(ex);
        String type = p.get("type", null);
        if (type == null) { respond(ex, 400, Json.error(1001, "required: type")); return; }

        float x = p.getFloat("x", Float.NaN);
        float y = p.getFloat("y", Float.NaN);
        Team team = agent.team();
        if (team == null) { respond(ex, 403, Json.error(1403, "agent has no team")); return; }

        postToGame(ex, () -> {
            // 未给坐标时，用核心位置
            float sx = x, sy = y;
            if (Float.isNaN(sx) || Float.isNaN(sy)) {
                var core = team.core();
                if (core == null) return Json.error(1005, "team " + team.name + " has no core");
                sx = core.x; sy = core.y;
            }
            Actor.Result r = Operations.spawn(team, type, sx, sy);
            return r.ok ? Json.ok(new Json.Obj().put("message", r.message).toString())
                        : Json.error(r.code, r.message);
        });
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
                return Json.ok(new Json.Obj().put("message", r.message).toString());
            }
            return Json.ok(new Json.Obj()
                .put("agent", agent.id).put("team", team.name)
                .putRaw("builders", Operations.queueReport(team))
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
                    .putRaw("cost", req.toString())
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
            // 新放下的核心是空的，BuilderComp 的 hasAll 资源检查会挡住建造。
            // 竞技场场景先用无限资源打通链路，资源规则留待 P4 完善。
            r.infiniteResources = true;
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

            arc.util.Time.run(2f, () -> {
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

            StringBuilder placed = new StringBuilder("[");
            boolean firstPlaced = true;
            java.util.List<int[]> takenSpots = new java.util.ArrayList<>();

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

                    // 地图已有核心，只需补一个建造单位
                    int[] unitSpot = wantUnits ? spawnBuilder(t, a.id, takenSpots, log) : null;

                    log.append("bind[").append(a.id).append("]->").append(t.name);
                    if (unitSpot != null) {
                        log.append("@").append(unitSpot[0]).append(",").append(unitSpot[1]);
                    }
                    log.append("; ");

                    if (!firstPlaced) placed.append(',');
                    firstPlaced = false;

                    var core = t.core();
                    Json.Obj o = new Json.Obj()
                        .put("agent", a.id).put("team", t.id)
                        .put("teamName", t.name)
                        .put("coreSource", "map");
                    if (core != null) o.put("coreX", core.tileX()).put("coreY", core.tileY());
                    if (unitSpot != null) o.put("unitX", unitSpot[0]).put("unitY", unitSpot[1]);
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

                int[] spot = findCoreSpot(coreBlock, t);
                if (spot == null) {
                    log.append("no core spot for ").append(a.id).append("; ");
                    continue;
                }

                // 先铺 coreZone 地板 —— 这是核心能通过 validPlace 的前提。
                // 否则 BuildVisibility.coreZoneOnly.visible() 为 false，
                // Block.isHidden() 返回 true，validPlace 从第一个检查就失败。
                layCoreZone(spot[0], spot[1], coreBlock.size);

                Tile tile = Vars.world.tile(spot[0], spot[1]);
                if (!mindustry.world.Build.validPlace(coreBlock, t, spot[0], spot[1], 0)) {
                    // 逐项拆解 validPlace 的后续检查，定位到底卡在哪一步
                    boolean canPlaceOn = coreBlock.canPlaceOn(tile, t, 0);
                    boolean noOverlap = mindustry.world.Build.checkNoUnitOverlap(coreBlock, spot[0], spot[1]);
                    boolean ignoreUnits = mindustry.world.Build.validPlaceIgnoreUnits(
                        coreBlock, t, spot[0], spot[1], 0, true, true);

                    log.append("validPlace=false after coreZone for ").append(a.id)
                       .append("{canPlaceOn=").append(canPlaceOn)
                       .append(",noUnitOverlap=").append(noOverlap)
                       .append(",ignoreUnits=").append(ignoreUnits)
                       .append(",floor=").append(tile == null ? "null" : tile.floor().name)
                       .append(",allowCore=").append(tile == null ? "?" : tile.floor().allowCorePlacement)
                       .append(",existingBlock=").append(tile == null ? "?" : tile.block().name)
                       .append(",polyProtect=").append(r.polygonCoreProtection)
                       .append("}; ");
                    continue;
                }
                tile.setBlock(coreBlock, t, 0);
                log.append("core[").append(a.id).append("]@")
                   .append(spot[0]).append(",").append(spot[1]).append("; ");

                if (!firstPlaced) placed.append(',');
                firstPlaced = false;
                placed.append(new Json.Obj()
                    .put("agent", a.id).put("team", t.id)
                    .put("coreX", spot[0]).put("coreY", spot[1]).toString());

                // ---- 5. 生成建造单位 ----
                if (wantUnits) {
                    mindustry.type.UnitType ut = pickBuilderUnit();
                    if (ut != null) {
                        mindustry.gen.Unit u = ut.create(t);
                        u.set(spot[0] * Vars.tilesize + Vars.tilesize / 2f,
                              spot[1] * Vars.tilesize + Vars.tilesize / 2f);
                        u.add();
                        log.append("unit[").append(a.id).append("]=").append(ut.name).append("; ");
                    }
                }
            }
            placed.append(']');

            // 恢复 editor 与 staticFog 状态
            r.editor = prevEditor;
            r.staticFog = prevStaticFog;

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
            });

          } catch (Throwable t) {
            AIArena.log("setup phase1 failed: " + t);
            future.complete(Json.error(1500, "setup phase1: " + t));
          }
        });

        // HTTP 线程等待两阶段完成。setup 涉及换图与整帧调度，给足 8 秒。
        try {
            String json = future.get(8000, TimeUnit.MILLISECONDS);
            boolean isError = json != null && json.contains("\"ok\":false");
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

    private static int[] findCoreSpot(Block coreBlock, Team team) {
        int size = Math.max(1, coreBlock.size);
        int w = Vars.world.width(), h = Vars.world.height();
        int cx = w / 2, cy = h / 2;

        for (int radius = 0; radius < Math.max(w, h); radius += 3) {
            for (int dy = -radius; dy <= radius; dy += 3) {
                for (int dx = -radius; dx <= radius; dx += 3) {
                    int x = cx + dx, y = cy + dy;
                    if (isClearArea(x, y, size, w, h)) return new int[]{x, y};
                }
            }
        }
        for (int y = 2; y < h - size - 2; y++) {
            for (int x = 2; x < w - size - 2; x++) {
                if (isClearArea(x, y, size, w, h)) return new int[]{x, y};
            }
        }
        return null;
    }

    /**
     * 在指定区域铺 coreZone 地板。
     * 这是核心能够通过 validPlace 的前提，也是自制 PvP 地图必须做的事。
     */
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

    private static String visibleUnits(Snapshot.State s, int myTeam, boolean admin) {
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
            if (u.controllerId >= 0) o.put("controller", u.controllerId);
            if (!u.command.isEmpty()) o.put("command", u.command);
            sb.append(o.toString());
        }
        return sb.append(']').toString();
    }

    private static String visibleBuildings(Snapshot.State s, int myTeam, boolean admin) {
        Team team = Team.get(myTeam);
        StringBuilder sb = new StringBuilder("[");
        boolean first = true;
        for (Snapshot.BuildInfo b : s.builds) {
            if (b.team != myTeam && !admin) {
                if (!safeVisibleTile(team, b.x, b.y)) continue;
            }
            if (!first) sb.append(',');
            first = false;

            StringBuilder its = new StringBuilder("{");
            for (int i = 0; i < b.items.length; i++) {
                if (i > 0) its.append(',');
                its.append(Json.str(b.items[i])).append(':').append(b.itemAmounts[i]);
            }
            its.append('}');

            StringBuilder lqs = new StringBuilder("{");
            for (int i = 0; i < b.liquids.length; i++) {
                if (i > 0) lqs.append(',');
                lqs.append(Json.str(b.liquids[i])).append(':').append(b.liquidAmounts[i]);
            }
            lqs.append('}');

            Json.Obj o = new Json.Obj()
                .put("x", b.x).put("y", b.y).put("team", b.team).put("block", b.block)
                .put("health", b.health).put("maxHealth", b.maxHealth)
                .put("enabled", b.enabled).put("efficiency", b.efficiency)
                .putRaw("items", its.toString())
                .putRaw("liquids", lqs.toString());
            if (b.config != null) o.put("config", b.config);
            if (b.constructing) o.put("constructing", true).put("buildProgress", b.buildProgress);
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
    private static void postToGame(HttpExchange ex, GameTask task) {
        CompletableFuture<String> future = new CompletableFuture<>();

        Core.app.post(() -> {
            try { future.complete(task.run()); }
            catch (Throwable t) { future.complete(Json.error(1500, String.valueOf(t))); }
        });

        try {
            String json = future.get(POST_TIMEOUT_MS, TimeUnit.MILLISECONDS);
            boolean isError = json != null && json.contains("\"ok\":false");
            respond(ex, isError ? statusFor(json) : 200, json);
        } catch (java.util.concurrent.TimeoutException te) {
            respond(ex, 504, Json.error(1007, "game thread did not respond within "
                + POST_TIMEOUT_MS + " ms (op_expired)"));
        } catch (Throwable t) {
            respond(ex, 500, Json.error(1500, String.valueOf(t)));
        }
    }

    /** 从错误码推 HTTP 状态，便于 AI 侧按状态码分流。 */
    private static int statusFor(String json) {
        if (json.contains("\"code\":1001")) return 400;
        if (json.contains("\"code\":1002")) return 404;
        if (json.contains("\"code\":1003")) return 400;
        if (json.contains("\"code\":1004")) return 429;
        if (json.contains("\"code\":1005")) return 403;
        if (json.contains("\"code\":1006")) return 410;
        if (json.contains("\"code\":1007")) return 504;
        return 400;
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
