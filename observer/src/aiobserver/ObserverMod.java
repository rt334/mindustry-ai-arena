package aiobserver;

import arc.Core;
import arc.Events;
import arc.Input;
import arc.input.KeyCode;
import arc.math.geom.Vec2;
import arc.scene.ui.Label;
import arc.scene.ui.layout.Table;
import arc.util.Time;
import mindustry.Vars;
import mindustry.game.EventType;
import mindustry.gen.Call;
import mindustry.gen.Groups;
import mindustry.gen.Unit;
import mindustry.mod.Mod;
import mindustry.ui.Styles;

/**
 * AI 竞技场 · 观战端。
 *
 * 设计目标：人能看直播，且**完全不干扰对局**。
 *
 * ── 视角是服务端的事，客户端只负责渲染 ──
 *
 * 服务端把观战者标成 spectator（永不生成单位）并给他一个「视角队伍」：
 *
 *   视角 = 真实队伍   服务端按那个队的视野同步实体，客户端画那个队的迷雾
 *   视角 = derelict   服务端发全部实体（全图裁判），客户端不画迷雾
 *
 * 所以切视角必须走服务端 —— 客户端本地改 player.team() 只能骗过渲染，
 * 服务端仍然按旧队伍发实体，结果就是「迷雾变了但看不到人」。
 * 这里通过 /arena-view 指令把意图交给服务端，服务端改完会重发世界数据。
 *
 * ── 客户端必须自己做的三件事 ──
 *
 * 1. 本地 spectator 标志
 *    PlayerComp.update() 在客户端也会跑。若本地 spectator 为 false，
 *    而视角队伍又恰好有核心，客户端就会调 core.requestSpawn()，
 *    那是个 @Remote 方法 —— 会真的往服务端发一个生成请求。
 *
 * 2. 全图视角不画迷雾
 *    迷雾渲染由 state.rules.fog 控制（Renderer → FogRenderer.drawFog）。
 *    服务端为了 AI 的视野约束必须保持 fog=true，所以裁判全图只能在客户端
 *    本地把这一份 rules 副本关掉。它只影响本机渲染，不会发回服务端。
 *
 * 3. 相机每帧强行覆写
 *    引擎在 DesktopInput 里每帧把相机 lerp 到玩家单位
 *    （Core.camera.position.lerpDelta(panTarget, ...)）。这里维护独立的
 *    camPos，在引擎更新之后再覆写，把 lerp 压掉。
 *
 * 操作：
 *   WASD / 方向键   平移
 *   中键拖拽         平移
 *   滚轮             缩放
 *   Tab              切到下一个有核心的队伍（会通知服务端）
 *   G                全图裁判视角
 *   F1               显示/隐藏帮助
 */
public class ObserverMod extends Mod {

    private static final float PAN_SPEED = 12f;      // 格/秒

    /** 自动连接地址。Mindustry 客户端没有 -connect 参数，只能由 Mod 自己连。 */
    private static final String AUTO_HOST = System.getProperty("arena.host", "127.0.0.1");
    private static final int    AUTO_PORT = Integer.getInteger("arena.port", 6567);
    private static final boolean AUTO_CONNECT =
        !"false".equalsIgnoreCase(System.getProperty("arena.autoconnect", "true"));

    private boolean enabled = true;
    private boolean freeCamera = true;
    private Label statusLabel;
    private Table helpTable;
    private boolean helpVisible = true;

    private float lastDragX, lastDragY;
    private boolean dragging = false;

    /** 我们自己的相机位置。引擎会往玩家单位 lerp，这里每帧把它拽回来。 */
    private final Vec2 camPos = new Vec2();

    /** 本机是不是观战端。连上服务器后由自己认定。 */
    private boolean spectator = false;

    /** 由 watchdog 线程置位、主线程消费的重连请求。 */
    private volatile boolean reconnectRequested = false;

    /** 上次记录过的视角队伍名，用于只在变化时打日志。 */
    private String lastLoggedTeam = "";

    /** 上次切换视角的时间，用于限流。 */
    private long lastViewChange = 0;

