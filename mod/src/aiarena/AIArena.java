package aiarena;

import arc.Core;
import arc.files.Fi;
import arc.struct.Seq;
import arc.util.Log;
import arc.util.serialization.Jval;
import mindustry.game.Team;

import java.security.MessageDigest;
import java.security.SecureRandom;

/**
 * 配置与鉴权。
 *
 * 配置形状（config/ai-arena.json）：
 * {
 *   "bind": "127.0.0.1",
 *   "port": 7199,
 *   "rateLimit": { "perSecond": 60, "burst": 200 },
 *   "agents": [
 *     { "id": "alpha", "team": 100, "token": "<48 hex chars>", "admin": false },
 *     ...
 *   ]
 * }
 *
 * 安全约定：
 *  - token 缺失时自动生成并写回配置文件（不硬编码默认值）
 *  - token 比较使用 MessageDigest.isEqual（恒定时间），避免时序侧信道
 *  - bind 只接受回环地址；配置写成其它地址会被拒绝并降级为 127.0.0.1
 */
public final class AIArena {

    private static final String TAG = "[AIARENA]";
    private static final String CONFIG_NAME = "ai-arena.json";

    public static String bind = "127.0.0.1";
    public static int port = 7199;

    /**
     * 接口版本号。**跨版本的对局成绩不可比** —— 成绩记录必须带上它。
     *
     * 约定（详见 docs/API.md）：
     *   major  +1  破坏性：删字段、改字段语义、改默认行为
     *   minor  +1  增量：只加字段 / 只加端点，老客户端仍然能用
     *
     * 之所以要它：这个接口改过不少次（`stuckReason`、批量的 requested/accepted、
     * `/queue` 的 cleared、`/drill` 的 itemsPerSecond、SSE、蓝图……），
     * 而 `reviews/` 里几批数据是不同时期跑的。没有版本号，
     * 「这局 AI 是 3.2/s 那局 AI 是 2.1/s」根本说不清是不是同一个接口。
     */
    public static final String API_VERSION = "1.4";
    public static int ratePerSecond = 60;
    public static int rateBurst = 200;

    /**
     * HTTP 工作线程数。
     *
     * 默认 4 在多 AI 并发轮询时会成为瓶颈 —— 实测 12 个并发客户端下
     * 约 1.25% 的请求失败（线程池排队导致连接被拒）。
     * 现在默认 16，并可通过配置调整。
     */
    public static int httpThreads = 16;

    /** HttpServer 的 accept backlog。0 表示用系统默认。 */
    public static int httpBacklog = 128;

    /**
     * 已配置的 agent。
     *
     * ⚠ 必须是线程安全容器。这个列表会被 HTTP 线程高频遍历（每个请求都要过
     * authenticate），而 arc 的 Seq 迭代器在多线程并发遍历时会互相踩状态，
     * 抛 NoSuchElementException（实测 24 并发下约 3% 的请求失败）。
     *
     * agents 只在启动时写入一次，之后纯读 —— CopyOnWriteArrayList 的读路径
     * 完全无锁，正好匹配这个访问模式。
     */
    public static final java.util.List<Agent> agents = new java.util.concurrent.CopyOnWriteArrayList<>();

    /**
     * 观战者 UUID。
     *
     * 「观战者」在引擎里由 PlayerComp.spectator 定义，含义只有一条：
     * **永远不生成单位**（既没有初始单位，死后也不会重生）。这条是硬需求 ——
     * 观战者一旦有单位，就能采矿、建造、指挥，等于插手对局。
     *
     * 视角则由队伍决定，而且完全是**每客户端**的：
     *   队伍 = 某个真实队伍   → 引擎按那个队的视野给他同步实体、客户端渲染那个队的迷雾
     *   队伍 = derelict       → NetServer 判定为「全图视角」，发全部实体、客户端不画迷雾
     *
     * 关键在于**不动 state.rules.fog**。早期版本用关掉全局迷雾来实现裁判模式，
     * 结果所有玩家（包括 AI）都失去视野约束 —— 那是把「谁能看见」这个每客户端的
     * 问题当成了全局开关。
     */
    public static final java.util.Set<String> observers = java.util.concurrent.ConcurrentHashMap.newKeySet();

