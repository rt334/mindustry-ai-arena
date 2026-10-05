package aiarena;

import arc.ApplicationListener;
import arc.Core;
import mindustry.game.Team;
import mindustry.gen.Player;
import mindustry.mod.Mod;

/**
 * AI 竞技场 · 服务器 Mod 入口。
 *
 * 启动顺序：
 *   1. 读取/生成配置（config/ai-arena.json）
 *   2. 挂载引擎事件监听器（事件流）
 *   3. 把连入的玩家接管成观战者
 *   4. 注册观战指令 /arena-view
 *   5. 注册主线程监听器 —— 每帧刷新只读快照
 *   6. 启动 HTTP 服务端
 *
 * 快照刷新放在 ApplicationListener.update() 里，确保它跑在游戏主线程上；
 * HTTP 线程只读取 Snapshot 替换出来的不可变对象，不触碰世界。
 */
public class AIArenaMod extends Mod {

    @Override
    public void init() {
        AIArena.log("init, headless=" + mindustry.Vars.headless);

        AIArena.load();

        EventLog.install();

        // 玩家一加入就接管成观战者。
        //
        // 时机是硬性的：引擎在 PlayerJoin 之后立刻执行
        //     player.deathTimer = Player.deathDelay;
        //     player.update();
        // 那一次 update 就会走 PlayerComp 的自动生成逻辑，把初始单位发出来。
        // 所以必须在 PlayerJoin 的当下就把 spectator 置上 —— 置上之后
        // PlayerComp.update() 直接返回，既不生成初始单位，也永远不会重生。
        if (AIArena.AUTO_SPECTATE) {
            arc.Events.on(mindustry.game.EventType.PlayerJoin.class, e -> {
                if (e.player == null) return;
                boolean ok = AIArena.makeObserver(e.player, AIArena.DEFAULT_VIEW);
                AIArena.log("auto-spectate " + e.player.name
                            + " -> " + (ok ? "ok" : "FAILED")
                            + " team=" + e.player.team().name
                            + " view=" + (AIArena.DEFAULT_VIEW < 0 ? "all" : String.valueOf(AIArena.DEFAULT_VIEW)));
            });
        }


        // 连接生命周期诊断：把 join/leave 和**断开原因**记下来。
        // 反复出现 timeout/error 而不是 closed，就能确定是网络层在拦包 ——
        // 这是这一轮里最难查的一个现象（客户端每隔一两分钟断一次，
        // 每次重连都会重置视角并重载世界，看起来像「切队跳回 / 建筑要等加载」）。
        arc.Events.on(mindustry.game.EventType.PlayerJoin.class, e -> Diag.join(e.player));

        AIArena.installDisconnectDiag();
        registerViewCommand();
        registerViewTeamProvider();

        Core.app.addListener(new ApplicationListener() {
            @Override
            public void update() {
                Snapshot.update();
                // 视野进出追踪：让 AI 能知道「有单位进入了我的视线」，
                // 而不是每拍拉列表自己 diff（那样会漏掉一闪而过的单位）
                VisionTracker.update();
                AIArena.fogRepushTick();
                RateTracker.update();
                StallWatch.update();
                StallWatch.updatePlans();
                Commander.tickMoveOrders();
                ensureAgentPlayersPeriodically();
                // WS 推送必须在主线程：channelJson 会读 Vars.state / Groups
                WsServer.tick();
            }
        });

        HttpApi.start();
        // WebSocket 用独立端口（HTTP 端口 + 1）。
        // JDK 的 HttpServer 不支持连接劫持，做不了 Upgrade，只能另开裸 socket。
        WsServer.start(AIArena.port + 1, AIArena.port);

        AIArena.log("ready");
    }

    /**
     * AI 玩家看门狗。
     *
     * 引擎里有些操作会清空 Groups.player（实测 host 开端口之后玩家就没了，
     * 而且清理是**异步**发生的 —— 同步补建会输给那个延迟任务）。玩家一没，
     * 就没有 PlayerComp 去 requestSpawn，整局一个单位都不会有，AI 完全不动。
     *
     * 与其去追每一个清空点，不如每 0.5 秒检查一遍：谁缺就补谁。
     * 只补缺、不重建，所以不会打断正在进行的对局。
     */
    private static long lastAgentCheck = 0;

    private static void ensureAgentPlayersPeriodically() {
        try {
            if (mindustry.Vars.state == null) return;
            if (arc.util.Time.timeSinceMillis(lastAgentCheck) < 500) return;
            lastAgentCheck = arc.util.Time.millis();

            StringBuilder sb = new StringBuilder();
            int n = HttpApi.ensureAgentPlayers(sb);
            if (n > 0) AIArena.log("watchdog re-created " + n + " AI player(s)");
        } catch (Throwable t) {
            AIArena.log("agent watchdog failed: " + t);
        }
    }