    /**
     * 期望的视角队伍 id；-1 表示全图裁判视角。
     *
     * 必须在每帧重申（见 maintainSpectatorState），不能只在按键时设一次：
     * 服务端会把观战者自己的 player 实体（team = derelict）随实体快照发过来，
     * 客户端 readSyncEntity 会把它写进 Vars.player，把刚设好的视角队伍覆盖掉。
     */
    private volatile int desiredViewTeam = -1;

    /** 上次周期性状态日志的时间。 */
    private long lastStatusLog = 0;

    /** 上次绘制期诊断的时间。 */
    private long lastDrawDiag = 0;

    @Override
    public void init() {
        Events.on(EventType.ClientLoadEvent.class, e -> Core.app.post(this::setupUI));

        // 绘制期诊断。
        //
        // 之前的诊断只在 ApplicationListener.update() 里取样，那是**渲染之后**的
        // 状态，看不出「渲染时 fog 到底是什么」。而 BlockRenderer 的建筑绘制门是
        //     boolean visible = (build == null || !build.inFogTo(pteam));
        //     if(block != Blocks.air && (visible || build.wasVisible)) { ... }
        // 而 BuildingComp.inFogTo 在 !state.rules.fog 时返回 false。
        //
        // 所以如果渲染那一刻 fog 还是 true，建筑就会被判为「在迷雾里」而不画 ——
        // 但 update() 里看到的是 false，两边对不上，症状就是「看不到建筑」。
        //
        // Trigger.drawOver 正好在 blocks.drawBlocks() 之前触发（Renderer.java:430），
        // 在这里取样就能拿到真正决定绘制的那份状态。
        //
        // Groups.draw 也要看：渲染器画的是 Groups.draw（Renderer.java:433），
        // 不是 Groups.unit —— 实体在 Groups.unit 里但在 Groups.draw 里没有，
        // 同样不会被画出来。
        Events.run(mindustry.game.EventType.Trigger.drawOver, () -> {
            if (!spectator) return;

            // ⚠ 这里必须**强制覆盖**，不能只在 ApplicationListener.update() 里设。
            //
            // 实测同一时刻两条日志：
            //     [drawdiag] rulesFog=true    ← 渲染时
            //     [diag]     fog=false        ← update() 里
            // 引擎里没有任何地方会把 rules.fog 改回 true，所以只能是时序：渲染发生在
            // 我的 update 之前，update 里设的值作用不到这一帧的绘制上。
            //
            // 后果很具体 —— BlockRenderer 的建筑绘制门是
            //     boolean visible = (build == null || !build.inFogTo(pteam));
            // BuildingComp.inFogTo 在 fog=true 时会查 isDiscovered(viewer)，而观战者
            // 在 derelict 没有任何迷雾位图 → 返回 false → inFogTo 返回 true
            // → 每个建筑都被判为「在迷雾里」而不画。单位同理。
            //
            // drawOver 在 Renderer.java:430 触发，紧接着 431 行才是 blocks.drawBlocks()。
            // 在这里改，当帧就生效。
            boolean fullView;
            try {
                fullView = Vars.player != null && Vars.player.team() == mindustry.game.Team.derelict;
            } catch (Throwable t) {
                fullView = false;
            }
            if (fullView) {
                if (Vars.state.rules.fog) Vars.state.rules.fog = false;
                if (Vars.state.rules.staticFog) Vars.state.rules.staticFog = false;
            }

            if (arc.util.Time.timeSinceMillis(lastDrawDiag) < 2000) return;
            lastDrawDiag = arc.util.Time.millis();

            // 客户端本地的迷雾数据诊断。
            //
            // 观战切到某些队伍时整屏全黑，而 UI 层正常（队伍名、核心库存都对）。
            // FogRenderer 的第一步是：
            //     if(fogControl.getDiscovered(player.team()) == null) return;
            // 所以「fog 数据为 null」反而会导致**不画迷雾**、世界可见；
            // 黑屏说明数据存在但位图全零。这里把两者都打出来。
            String fogState = "?";
            int discCount = 0;
            try {
                var disc = Vars.fogControl.getDiscovered(Vars.player.team());
                if (disc == null) {
                    fogState = "null(不画迷雾)";
                } else {
                    for (int i = 0; i < disc.length(); i++) {
                        if (disc.get(i)) discCount++;
                    }
                    fogState = "len=" + disc.length() + " bits";
                }
            } catch (Throwable t) {
                fogState = "err:" + t;
            }

            arc.util.Log.info("[drawdiag] team=@ world=@x@ (expect @) discovered=@ 已探索=@",
                Vars.player.team().name,
                Vars.world.width(), Vars.world.height(),
                Vars.world.width() * Vars.world.height(),
                fogState, discCount);
        });

        if (AUTO_CONNECT) {
            Events.on(EventType.ClientLoadEvent.class, e -> Time.run(60f, this::autoConnect));

            // 断线重连看门狗跑在独立线程上 —— 主线程在断线时可能已经不更新了
            Thread t = new Thread(this::watchConnection, "ai-observer-reconnect");
            t.setDaemon(true);
            t.start();
        }

        Core.app.addListener(new arc.ApplicationListener() {
            @Override
            public void update() {
                if (Vars.state == null || !Vars.state.isGame()) return;

                maintainSpectatorState();
                if (!enabled) return;

                // 只处理按键（F1 / Tab / G），**不碰相机**。
                //
                // 早期版本在这里每帧 Core.camera.position.set(camPos)，把相机拽回自己
                // 维护的位置 —— 结果是和引擎打架：DesktopInput 本来就有「玩家已死 →
                // 自由平移」分支（WASD / 中键拖拽 / 滚轮缩放都在里面），观战者永远
                // dead，所以引擎那套完全可用；但我每帧再覆盖一次，两边互相抵消，
                // 表现就是「怎么按视角都不动」。
                //
                // 输入交给引擎，观战端只管视角切换。
                updateHotkeys();

                // 切队时把相机**跳一次**到那一队的核心，之后就交还给玩家自由平移。
                //
                // 为什么必须跳：不跳的话相机会留在上一队的位置，而新队伍在那片区域
                // 大概率没探索过 —— 迷雾正确地把它画成全黑，看起来就像「切到这一队
                // 就黑屏」，非常容易被误判成渲染 bug。
                //
                // 为什么只跳一次：早期版本每帧 Core.camera.position.set(...)，
                // 等于和引擎抢方向盘 —— DesktopInput 本来就有「玩家已死 → 自由平移」
                // 分支（WASD / 中键拖拽 / 滚轮缩放），每帧覆盖会让两边互相抵消，
                // 表现是「怎么按视角都不动」。
                jumpCameraOnViewChange();
            }
        });
    }