    /** 观战者当前视角：uuid -> 队伍 id。-1 表示全图（裁判视角）。 */
    private static final java.util.Map<String, Integer> viewTeams = new java.util.concurrent.ConcurrentHashMap<>();

    /** 是否自动把每个连入的玩家设为观战者。默认开，可用 -Darena.autospectate=false 关。 */
    public static final boolean AUTO_SPECTATE =
        !"false".equalsIgnoreCase(System.getProperty("arena.autospectate", "true"));

    /** 新观战者的默认视角。-1 = 裁判全图；也可以设成某个队伍 id。 */
    public static final int DEFAULT_VIEW = Integer.getInteger("arena.defaultview", -1);

    /**
     * 是否允许直接召唤单位。
     *
     * **默认关闭** —— 单位必须由工厂生产（air-factory / ground-factory /
     * naval-factory / 各类 fabricator）。这和其他 RTS 的规则一致：兵不是凭空出现的，
     * 要先有产能。
     *
     * 直接召唤绕过了整套经济与产能：没有建造时间、不需要电力、不需要工厂，
     * 于是「产能压制」这种维度根本不存在，对局退化成两个脚本对撞。
     *
     * 需要调试时用 -Darena.allowspawn=true 显式打开。
     */
    public static final boolean ALLOW_DIRECT_SPAWN =
        "true".equalsIgnoreCase(System.getProperty("arena.allowspawn", "false"));

    /**
     * 是否允许 /control?op=warp —— **直接改单位坐标**。
     *
     * 默认禁止。这是 P0 技术验证留下的调试探针（用来观察「服务器改世界之后
     * 位置会不会被引擎改回去」），但它同时是一条**瞬移后门**：
     *
     *   对等约束第 9 条是「移动速度 = 引擎行为」，人类玩家只能 WASD，
     *   而 warp 让 AI 一步跨到任意坐标 —— 走位、赶路、规避全都不再成立。
     *
     * 调试时用 -Darena.allowwarp=true 显式打开。
     */
    public static final boolean ALLOW_WARP =
        "true".equalsIgnoreCase(System.getProperty("arena.allowwarp", "false"));

    // ---------------------------------------------------------------- 限流

    /** 每 agent 的令牌桶。key = agent id。 */
    private static final java.util.Map<String, Bucket> buckets =
        new java.util.concurrent.ConcurrentHashMap<>();

    private static final class Bucket {
        double tokens;
        long lastMs;
        Bucket(double tokens, long now) { this.tokens = tokens; this.lastMs = now; }
    }

    /**
     * 令牌桶限流。超限返回 false（调用方回 429 + code 1429）。
     *
     * 动机：配置里的 rateLimit 以前是**死配置** —— 解析了却没人用，
     * 于是一个 agent 放开打就能占满 HTTP 线程池，把别的 agent 全堵住。
     *
     * 用同步块而不是无锁：只有 16 个 HTTP 线程会走到这，争用很低，
     * 而令牌桶的读改写必须原子。
     */
    public static boolean takeToken(Agent agent) {
        if (agent == null) return true;
        long now = System.currentTimeMillis();
        Bucket b = buckets.computeIfAbsent(agent.id, k -> new Bucket(rateBurst, now));
        synchronized (b) {
            double elapsed = (now - b.lastMs) / 1000.0;
            b.lastMs = now;
            b.tokens = Math.min(rateBurst, b.tokens + elapsed * ratePerSecond);
            if (b.tokens < 1.0) return false;
            b.tokens -= 1.0;
            return true;
        }
    }

    /** 观战者当前视角队伍 id；-1 表示全图。 */
    public static int viewTeamOf(mindustry.gen.Player pl) {
        if (pl == null) return -1;
        Integer v = viewTeams.get(pl.uuid());
        return v == null ? -1 : v;
    }

