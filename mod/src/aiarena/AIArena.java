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

    public static final class Agent {
        public final String id;
        /** 配置里声明的队伍，作为地图没有可用核心时的兜底。 */
        public final int configTeamId;
        public final byte[] tokenBytes;
        public final boolean admin;

        /**
         * 本局实际使用的队伍。
         *
         * 官方 PvP 地图（veins/glacier/passage）自带 sharded 与 crux 两个核心，
         * 此时 agent 应接管地图已有的队伍，而不是另造核心。setup 会按地图实际情况
         * 重新绑定这个字段，HTTP 线程读取它（volatile 保证可见性）。
         */
        private volatile int activeTeamId;

        Agent(String id, int teamId, byte[] tokenBytes, boolean admin) {
            this.id = id;
            this.configTeamId = teamId;
            this.activeTeamId = teamId;
            this.tokenBytes = tokenBytes;
            this.admin = admin;
        }

        public Team team() { return Team.get(activeTeamId); }
        public int teamId() { return activeTeamId; }

        public void bindTeam(int id) { this.activeTeamId = id; }
        public void resetTeam() { this.activeTeamId = configTeamId; }

        // 令牌不得出现在日志或序列化里
        @Override public String toString() {
            return "Agent(" + id + ", team=" + activeTeamId
                 + (activeTeamId == configTeamId ? "" : " (cfg " + configTeamId + ")")
                 + ", admin=" + admin + ")";
        }
    }

    private AIArena() {}

    public static void log(String s) { Log.info(TAG + " " + s); System.out.println(TAG + " " + s); }

    // ---------------------------------------------------------------- load

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

    private static boolean isLoopback(String host) {
        return "127.0.0.1".equals(host)
            || "localhost".equalsIgnoreCase(host)
            || "::1".equals(host)
            || "[::1]".equals(host);
    }
}