    /**
     * 注册观战视角的「快照路由」回调。
     *
     * ⚠ 这个注册一直缺失，是「UDP 快照超时」的根因。
     *
     * `NetServer.sync()` 在 `rules.fog` 下的观战路由是这样：
     *
     * ```java
     * for(Player p : Groups.player){
     *     Team view = viewTeamFor(p);                       // ← 我们没注册，恒为 null
     *     boolean full = view == null && isFullView(p);     // ← isFullView 要求 team == derelict
     *     if(view == null && !full) continue;               // ← 于是被静默跳过，一个快照都不发
     *     ...
     * }
     * ```
     *
     * 后果：观战者只要把 team 从 derelict 切到某个真实队伍（`/arena-view <id>`），
     * 就既不满足 viewTeamFor 也 不满足 isFullView —— 服务端完全停止给他发实体快照，
     * 客户端 20 秒后（`NetClient.entitySnapshotTimeout`）报
     * "Timed out after not received UDP snapshots." 并断开。
     *
     * 表现就是「视角每轮转到一个真实队伍就断一次」。
     *
     * 修法就是把这个接口实现掉：绑定了真实队伍就按那个队的视角发。
     * 返回 null 表示「无特殊视角」，保持引擎默认行为。
     */
    private void registerViewTeamProvider() {
        try {
            mindustry.core.NetServer.viewTeamProvider = player -> {
                if (player == null || !player.spectator) return null;
                mindustry.game.Team t = player.team();
                // derelict = 全图视角，交给 isFullView 走全量分支
                if (t == null || t == mindustry.game.Team.derelict) return null;
                return t;
            };
            AIArena.log("viewTeamProvider registered");
        } catch (Throwable t) {
            AIArena.log("registerViewTeamProvider failed: " + t);
        }
    }

    /**
     * 观战视角指令。
     *
     * 为什么走指令而不是让客户端直接改本地队伍：客户端本地改队只能骗过渲染，
     * 服务端仍然按旧队伍给他发实体 —— 结果就是「迷雾变了但看不到人」。
     * 视角是服务端的事，必须让服务端改并重发世界数据。
     *
     *   /arena-view all      全图裁判视角
     *   /arena-view next     切到下一个有核心的队伍
     *   /arena-view <id>     切到指定队伍
     *   /arena-view off      退出观战（变回普通玩家）
     */
    private void registerViewCommand() {
        try {
            mindustry.Vars.netServer.clientCommands.<Player>register(
                "arena-view", "<all|next|off|teamId>", "切换观战视角（仅观战者）",
                (args, player) -> {
                    if (player == null) return;

                    if (!player.spectator) {
                        player.sendMessage("[scarlet]你不是观战者，无法切换视角。");
                        return;
                    }

                    String a = args[0].trim();

                    if (a.equalsIgnoreCase("off")) {
                        AIArena.clearObserver(player);
                        player.sendMessage("[accent]已退出观战模式。");
                        return;
                    }

                    if (a.equalsIgnoreCase("all")) {
                        AIArena.setViewTeam(player, -1);
                        player.sendMessage("[accent]视角: [white]全图（裁判）");
                        return;
                    }

                    int target;
                    if (a.equalsIgnoreCase("next")) {
                        target = nextViewTeam(player);
                        if (target == Integer.MIN_VALUE) {
                            player.sendMessage("[scarlet]没有找到有核心的队伍。");
                            return;
                        }
                    } else {
                        try {
                            target = Integer.parseInt(a);
                        } catch (NumberFormatException nfe) {
                            player.sendMessage("[scarlet]参数无效，用法: /arena-view all|next|off|<队伍id>");
                            return;
                        }
                        if (target < 0 || target >= Team.all.length) {
                            player.sendMessage("[scarlet]队伍 id 超出范围: " + target);
                            return;
                        }
                    }

                    AIArena.setViewTeam(player, target);
                    player.sendMessage("[accent]视角: [white]" + Team.get(target).name);
                });
            AIArena.log("registered /arena-view");
        } catch (Throwable t) {
            AIArena.log("registerViewCommand failed: " + t);
        }
    }

    /** 当前视角的下一个有核心的队伍。返回 Integer.MIN_VALUE 表示没有。 */
    private static int nextViewTeam(Player player) {
        try {
            arc.struct.IntSeq ids = new arc.struct.IntSeq();
            for (var td : mindustry.Vars.state.teams.present) {
                if (td.cores.size > 0) ids.add(td.team.id);
            }
            if (ids.isEmpty()) return Integer.MIN_VALUE;
            ids.sort();

            int current = AIArena.viewTeamOf(player);
            // 全图视角（-1）从第一个队伍开始
            if (current < 0) return ids.first();

            for (int i = 0; i < ids.size; i++) {
                if (ids.get(i) == current) {
                    return ids.get((i + 1) % ids.size);
                }
            }
            return ids.first();
        } catch (Throwable t) {
            return Integer.MIN_VALUE;
        }
    }
}