    /**
     * 把玩家设为观战者，并指定视角队伍。
     *
     * 必须在玩家加入的**那一刻**调用（PlayerJoin 事件里）：引擎在 PlayerJoin 之后
     * 会立刻 `player.deathTimer = deathDelay; player.update();`，那一次 update 就会
     * 把初始单位生成出来。晚一步就晚了。
     *
     * @param viewTeamId 视角队伍；-1 = 全图裁判视角
     */
    public static boolean makeObserver(mindustry.gen.Player pl, int viewTeamId) {
        if (pl == null) return false;
        try {
            pl.spectator = true;
            if (pl.unit() != null) pl.clearUnit();

            viewTeams.put(pl.uuid(), viewTeamId);
            Team t = viewTeamId < 0 ? Team.derelict : Team.get(viewTeamId);
            if (pl.team() != t) pl.team(t);

            try {
                mindustry.Vars.netServer.admins.adminPlayer(pl.getInfo().id, pl.usid());
            } catch (Throwable ignored) {}
            pl.admin = true;

            observers.add(pl.uuid());

            // 观战者服务端队伍固定 derelict：不属于任何队，永远不会被引擎发单位。
            // 世界数据里带的「我是哪个队」也就是 derelict，客户端据此走全图分支
            // （FogRenderer 对 derelict 取不到静态位图，本来就不画迷雾）。
            resendWorld(pl);
            return true;
        } catch (Throwable t) {
            log("makeObserver failed: " + t);
            return false;
        }
    }

    /**
     * 把本 mod 的视角提供器接到引擎上。
     *
     * NetServer 每帧按队序列化实体快照时会问这里：「这个连接该收哪个队的实体」。
     * 返回 null 表示按常规处理（用玩家自己的队伍）。
     */


    /** 重发世界数据，让客户端拿到最新的队伍 / 实体 / 迷雾状态。 */
    private static void resendWorld(mindustry.gen.Player pl) {
        try {
            if (pl.con != null && pl.con.hasConnected) {
                mindustry.Vars.netServer.sendWorldData(pl);
            }
        } catch (Throwable ignored) {}
    }

    /**
     * 切换观战视角。
     *
     * 服务端把观战者的**队伍**设成视角队伍，客户端跟着走 —— 不重发世界数据。
     *
     * 为什么这样能生效：观战者自己的 player 实体也在 Groups.sync 里，会随实体快照
     * 发给他，而 team 是同步字段。所以服务端改完队伍，客户端下一个快照就收到了。
     *
     * 早期版本是「客户端本地改队 + 服务端只记录」—— 两边互相打架：实体快照每帧把
     * team 写回 derelict，客户端每帧再改回去，结果就是画面持续闪动。让服务端做
     * 唯一的事实来源，就没有这个问题。
     *
     * 重发整个世界数据是更早的做法，那会让客户端 Groups.clear() 后重建整个世界，
     * 连按几次就把客户端淹没了（一串 "Received world data" 之后直接退出）。
     *
     * @param viewTeamId 视角队伍；-1 = 全图裁判视角（derelict）
     */
    public static boolean setViewTeam(mindustry.gen.Player pl, int viewTeamId) {
        if (pl == null || !pl.spectator) return false;
        try {
            viewTeams.put(pl.uuid(), viewTeamId);

            Team t = viewTeamId < 0 ? Team.derelict : Team.get(viewTeamId);
            if (t != null && pl.team() != t) pl.team(t);
            pl.clearUnit();

            // 立刻按新视角发一次快照。不等下一个 tick 的话，切视角后会有几秒
            // 只看到旧实体（表现是「建筑要加载后才被看到」）。
            try {
                if (mindustry.Vars.netServer != null) mindustry.Vars.netServer.forceSnapshot(pl);
            } catch (Throwable ignored) {}

            return true;
        } catch (Throwable t) {
            log("setViewTeam failed: " + t);
            return false;
        }
    }