    private int lastJumpedViewTeam = Integer.MIN_VALUE;

    /** 视角队伍变化时，把相机移到该队核心（或任意一栋建筑）上。 */
    private void jumpCameraOnViewChange() {
        try {
            if (Vars.player == null) return;
            int now = Vars.player.team().id;
            if (now == lastJumpedViewTeam) return;
            lastJumpedViewTeam = now;

            // 全图视角（derelict）不跳，让玩家自己看
            if (Vars.player.team() == mindustry.game.Team.derelict) return;

            float tx = Float.NaN, ty = Float.NaN;

            // 优先核心，其次任意建筑，最后任意单位 —— 都是「这一队的家」。
            try {
                var core = Vars.player.team().core();
                if (core != null) { tx = core.x; ty = core.y; }
            } catch (Throwable ignored) {}

            if (Float.isNaN(tx)) {
                for (var b : Vars.player.team().data().buildings) {
                    if (b == null) continue;
                    tx = b.x; ty = b.y; break;
                }
            }
            if (Float.isNaN(tx)) {
                for (var u : Vars.player.team().data().units) {
                    if (u == null) continue;
                    tx = u.x; ty = u.y; break;
                }
            }
            if (Float.isNaN(tx)) return;

            Core.camera.position.set(tx, ty);
            arc.util.Log.info("[observer] camera jumped to (@,@) for view team @", (int) tx, (int) ty, now);
        } catch (Throwable t) {
            arc.util.Log.info("[observer] camera jump failed: @", t.toString());
        }
    }