    /** 取消观战，变回普通玩家。 */
    public static void clearObserver(mindustry.gen.Player pl) {
        if (pl == null) return;
        observers.remove(pl.uuid());
        viewTeams.remove(pl.uuid());
        pl.spectator = false;
    }

    /**
     * 把断开原因接到 Diag 上。
     *
     * PlayerLeave 事件不带原因，而原因恰恰是判断「该改游戏还是该改网络栈」的
     * 唯一依据：closed = 客户端正常关闭；timeout = 心跳超时（UDP 被拦或丢包）；
     * error = 底层读写错误。
     */
    public static void installDisconnectDiag() {
        try {
            mindustry.core.NetServer.disconnectListener = (pl, reason) -> Diag.leave(pl, reason);
            log("disconnect diagnostics installed");
        } catch (Throwable t) {
            log("installDisconnectDiag failed: " + t);
        }
    }

    public static final class Agent {
        public final String id;
        /** 配置里声明的队伍，作为地图没有可用核心时的兜底。 */
        public final int configTeamId;
        public final byte[] tokenBytes;
        /** 明文 token。WS 内部转发命令时要拼回 REST 请求头用。 */
        public final String token;
        public final boolean admin;

        /**
         * 本局实际使用的队伍。
         *
         * 官方 PvP 地图（veins/glacier/passage）自带 sharded 与 crux 两个核心，
         * 此时 agent 应接管地图已有的队伍，而不是另造核心。setup 会按地图实际情况
         * 重新绑定这个字段，HTTP 线程读取它（volatile 保证可见性）。
         */
        private volatile int activeTeamId;

        /**
         * 本局绑定的真实玩家实体。
         *
         * 为什么不用影子 Player：
         *   Mindustry 的 PlayerComp.update() 会自动给「没有单位的玩家」从核心
         *   生成初始单位（core.requestSpawn(self())）。所以只要 agent 对应一个
         *   真实的 Player 并加入队伍，引擎就会像对待真人玩家一样给它单位 ——
         *   不需要手动 spawn，也不该预置任何兵和建筑。
         *
         *   AI 的 HTTP 操作因此可以直接作用在这个玩家身上，与真人玩家走完全
         *   相同的代码路径。
         *
         * 由 setup 在主线程创建，HTTP 线程只读（volatile 保证可见性）。
         */
        private volatile mindustry.gen.Player player;

        Agent(String id, int teamId, byte[] tokenBytes, boolean admin) {
            this.id = id;
            this.configTeamId = teamId;
            this.activeTeamId = teamId;
            this.tokenBytes = tokenBytes;
            this.token = new String(tokenBytes, java.nio.charset.StandardCharsets.UTF_8);
            this.admin = admin;
        }

        public Team team() { return Team.get(activeTeamId); }
        public int teamId() { return activeTeamId; }

        public void bindTeam(int id) { this.activeTeamId = id; }
        public void resetTeam() { this.activeTeamId = configTeamId; }

        public mindustry.gen.Player player() { return player; }
        public void bindPlayer(mindustry.gen.Player p) { this.player = p; }

        /** 该 agent 当前控制的单位（没有则 null）。 */
        public mindustry.gen.Unit unit() {
            var p = player;
            return p == null ? null : p.unit();
        }

        // 令牌不得出现在日志或序列化里
        @Override public String toString() {
            return "Agent(" + id + ", team=" + activeTeamId
                 + (activeTeamId == configTeamId ? "" : " (cfg " + configTeamId + ")")
                 + ", admin=" + admin
                 + (player == null ? "" : ", player=" + player.name)
                 + ")";
        }
    }

    private AIArena() {}

    public static void log(String s) { Log.info(TAG + " " + s); System.out.println(TAG + " " + s); }

    // ---------------------------------------------------------------- load

    /**
     * 把建造单位的 buildRange 放大到覆盖整张地图。
     *
     * 为什么必须这么做：
     *
     *   `BuilderComp` **不含任何移动代码** —— 单位移动由它的**控制器**负责。
     *   正常游戏里那是玩家（按键）；竞技场里 gamma 被影子 AI 玩家持有
     *   （controller = Player#NNN），而影子玩家永远不发移动输入。
     *
     *   而 `UnitTypes.gamma.controller` 是
     *   `u -> u.team.isAI() ? new BuilderAI(true, 400f) : new CommandAI()` ——
     *   PvP 下 `Team.isAI()` 为 false，所以就算不被玩家持有也只会拿到
     *   CommandAI，那个同样不建造、不寻路。
     *
     *   雪上加霜的是单位**出生在核心正中心**（spawnedByCore），而核心是
     *   solid 方块；`ElevationMoveComp.solidity()` 在不飞时返回
    /**
     * 把建造单位的 buildRange 放大到覆盖整张地图。
     *
     * ⚠ **已停用** —— YG 明确要求不许改 buildRange。保留代码仅作记录，
     * 真正走的是引擎侧 `BuilderComp` 的直接位移补丁。
     */
    public static void widenBuilderRange() {
        try {
            float range = 4000f;
            for (mindustry.type.UnitType t : mindustry.Vars.content.units()) {
                if (t != null && t.buildSpeed > 0f) {
                    t.buildRange = range;
                }
            }
            log("builder buildRange widened to " + (int) range + "px");
        } catch (Throwable e) {
            log("widenBuilderRange failed: " + e);
        }
    }

    public static void load() {
        Fi dir = Core.settings.getDataDirectory();
        Fi file = dir.child(CONFIG_NAME);

        if (!file.exists()) {
            log("config not found, creating default at " + file.absolutePath());
            writeDefault(file);
        }

        try {
            // 剥离 UTF-8 BOM。外部工具（尤其是 PowerShell 的 Set-Content -Encoding UTF8）
            // 写出的 JSON 常带 BOM，而 Jval 遇到 BOM 会解析失败 —— 表现为
            // 配置文件里明明有 agent，Mod 却一个都读不到（全部 token 变空）。
            String raw = file.readString("UTF-8");
            if (raw != null && !raw.isEmpty() && raw.charAt(0) == '\uFEFF') {
                raw = raw.substring(1);
            }
            Jval root = Jval.read(raw);

            String b = root.getString("bind", "127.0.0.1");
            if (!isLoopback(b)) {
                log("WARNING: bind=" + b + " is not a loopback address; forcing 127.0.0.1");
                b = "127.0.0.1";
            }
            bind = b;
            port = root.getInt("port", 7199);

            Jval rl = root.get("rateLimit");
            if (rl != null) {
                ratePerSecond = rl.getInt("perSecond", 60);
                rateBurst      = rl.getInt("burst", 200);
            }

            Jval http = root.get("http");
            if (http != null) {
                httpThreads = Math.max(2, http.getInt("threads", 16));
                httpBacklog = Math.max(0, http.getInt("backlog", 128));
            }

            agents.clear();
            Jval arr = root.get("agents");
            if (arr != null && arr.isArray()) {
                for (Jval a : arr.asArray()) {
                    String id = a.getString("id", null);
                    if (id == null || id.isEmpty()) { log("skip agent without id"); continue; }
                    int team = a.getInt("team", -1);
                    if (team < 0 || team >= Team.all.length) { log("skip agent " + id + ": bad team " + team); continue; }
                    String tok = a.getString("token", null);
                    if (tok == null || tok.length() < 16) {
                        log("skip agent " + id + ": token missing or too short");
                        continue;
                    }
                    boolean admin = a.getBool("admin", false);
                    agents.add(new Agent(id, team, tok.getBytes("UTF-8"), admin));
                }
            }

            log("loaded " + agents.size() + " agent(s), bind=" + bind + ":" + port);
        Audit.init();
        writeDiscoveryFiles();
            for (Agent a : agents) log("   " + a);
        } catch (Throwable t) {
            log("config load FAILED: " + t);
            t.printStackTrace();
        }

        if (agents.isEmpty()) {
            log("WARNING: no agents configured — all authenticated endpoints will return 401");
        }
    }