    /**
     * 维持观战状态。每帧跑，因为服务端可能在任意时刻改我们的视角。
     */
    private void maintainSpectatorState() {
        try {
            // 重连请求只能在主线程执行（watchdog 线程只置标志）
            if (reconnectRequested) {
                reconnectRequested = false;
                if (!Vars.net.client() && !Vars.net.active()) autoConnect();
            }

            var p = Vars.player;
            if (p == null) return;

            // 服务端把观战者放进 derelict 且不给单位 —— 用这个组合认定自己是观战端。
            // 判定成观战端之后就一直保持，避免切到真实队伍视角时误判成普通玩家。
            if (!spectator) {
                boolean looksLikeSpectator = p.dead() && p.team() == mindustry.game.Team.derelict;
                if (looksLikeSpectator) {
                    spectator = true;
                    arc.util.Log.info("[observer] spectator detected, local team=@", p.team().name);

                    // 相机对准战场。
                    //
                    // 这是最容易被误判成「单位没渲染」的坑：实体数据全都在客户端手里
                    // （诊断里 units=34 和服务端完全一致），但相机停在空地时画面就是
                    // 一片什么都没有的地形。地图中心尤其糟 —— 那里通常正好是双方之间的
                    // 无人区，最近的基地还在屏幕外。
                    focusAction();
                }
            }
            if (!spectator) return;

            // 1. 本地置上 spectator，避免客户端自己发 requestSpawn 包
            if (!p.spectator) p.spectator = true;

            // 2. 兜底清单位（服务端已经不会给，这里只是防止旧状态残留）
            if (p.unit() != null) p.clearUnit();

            // 3. 不再本地改队。
            //
            // 视角队伍由**服务端**设定，客户端跟着实体快照走 —— 观战者自己的
            // player 实体也在同步之列，team 是同步字段，服务端改完下一个快照就到。
            //
            // 早期版本让客户端本地改 player.team()，结果两边互相打架：
            // 实体快照每帧把 team 写回服务端那份，客户端每帧再改回去，
            // 画面持续闪动（「切过去又强制切回裁判又切回来」）。
            // 唯一事实来源只有一个，才不会闪。

            // 4. 全图视角不画迷雾。
            //    服务端用「spectator 且队伍是 derelict」表示全图，见 NetServer.isFullView。
            boolean fullView = p.team() == mindustry.game.Team.derelict;

            if (fullView) {
                if (Vars.state.rules.fog) Vars.state.rules.fog = false;
                if (Vars.state.rules.staticFog) Vars.state.rules.staticFog = false;
            } else if (!Vars.state.rules.fog) {
                // 切回队伍视角时恢复（服务端那份 rules 一直是 fog=true）
                Vars.state.rules.fog = true;
                Vars.state.rules.staticFog = true;
            }

            // 队伍变化时打一行日志 —— 这是排查「切队没反应 / 迷雾不切换」最直接的证据。
            // 打印的是**改完之后**的状态，否则看到的是实体快照刚覆盖回来的旧值。
            //
            // units/builds 尤其重要：UnitComp.handleSyncHidden() 会把不可见的单位
            // 直接从客户端删掉（remove()），所以切到队伍视角再切回全图时，
            // 这些单位是否被重新补回来，只能靠这里的计数确认。
            String teamName = p.team().name;
            if (!teamName.equals(lastLoggedTeam)) {
                lastLoggedTeam = teamName;
                arc.util.Log.info("[observer] view -> @ (@) | fog=@ staticFog=@ | units=@ builds=@ | hasUnit=@",
                    teamName, fullView ? "FULL MAP" : "team vision",
                    Vars.state.rules.fog, Vars.state.rules.staticFog,
                    Groups.unit.size(), Groups.build.size(), p.unit() != null);
            }

            // 周期性快照：用来和服务端的 /units?view=all 对照，确认客户端手里的
            // 实体集合和服务端一致（排查「全图看不到单位」是渲染问题还是实体缺失）。
            //
            // 一行包含排查所需的全部事实：队伍、迷雾、实体数、相机位置、连接状态。
            // 只看「有没有单位」是不够的 —— 相机停在地图角落时画面同样空无一物，
            // 而这两种情况的修法完全不同。
            if (arc.util.Time.timeSinceMillis(lastStatusLog) > 2000) {
                lastStatusLog = arc.util.Time.millis();
                arc.util.Log.info("[diag] team=@ fog=@ staticFog=@ units=@ builds=@ cam=(@,@) spectator=@ hasUnit=@ net=@",
                    teamName, Vars.state.rules.fog, Vars.state.rules.staticFog,
                    Groups.unit.size(), Groups.build.size(),
                    (int) (Core.camera.position.x / Vars.tilesize),
                    (int) (Core.camera.position.y / Vars.tilesize),
                    spectator, p.unit() != null,
                    (Vars.net.client() && Vars.net.active()) ? "up" : "down");
            }
        } catch (Throwable ignored) {
        }
    }