    private static void writeDefault(Fi file) {
        String token = randomToken();
        String cfg = "{\n"
            + "  \"bind\": \"127.0.0.1\",\n"
            + "  \"port\": 7199,\n"
            + "  \"rateLimit\": { \"perSecond\": 60, \"burst\": 200 },\n"
            + "  \"agents\": [\n"
            + "    { \"id\": \"alpha\", \"team\": 100, \"token\": \"" + token + "\", \"admin\": false },\n"
            + "    { \"id\": \"beta\",  \"team\": 101, \"token\": \"" + randomToken() + "\", \"admin\": false },\n"
            + "    { \"id\": \"referee\", \"team\": 0, \"token\": \"" + randomToken() + "\", \"admin\": true }\n"
            + "  ]\n"
            + "}\n";
        try {
            file.writeString(cfg, false, "UTF-8");
            log("generated tokens for 3 agents (see " + file.absolutePath() + ")");
        } catch (Throwable t) {
            log("failed to write default config: " + t);
        }
    }

    public static String randomToken() {
        byte[] b = new byte[24];
        new SecureRandom().nextBytes(b);
        StringBuilder sb = new StringBuilder(48);
        for (byte x : b) sb.append(String.format("%02x", x));
        return sb.toString();
    }

    // ---------------------------------------------------------------- auth

    /**
     * 校验 Bearer token 并返回对应 agent。
     * @return 匹配的 agent，或 null（调用方须回 401）
     */
    public static Agent authenticate(String authorizationHeader) {
        if (authorizationHeader == null) return null;

        String prefix = "Bearer ";
        if (!authorizationHeader.startsWith(prefix)) return null;

        byte[] presented = authorizationHeader.substring(prefix.length()).trim()
                               .getBytes(java.nio.charset.StandardCharsets.UTF_8);
        Agent found = null;

        // 遍历全部 agent 且不做提前退出，避免通过响应时间泄露匹配位置
        for (Agent a : agents) {
            if (MessageDigest.isEqual(a.tokenBytes, presented)) found = a;
        }
        return found;
    }

    /**
     * 按明文 token 找 agent。WebSocket 握手用 —— 浏览器没法给 WS 握手设
     * 自定义头，所以 token 只能走 query string，这里收的是已经解出来的明文。
     */
    public static Agent agentByToken(String token) {
        if (token == null) return null;
        byte[] presented = token.trim().getBytes(java.nio.charset.StandardCharsets.UTF_8);
        Agent found = null;
        for (Agent a : agents) {
            if (MessageDigest.isEqual(a.tokenBytes, presented)) found = a;
        }
        return found;
    }

    /**
     * 迷雾补推的时间窗（毫秒时间戳）。setup 结束时置为「现在 + 20 秒」。
     *
     * 为什么需要：setup 为了绕开 validPlace 的「该格必须已探索」死循环，
     * 会在放置核心期间临时把 rules.staticFog 关掉。而 FogControl 的
     * TileChangeEvent 处理器里有一道 if(state.rules.staticFog) 的门，
     * 于是新核心的迷雾事件全被静默丢弃，staticData 永远是全零位图 ——
     * 客户端切到这一队就是整屏全黑（UI 却完全正常，极易误判成相机问题）。
     *
     * 恢复 staticFog 之后要补推，但**不能只推一次**：核心放进世界后要过一会儿
     * 才真正出现在 Groups.build 里（实测就地推和 30 帧后推都只数到地图自带的
     * 2 个核心）。forceUpdate 是幂等的，所以挂一个时间窗反复补最稳。
     */
    public static volatile long FOG_REPUSH_UNTIL = 0L;
    private static long lastRepushLog = 0L;