    // ---------------------------------------------------------------- 连接

    private void autoConnect() {
        try {
            if (Vars.net.client() || Vars.net.active()) return;
            log("connecting to " + AUTO_HOST + ":" + AUTO_PORT);
            Vars.ui.join.connect(AUTO_HOST, AUTO_PORT);
        } catch (Throwable t) {
            log("connect failed: " + t);
        }
    }

    /**
     * 断线自动重连。
     *
     * 实测客户端会间歇性掉线（服务器日志报 "disconnected. (closed)"），
     * 原因是这台机器装了 HIPS 类安全软件，其内核过滤驱动会间歇拦 UDP。
     *
     * ⚠ 这个线程**只观察、不动作**。Vars.ui.join.connect() 会碰 UI 和游戏状态，
     * 必须在主线程跑 —— 早期版本直接在 watchdog 线程里调它，客户端会莫名其妙
     * 退出（stdout 里没有任何异常，因为异常根本没机会被记录）。
     * 现在只置一个标志，由主线程的 maintainSpectatorState() 消费。
     */
    private void watchConnection() {
        if (!AUTO_CONNECT) return;

        boolean wasConnected = false;
        int misses = 0;

        while (true) {
            try {
                boolean connected = Vars.net.client() && Vars.net.active() && Vars.state.isGame();

                if (connected) {
                    if (!wasConnected) log("connected");
                    wasConnected = true;
                    misses = 0;
                } else {
                    if (wasConnected) {
                        log("disconnected, will retry");
                        wasConnected = false;
                        spectator = false;   // 重连后重新认定
                    }
                    // 连续多次判定为断开才请求重连，避免把「正在加载世界」
                    // 这类瞬时状态误判成掉线
                    misses++;
                    if (misses >= 6) {
                        misses = 0;
                        reconnectRequested = true;
                    }
                }
            } catch (Throwable ignored) {
            }

            try { Thread.sleep(1000); } catch (InterruptedException e) { return; }
        }
    }

    private void log(String msg) {
        try { Vars.ui.showInfoFade("[accent]观战端: [white]" + msg); } catch (Throwable ignored) {}
    }

    // ---------------------------------------------------------------- UI

    private void setupUI() {
        if (Vars.ui == null || Vars.ui.hudGroup == null) return;

        Table root = new Table();
        root.setFillParent(true);
        root.top().left();

        Table box = new Table();
        box.background(Styles.black6);

        statusLabel = box.label(this::statusText).left().pad(4f).get();
        box.row();
        box.table(btns -> {
            btns.defaults().pad(2f);
            btns.button("下一队", Styles.defaultt, this::cycleTeam).width(90f);
            btns.button("全图", Styles.defaultt, () -> viewAll()).width(70f);
            btns.button("帮助", Styles.defaultt, () -> {
                helpVisible = !helpVisible;
                if (helpTable != null) helpTable.visible = helpVisible;
            }).width(70f);
        }).left().row();

        helpTable = new Table();
        helpTable.background(Styles.black6);
        helpTable.add("[accent]观战操作[]").left().row();
        helpTable.add("WASD / 方向键   平移相机").left().row();
        helpTable.add("中键拖拽         平移相机").left().row();
        helpTable.add("滚轮             缩放").left().row();
        helpTable.add("Tab              切到下一个有核心的队伍").left().row();
        helpTable.add("G                全图裁判视角").left().row();
        helpTable.add("F1               显示/隐藏本帮助").left().row();
        helpTable.add("[lightgray]只读观战：服务端不会给你任何单位[]").left().row();
        box.add(helpTable).left().padTop(4f);

        root.add(box).left().top().pad(8f);
        Vars.ui.hudGroup.addChild(root);
    }

    private String statusText() {
        String team;
        try {
            team = Vars.player == null ? "-" : Vars.player.team().name;
        } catch (Throwable t) {
            team = "?";
        }
        return "[accent]观战端[]  "
             + (spectator ? "[green]观战[]" : "[gray]未连接[]")
             + "  视角: " + team
             + (team.equals("derelict") ? " [lightgray](全图)[]" : "");
    }

    // ---------------------------------------------------------------- 视角

    /**
     * 切到下一个有核心的队伍。
     *
     * 客户端自己算出目标队伍，然后把**明确的队伍 id** 发给服务端，同时把本地
     * player.team() 也切过去 —— 本地这一份只影响迷雾渲染，服务端那一份只影响
     * 「该给我发哪些实体」，两边合起来才是一致视角。
     *
     * 早期版本让服务端切队后重发世界数据，结果连按几次就把 30+ kB 的世界数据
     * 连发十几次，客户端被淹没、屏幕全黑、最后进程退出。现在不重发任何世界数据。
     */
    private void cycleTeam() {
        try {
            if (!spectator) {
                log("尚未以观战者身份连上服务器");
                return;
            }

            arc.struct.IntSeq ids = new arc.struct.IntSeq();
            for (var td : Vars.state.teams.present) {
                if (td.cores.size > 0) ids.add(td.team.id);
            }
            if (ids.isEmpty()) {
                log("没有找到有核心的队伍");
                return;
            }
            ids.sort();

            // 当前是哪个队就切到下一个；全图（derelict）从第一个开始
            int current = Vars.player.team().id;
            int next = ids.first();
            for (int i = 0; i < ids.size; i++) {
                if (ids.get(i) == current) {
                    next = ids.get((i + 1) % ids.size);
                    break;
                }
            }

            applyView(next);
            Call.sendChatMessage("/arena-view " + next);

            // 相机跟着跳到那个队伍的核心 —— 否则切了队画面还停在原地，
            // 看起来像「切队没反应」。
            jumpToTeam(mindustry.game.Team.get(next));
        } catch (Throwable t) {
            log("切换视角失败: " + t);
        }
    }

    /** 全图裁判视角。 */
    private void viewAll() {
        applyView(-1);
        Call.sendChatMessage("/arena-view all");
    }

    /**
     * 把相机对准「有东西的地方」。
     *
     * 优先找最近的建筑群（核心），找不到就取所有单位的质心。全图视角下两者都能
     * 让画面里立刻出现内容 —— 否则相机可能正好落在双方之间的无人区。
     */
    private void focusAction() {
        try {
            // 1. 优先：离地图中心最近的建筑（通常是某个核心）
            float cx = Vars.world.width() * Vars.tilesize / 2f;
            float cy = Vars.world.height() * Vars.tilesize / 2f;

            float best = Float.MAX_VALUE;
            float bx = cx, by = cy;
            boolean found = false;
            for (mindustry.gen.Building b : Groups.build) {
                if (b == null || b.block == null) continue;
                float d = (b.x - cx) * (b.x - cx) + (b.y - cy) * (b.y - cy);
                if (d < best) { best = d; bx = b.x; by = b.y; found = true; }
            }

            // 2. 兜底：所有单位的质心
            if (!found && Groups.unit.size() > 0) {
                float sx = 0f, sy = 0f;
                for (Unit u : Groups.unit) { sx += u.x; sy += u.y; }
                bx = sx / Groups.unit.size();
                by = sy / Groups.unit.size();
                found = true;
            }

            if (!found) { bx = cx; by = cy; }

            camPos.set(bx, by);
            Core.camera.position.set(camPos);
            freeCamera = true;

            arc.util.Log.info("[observer] camera focused on (@,@) tiles, builds=@ units=@",
                (int) (bx / Vars.tilesize), (int) (by / Vars.tilesize),
                Groups.build.size(), Groups.unit.size());
        } catch (Throwable t) {
            arc.util.Log.info("[observer] focusAction failed: " + t);
        }
    }