    /**
     * 迷雾补推节流。
     *
     * 补推窗口是 setup 后 20 秒。原先在这 20 秒里**每帧**跑（1200 次），
     * 每次遍历所有队伍的所有建筑并逐个 forceUpdate。建筑不会移动、
     * 迷雾半径也不变，60 Hz 的重复推送纯属浪费。10 Hz 效果完全相同。
     */
    private static double lastFogRepushTick = -1;
    private static final double FOG_REPUSH_INTERVAL_TICKS = 6;   // ≈10 Hz @ 60 FPS

    /** 由主线程逐帧调用（内部节流到 10 Hz）：在时间窗内补推迷雾事件。 */
    public static void fogRepushTick() {
        if (FOG_REPUSH_UNTIL <= 0L) return;
        if (arc.util.Time.millis() > FOG_REPUSH_UNTIL) { FOG_REPUSH_UNTIL = 0L; return; }
        try {
            if (mindustry.Vars.state == null || !mindustry.Vars.state.isGame()) return;
            if (!mindustry.Vars.state.rules.fog || !mindustry.Vars.state.rules.staticFog) return;

            double tickNow = mindustry.Vars.state.tick;
            if (lastFogRepushTick >= 0 && tickNow - lastFogRepushTick < FOG_REPUSH_INTERVAL_TICKS) return;
            lastFogRepushTick = tickNow;

            int seen = 0, pushed = 0;
            StringBuilder detail = new StringBuilder();
            for (var td : mindustry.Vars.state.teams.present) {
                if (td.team == null || td.team == mindustry.game.Team.derelict) continue;
                for (mindustry.gen.Building b : td.buildings) {
                    // ⚠ 这里**不能**检查 b.isAdded()。
                    //
                    // setup 里用 tile.setBlock() 现建的核心会进 TeamData.buildings，
                    // 但 isAdded() 是 false —— 它没被真正加进实体组，这也正是
                    // Groups.build.size() 只有 2（地图自带那两个）的原因。
                    // 加了这个检查就会把 102/103 的核心全部跳过，迷雾永远补不上。
                    // forceUpdate 只需要 tile 坐标和 fogRadius，不依赖实体组。
                    if (b == null) continue;
                    seen++;
                    if (!b.block.flags.contains(mindustry.world.meta.BlockFlag.hasFogRadius)) continue;
                    mindustry.Vars.fogControl.forceUpdate(td.team, b);
                    pushed++;
                    detail.append(b.block.name).append('/').append(td.team.name).append(' ');
                }
            }
            if (arc.util.Time.timeSinceMillis(lastRepushLog) > 3000) {
                lastRepushLog = arc.util.Time.millis();
                log("fogRepushTick: builds=" + seen + " pushed=" + pushed + " -> " + detail);
            }
        } catch (Throwable t) {
            log("fogRepushTick failed: " + t);
        }
    }

    private static boolean isLoopback(String host) {
        return "127.0.0.1".equals(host)
            || "localhost".equalsIgnoreCase(host)
            || "::1".equals(host)
            || "[::1]".equals(host);
    }

    /**
     * 端口发现文件 —— DESIGN.md 704-715 要求 `bridge-<agentId>.json`。
     *
     * 此前零实现，而且 DESIGN.md 里写死的 `port: 7199` 与可配置端口冲突：
     * 改了配置之后别人还得去读配置才知道连哪。这个文件就是「实际在哪个端口」
     * 的唯一答案。
     *
     * **不写 token** —— 它只解决「连哪」，不解决「以谁的身份」。
     * 把凭据塞进固定路径的文件里，等于把钥匙放在门口垫子下。
     */
    private static void writeDiscoveryFiles() {
        try {
            for (Agent ag : agents) {
                String base = "http://" + bind + ":" + port + "/v1/" + ag.id;
                String json = new Json.Obj()
                    .put("agent", ag.id)
                    .put("apiVersion", API_VERSION)
                    .put("httpPort", port)
                    .put("httpBase", base)
                    .toString();
                Core.files.local("bridge-" + ag.id + ".json").writeString(json);
            }
            log("wrote " + agents.size() + " discovery file(s): bridge-<agent>.json");
        } catch (Throwable t) {
            log("discovery files failed: " + t);
        }
    }
}