    /**
     * 本地切换视角队伍。
     *
     * 只改本机的 player.team()，不发任何东西给服务端 —— 它决定客户端渲染哪个
     * 队伍的迷雾。服务端的视角由 /arena-view 指令单独设置。
     *
     * ⚠ 这里**不能**调 fogControl.resetFog()。那会把客户端的迷雾位图整个清空，
     * 而位图是随世界数据下发的，清掉之后不会自己回来 —— 表现就是切完队伍
     * 永远一片黑。FogRenderer 自己会在队伍变化时 copyFromCpu() 重画静态迷雾，
     * 不需要我们插手。
     */
    private void applyView(int teamId) {
        // 视角队伍由服务端设定并通过实体快照同步过来，这里只记录我们请求了什么。
        desiredViewTeam = teamId;
    }

    private void sendViewCommand(String arg) {
        try {
            if (!spectator) {
                log("尚未以观战者身份连上服务器");
                return;
            }
            Call.sendChatMessage("/arena-view " + arg);
        } catch (Throwable t) {
            log("切换视角失败: " + t);
        }
    }

    /** 把相机移到指定队伍的核心（或第一个单位）上。 */
    private void jumpToTeam(mindustry.game.Team team) {
        try {
            if (team == null) return;

            var core = team.core();
            if (core != null) {
                camPos.set(core.x, core.y);
                Core.camera.position.set(camPos);
                freeCamera = true;
                return;
            }
            for (Unit u : Groups.unit) {
                if (u.team == team) {
                    camPos.set(u.x, u.y);
                    Core.camera.position.set(camPos);
                    freeCamera = true;
                    return;
                }
            }
        } catch (Throwable ignored) {
        }
    }

    // ---------------------------------------------------------------- 相机

    /**
     * 只处理观战端自己的热键，**不动相机**。
     *
     * 相机的平移/缩放全部交给引擎的 DesktopInput：它本来就有「玩家已死 → 自由平移」
     * 分支，观战者永远 dead，所以那套逻辑完全适用（WASD / 方向键 / 中键拖拽 / 滚轮）。
     * 早期版本自己维护 camPos 并每帧覆盖 Core.camera.position，等于和引擎抢方向盘，
     * 两边互相抵消，结果就是「怎么按视角都不动」。
     */
    private void updateHotkeys() {
        if (Vars.state == null || !Vars.state.isPlaying()) return;
        if (Vars.ui != null && Vars.ui.chatfrag != null && Vars.ui.chatfrag.shown()) return;

        Input input = Core.input;

        if (input.keyTap(KeyCode.f1)) {
            helpVisible = !helpVisible;
            if (helpTable != null) helpTable.visible = helpVisible;
        }

        // 视角切换限流：按住 Tab 会连发很多次，而每次切换都要服务端改过滤、
        // 客户端重画迷雾。600ms 足够跟手，又不会把客户端压垮。
        boolean viewAllowed = arc.util.Time.timeSinceMillis(lastViewChange) > 600;
        if (input.keyTap(KeyCode.tab) && viewAllowed) {
            lastViewChange = arc.util.Time.millis();
            cycleTeam();
        }
        if (input.keyTap(KeyCode.g) && viewAllowed) {
            lastViewChange = arc.util.Time.millis();
            viewAll();
        }
    }

    /** 供外部（其他 Mod / 调试）启停。 */
    public void setEnabled(boolean v) { this.enabled = v; }
}
