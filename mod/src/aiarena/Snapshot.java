package aiarena;

import arc.Core;
import arc.util.Time;
import mindustry.Vars;
import mindustry.game.Team;

/**
 * 主线程只读快照。
 *
 * 设计要点（源自 DESIGN.md 5.2 读写分离）：
 *
 *   读:  主线程定期生成不可变快照 ──→ HTTP 线程直接读（零跨线程，零阻塞）
 *   写:  HTTP 线程投递任务 ──→ 主线程队列执行 ──→ 结果回传
 *
 * 为什么读不能走 Core.app.post：
 *   post 在下一帧才执行，每个读请求至少延迟 1 帧；且 Future 等待会阻塞
 *   HTTP 线程，AI 轮询时会把线程池耗尽。主线程一旦因大战场变慢，HTTP 全线卡死。
 *
 * 并发模型：快照对象构造完成后不再修改，主线程整体替换 volatile 引用。
 * HTTP 线程读到的是某个完整版本，不会看到半个状态。
 */
public final class Snapshot {

    /** 当前快照。主线程写入，HTTP 线程读取。 */
    private static volatile State current = State.empty();

    private static int lastHeavyTick = -1;

    /** 轻量状态每 tick 刷新；重量级列表按 HEAVY_INTERVAL 刷新。 */
    private static final int HEAVY_INTERVAL_TICKS = 6;   // ≈ 10 Hz @ 60 FPS

    private Snapshot() {}

    /** 不可变快照。 */
    public static final class State {
        public final int tick;
        public final int wave;
        public final boolean playing;
        public final boolean paused;
        public final boolean gameOver;
        public final boolean pvp;
        public final boolean fog;
        public final int worldWidth, worldHeight;

        public final TeamInfo[] teams;
        public final UnitInfo[] units;
        public final BuildInfo[] builds;

        /** 单位/建筑列表是否是本 tick 新刷的（供调用方判断新鲜度）。 */
        public final boolean heavyFresh;

        State(int tick, int wave, boolean playing, boolean paused, boolean gameOver,
              boolean pvp, boolean fog, int worldWidth, int worldHeight,
              TeamInfo[] teams, UnitInfo[] units, BuildInfo[] builds, boolean heavyFresh) {
            this.tick = tick;
            this.wave = wave;
            this.playing = playing;
            this.paused = paused;
            this.gameOver = gameOver;
            this.pvp = pvp;
            this.fog = fog;
            this.worldWidth = worldWidth;
            this.worldHeight = worldHeight;
            this.teams = teams;
            this.units = units;
            this.builds = builds;
            this.heavyFresh = heavyFresh;
        }

        static State empty() {
            return new State(0, 0, false, false, false, false, false, 0, 0,
                             new TeamInfo[0], new UnitInfo[0], new BuildInfo[0], false);
        }
    }

    public static final class TeamInfo {
        public final int id;
        public final String name;
        public final boolean ai;
        public final boolean alive;
        public final int cores;
        public final int players;

        TeamInfo(int id, String name, boolean ai, boolean alive, int cores, int players) {
            this.id = id; this.name = name; this.ai = ai; this.alive = alive;
            this.cores = cores; this.players = players;
        }
    }

    public static final class UnitInfo {
        public final int id;
        public final String type;
        public final int team;
        public final float x, y;
        public final float health, maxHealth;
        public final float rotation;
        public final boolean canBuild;
        /** 携带物（item 名 → 数量）。单位能捡起物品并携带，这是玩家能看到的信息。 */
        public final String[] stackItems;
        public final int[] stackAmounts;
        /** 被控制的玩家 id；-1 表示 AI 控制。 */
        public final int controllerId;
        /** 当前指令名。 */
        public final String command;

        /**
         * 是否正在开火。玩家看得见单位在射击（枪口火光、弹道），无条件公平。
         */
        public final boolean shooting;
        /**
         * 当前交战目标的位置；NaN 表示没有目标。
         *
         * 对等性：玩家看得见弹道往哪飞，所以「朝哪个方向打」是可见信息。
         */
        public final float targetX, targetY;
        /** 目标的实体 id / 类型 / 队伍；目标不可见时由输出层清空。 */
        public final int targetId;
        public final String targetType;
        public final int targetTeam;
        /**
         * 弹药。UnitType.ammoCapacity 默认就是 1，UnitComp.ammof() 对普通单位
         * 恒返回 1 —— 所以 flare/gamma 这类单位这里永远是 1/1。
         * 只有方块单位（BlockUnitUnit）才真的会用这个值。
         */
        public final float ammo;
        public final int ammoCapacity;

        /**
         * 这个建造单位**当前正在建的那一格**（建造队列的队首）。
         * -1 表示它没有待办计划。
         *
         * 对等性：玩家看得见自己的建造单位在哪、在盖什么、盖到几成
         * （方块的施工进度条就画在屏幕上）。
         */
        public final int buildX, buildY;
        /** 当前这一格的施工进度 0~1。配合轮询就能算出「还要多久」。 */
        public final float buildProgress;
        /** 正在建什么方块；构造中该格可能是 ConstructBlock，所以取计划里的目标。 */
        public final String buildBlock;

        /** 这个单位的视野半径（`u.type.fogRadius`）。 */
        public final float fogRadius;

        UnitInfo(int id, String type, int team, float x, float y,
                 float health, float maxHealth, float rotation, boolean canBuild,
                 String[] stackItems, int[] stackAmounts, int controllerId, String command,
                 boolean shooting, float targetX, float targetY,
                 int targetId, String targetType, int targetTeam,
                 float ammo, int ammoCapacity,
                 int buildX, int buildY, float buildProgress, String buildBlock,
                 float fogRadius) {
            this.id = id; this.type = type; this.team = team; this.x = x; this.y = y;
            this.health = health; this.maxHealth = maxHealth;
            this.rotation = rotation; this.canBuild = canBuild;
            this.stackItems = stackItems; this.stackAmounts = stackAmounts;
            this.controllerId = controllerId; this.command = command;
            this.shooting = shooting;
            this.targetX = targetX; this.targetY = targetY;
            this.targetId = targetId; this.targetType = targetType; this.targetTeam = targetTeam;
            this.ammo = ammo; this.ammoCapacity = ammoCapacity;
            this.buildX = buildX; this.buildY = buildY;
            this.buildProgress = buildProgress; this.buildBlock = buildBlock;
            this.fogRadius = fogRadius;
        }

    }

    public static final class BuildInfo {
        public final int x, y, team;
        public final String block;
        public final float health, maxHealth;
        public final boolean enabled;
        public final float efficiency;
        /** 库存（item 名 → 数量）。玩家选中建筑就能看到。 */
        public final String[] items;
        public final int[] itemAmounts;
        /** 液体（liquid 名 → 数量）。 */
        public final String[] liquids;
        public final float[] liquidAmounts;
        /** 配置值的字符串形式；null 表示无配置。 */
        public final String config;
        /** 是否正在施工（ConstructBlock）。 */
        public final boolean constructing;
        /** 正在施工时的进度 0~1。 */
        public final float buildProgress;
        /**
         * 方块朝向 0~3（0=东 1=北 2=西 3=南）。
         *
         * 对等性：玩家看得见任何可见建筑的朝向 —— 传送带往哪流、
         * 炮塔朝哪边、工厂从哪边吐单位，全是画在屏幕上的。
         */
        /** 建筑的唯一 id。**必须暴露** —— /command?action=commandBuilding
         *  要求传 buildingIds，没有它这个 action 谁都调不了。 */
        public final int id;

        public final int rotation;
        /**
         * 电力满足度 0~1。玩家选中建筑能看到电力条，无条件可见。
         * 没有电力模块时为 -1。
         */
        public final float powerStatus;
        /**
         * 电力连线对端坐标，Point2.pack 打包。
         *
         * 对等性：PowerNode.draw() 只对**通过迷雾检查的建筑**调用，
         * 而可见节点的激光线会一直画到对端真实坐标：
         *     for(int i = 0; i < power.links.size; i++){
         *         Building link = world.build(power.links.get(i));
         *         drawLaser(x, y, link.x, link.y, size, link.block.size);
         *     }
         * 所以「可见节点的连线位置」是玩家能看到的。
         * 但**对端建筑本身在雾里时是黑的** —— 只知位置，不知是什么方块。
         * 这个区分留给读取方（visibleBuildings 会按队伍逐条判 visible）。
         */
        public final int[] powerLinks;

        /**
         * 能推货进来的邻格（Point2.pack），null 表示该方块没有「接货口」概念。
         *
         * 传送带专用，按 `Conveyor.acceptItem` 的方位规则算（Conveyor.java:352-358）：
         *
         *     direction = |relativeTo(源格) - rotation|
         *     direction == 0   背面，minitem >= 0.4   收
         *     direction 1 / 3  两侧，minitem >  0.7   收  ← 拐弯容易堵的真因
         *     direction == 2   正面（下游）           拒收
         *
         * 只列**该方位上真有建筑**的格 —— 空地不列，免得读的人以为那里有东西。
         *
         * 这是**规则**不是**结论**：告诉 AI 这格能从哪边收料，不替它判断
         * 「这条链会不会堵」。
         */
        /**
         * 这个建筑的视野半径（`build.fogRadius()`）。
         *
         * 对等性：视野范围是玩家能直接看到的东西 —— 屏幕上雾的范围就是它决定的。
         * 注意这**不是**建造范围（那是 UnitType.buildRange），两回事。
         */
        public final float fogRadius;

        public final int[] acceptsFrom;

        /**
         * 把货推出去的格（Point2.pack）。
         *
         * 传送带 = 正面那一格（不管那里有没有东西，那是它的朝向）。
         * 钻机 = **所有能接收的邻格** —— 钻机输出不受 rotation 控制，
         * 所以这里给的是实测结果而不是推导，探针用它脚下占多数的那个矿。
         */
        public final int[] sendsTo;

        BuildInfo(int id, int x, int y, int team, String block,
                  float health, float maxHealth, boolean enabled, float efficiency,
                  String[] items, int[] itemAmounts,
                  String[] liquids, float[] liquidAmounts,
                  String config, boolean constructing, float buildProgress,
                  int rotation, float powerStatus, int[] powerLinks,
                  float fogRadius, int[] acceptsFrom, int[] sendsTo) {
            this.id = id;
            this.x = x; this.y = y; this.team = team; this.block = block;
            this.health = health; this.maxHealth = maxHealth;
            this.enabled = enabled; this.efficiency = efficiency;
            this.items = items; this.itemAmounts = itemAmounts;
            this.liquids = liquids; this.liquidAmounts = liquidAmounts;
            this.config = config; this.constructing = constructing;
            this.buildProgress = buildProgress;
            this.rotation = rotation;
            this.powerStatus = powerStatus;
            this.powerLinks = powerLinks;
            this.fogRadius = fogRadius;
            this.acceptsFrom = acceptsFrom;
            this.sendsTo = sendsTo;
        }
    }

    // ---------------------------------------------------------------- update

    /**
     * 由主线程每帧调用。自身不做任何跨线程同步 —— 只构造新对象后整体替换引用。
     */
    public static void update() {
        try {
            int tick = (int) Vars.state.tick;

            // 注意 tick 回退：loadMap 会把 state.tick 重置为 0，而 lastHeavyTick 还留着
            // 上一张地图的值（例如 1500）。此时 (tick - lastHeavyTick) 是负数，条件
            // 永远不成立，快照会一直返回上一局的数据。必须把回退本身当成刷新信号。
            boolean heavy = (lastHeavyTick < 0)
                         || tick < lastHeavyTick
                         || (tick - lastHeavyTick >= HEAVY_INTERVAL_TICKS);

            // 情报状态机需要逐 tick 推进 —— 视野判定是按 tick 计的
            Intel.update();

            // 录像器逐 tick 推进（内部按 SNAPSHOT_INTERVAL 限流）
            Recorder.update();

            TeamInfo[] teams;
            UnitInfo[] units;
            BuildInfo[] builds;

            if (heavy) {
                lastHeavyTick = tick;
                teams  = collectTeams();
                units  = collectUnits();
                builds = collectBuilds();
                diffEntities(units, builds);
            } else {
                State prev = current;
                teams  = prev.teams;
                units  = prev.units;
                builds = prev.builds;
            }

            current = new State(
                tick,
                Vars.state.wave,
                Vars.state.isPlaying(),
                Vars.state.isPaused(),
                Vars.state.gameOver,
                Vars.state.rules.pvp,
                Vars.state.rules.fog,
                Vars.world.width(),
                Vars.world.height(),
                teams, units, builds,
                heavy
            );
        } catch (Throwable t) {
            // 快照失败绝不能影响游戏主循环
            AIArena.log("snapshot update failed: " + t);
        }
    }

    private static TeamInfo[] collectTeams() {
        TeamInfo[] out = new TeamInfo[Vars.state.teams.present.size];
        int i = 0;
        for (var td : Vars.state.teams.present) {
            out[i++] = new TeamInfo(
                td.team.id, td.team.name, td.team.isAI(), td.team.isAlive(),
                td.cores.size, td.players.size);
        }
        return out;
    }

    private static UnitInfo[] collectUnits() {
        UnitInfo[] out = new UnitInfo[mindustry.gen.Groups.unit.size()];
        int i = 0;
        for (mindustry.gen.Unit u : mindustry.gen.Groups.unit) {
            if (u == null || !u.isAdded()) continue;

            // 携带物
            String[] stItems = new String[0];
            int[] stAmts = new int[0];
            if (u.stack != null && u.stack.amount > 0 && u.stack.item != null) {
                stItems = new String[]{u.stack.item.name};
                stAmts = new int[]{u.stack.amount};
            }

            // 控制器：玩家控制时给玩家 id，AI 控制时给 -1
            int ctrl = -1;
            var c = u.controller();
            if (c instanceof mindustry.gen.Player p && p != null) ctrl = p.id;

            // 当前指令
            String cmd = "";
            if (c instanceof mindustry.ai.types.CommandAI cai && cai.command != null) {
                cmd = cai.command.name;
            }

            // 开火状态 + 交战目标。
            // attackTarget 挂在 CommandAI 上（CommandAI.java:27），
            // isShooting 在 WeaponsComp（WeaponsComp.java:20）。
            boolean shooting = u.isShooting();
            float tx = Float.NaN, ty = Float.NaN;
            int tid = -1;
            String ttype = "";
            int tteam = -1;
            if (c instanceof mindustry.ai.types.CommandAI cai && cai.attackTarget != null) {
                var at = cai.attackTarget;
                if (at instanceof mindustry.gen.Unit au) {
                    tx = au.x; ty = au.y; tid = au.id; ttype = au.type.name; tteam = au.team.id;
                } else if (at instanceof mindustry.gen.Building ab) {
                    tx = ab.x; ty = ab.y; tid = ab.id; ttype = ab.block.name; tteam = ab.team.id;
                } else {
                    tx = at.getX(); ty = at.getY();
                }
            }

            // 建造队列的队首就是它下一步要建的格子（BuilderComp 按 plans.first() 推进）
            int bX = -1, bY = -1;
            float bProg = 0f;
            String bBlock = null;
            try {
                if (u.plans != null && u.plans.size > 0) {
                    mindustry.entities.units.BuildPlan bp = u.plans.first();
                    if (bp != null) {
                        bX = bp.x; bY = bp.y; bProg = bp.progress;
                        if (bp.block != null) bBlock = bp.block.name;
                    }
                }
            } catch (Throwable ignored) { }

            float fogR = 0f;
            try { fogR = u.type.fogRadius; } catch (Throwable ignored) { }

            out[i++] = new UnitInfo(
                u.id, u.type.name, u.team.id, u.x, u.y,
                u.health, u.maxHealth, u.rotation, u.canBuild(),
                stItems, stAmts, ctrl, cmd,
                shooting, tx, ty, tid, ttype, tteam,
                u.ammof(), u.type.ammoCapacity,
                bX, bY, bProg, bBlock, fogR);
        }
        if (i == out.length) return out;
        UnitInfo[] trimmed = new UnitInfo[i];
        System.arraycopy(out, 0, trimmed, 0, i);
        return trimmed;
    }

    /**
     * 收集所有队伍的建筑。
     *
     * 用 TeamData.buildings 而不是 Groups.build —— 后者是为逻辑处理器准备的分组，
     * 实测只返回了部分建筑（三个核心与一个传送带里只出现了一个）。
     * TeamData.buildings 是引擎自己维护的每队建筑列表，覆盖完整。
     */
    private static BuildInfo[] collectBuilds() {
        arc.struct.Seq<BuildInfo> list = new arc.struct.Seq<>();
        for (var td : Vars.state.teams.present) {
            // 对 TeamData.buildings 做防御性遍历：这是引擎维护的 Seq，
            // 建筑在建造/摧毁过程中会被增删。虽然快照在主线程跑，但同一个
            // tick 内引擎也可能在别处改动它，越界访问会抛异常。
            int n;
            try { n = td.buildings.size; }
            catch (Throwable t) { continue; }

            for (int bi = 0; bi < n; bi++) {
                mindustry.gen.Building b;
                try { b = td.buildings.get(bi); }
                catch (Throwable t) { break; }
                if (b == null || b.block == null) continue;

                // 库存
                arc.struct.Seq<String> its = new arc.struct.Seq<>();
                arc.struct.Seq<Integer> amts = new arc.struct.Seq<>();
                if (b.items != null) {
                    for (mindustry.type.Item it : Vars.content.items()) {
                        int cnt = b.items.get(it);
                        if (cnt > 0) { its.add(it.name); amts.add(cnt); }
                    }
                }
                String[] iNames = its.toArray(String.class);
                int[] iAmts = new int[amts.size];
                for (int k = 0; k < iAmts.length; k++) iAmts[k] = amts.get(k);

                // 液体
                arc.struct.Seq<String> lqs = new arc.struct.Seq<>();
                arc.struct.Seq<Float> lAmts = new arc.struct.Seq<>();
                if (b.liquids != null) {
                    for (mindustry.type.Liquid lq : Vars.content.liquids()) {
                        float lv = b.liquids.get(lq);
                        if (lv > 0.01f) { lqs.add(lq.name); lAmts.add(lv); }
                    }
                }
                String[] lNames = lqs.toArray(String.class);
                float[] lVals = new float[lAmts.size];
                for (int k = 0; k < lVals.length; k++) lVals[k] = lAmts.get(k);

                // 配置
                String cfg = null;
                try { Object c = b.config(); if (c != null) cfg = String.valueOf(c); }
                catch (Throwable ignored) { }

                // 施工进度
                boolean constructing = b instanceof mindustry.world.blocks.ConstructBlock.ConstructBuild;
                float progress = constructing
                    ? ((mindustry.world.blocks.ConstructBlock.ConstructBuild) b).progress
                    : 1f;

                // 电力连线：只在有电力模块时采集。玩家看到的激光线就是这份数据。
                float pstat = -1f;
                int[] plinks = null;
                if (b.power != null) {
                    pstat = b.power.status;
                    var lk = b.power.links;
                    if (lk != null && lk.size > 0) {
                        plinks = new int[lk.size];
                        for (int li = 0; li < lk.size; li++) plinks[li] = lk.get(li);
                    }
                }

                // 物流接口：这一格能从哪收、往哪推。单独 try —— 判定失败
                // 不该让整张快照挂掉。
                float fogR = 0f;
                try { fogR = b.fogRadius(); } catch (Throwable ignored) { }

                int[] acceptsFrom = null, sendsTo = null;
                try {
                    acceptsFrom = conveyorInputs(b);
                    sendsTo = conveyorOutput(b);
                    if (sendsTo == null) sendsTo = drillOutputs(b);
                } catch (Throwable ignored) { }

                list.add(new BuildInfo(
                    b.id, b.tileX(), b.tileY(), b.team.id, b.block.name,
                    b.health, b.maxHealth, b.enabled, b.efficiency,
                    iNames, iAmts, lNames, lVals, cfg, constructing, progress,
                    b.rotation, pstat, plinks, fogR, acceptsFrom, sendsTo));
            }
        }
        return list.toArray(BuildInfo.class);
    }

    // ---------------------------------------------------------------- 物流接口

    /**
     * relativeTo 编码 → 格偏移（Tile.java:95-101）。
     *
     *     0 = 西 (x-1)   1 = 北 (y-1)   2 = 东 (x+1)   3 = 南 (y+1)
     *
     * 别按屏幕直觉读：y 向下增长，编码 3 是屏幕**下方**。
     * rotation 用同一套编码，于是 rot 0 = 面朝东、1 = 面朝南、2 = 面朝西、3 = 面朝北。
     * （引擎自己在 Conveyor.java:166 的注释里把 1 写成「北」，那是照抄 Rotation.top
     *   这个枚举名 —— 枚举的 top 指向屏幕下方，别信它。）
     */
    private static final int[] REL_DX = {-1, 0, 1, 0};
    private static final int[] REL_DY = {0, -1, 0, 1};

    /** 传送带的接货口：背面 + 两侧，只保留该方位上真有建筑的格。正面拒收，不列。 */
    private static int[] conveyorInputs(mindustry.gen.Building b) {
        if (!(b instanceof mindustry.world.blocks.distribution.Conveyor.ConveyorBuild)) return null;
        arc.struct.IntSeq seq = new arc.struct.IntSeq();
        int x = b.tileX(), y = b.tileY(), r = b.rotation;
        for (int rel = 0; rel < 4; rel++) {
            if (Math.abs(rel - r) == 2) continue;               // 正面：拒收
            int nx = x + REL_DX[rel], ny = y + REL_DY[rel];
            if (Vars.world.build(nx, ny) == null) continue;     // 那格是空地
            seq.add(arc.math.geom.Point2.pack(nx, ny));
        }
        return seq.size == 0 ? null : seq.toArray();
    }

    /** 传送带的正面格。即使空着也返回 —— 那是它的朝向。 */
    private static int[] conveyorOutput(mindustry.gen.Building b) {
        if (!(b instanceof mindustry.world.blocks.distribution.Conveyor.ConveyorBuild)) return null;
        int rel = (b.rotation + 2) % 4;
        return new int[]{ arc.math.geom.Point2.pack(b.tileX() + REL_DX[rel],
                                                    b.tileY() + REL_DY[rel]) };
    }

    /**
     * 钻机实际能推货出去的邻格。
     *
     * 钻机输出不受 rotation 控制（Drill.java:289 的 dump 向所有相邻接收方推），
     * 所以这不是推导而是实测：拿它脚下占多数的那个矿当探针，逐个邻格调 acceptItem。
     * footprint 退化成一份「谁在接货」的真实清单。
     */
    private static int[] drillOutputs(mindustry.gen.Building b) {
        if (!(b instanceof mindustry.world.blocks.production.Drill.DrillBuild db)) return null;

        arc.struct.IntSeq seq = new arc.struct.IntSeq();
        int s = db.block.size;
        // 多格方块的坐标是**中心**（实测：core-nucleus 覆盖 (287,102)-(291,106)，
        // 而 /buildings 报 (289,104)）。换算到左上角要用 block.sizeOffset ——
        // 那是引擎自己的偏移（Tile.java:485 的 getLinkedTiles 就用它），
        // 别手算 -((size-1)/2)：2x2 时两者都是 0、看着一样，3x3 以上才分道扬镳。
        int off = db.block.sizeOffset;
        int x0 = db.tileX() + off, y0 = db.tileY() + off;
        for (int i = 0; i < s; i++) {
            addNeighbour(seq, x0 + i, y0 - 1);                  // 上
            addNeighbour(seq, x0 + i, y0 + s);                  // 下
            addNeighbour(seq, x0 - 1, y0 + i);                  // 左
            addNeighbour(seq, x0 + s, y0 + i);                  // 右
        }
        return seq.size == 0 ? null : seq.toArray();
    }

    /**
     * 只列**有建筑**的方位，不判「此刻能不能收」。
     *
     * 原先这里调的是 `acceptItem`，读数会来回抖：传送带入口被自己身上的货占住时
     * `minitem <= 0.7`（Conveyor.java:358 的侧面条件），判定立刻变 false，
     * sendsTo 就空了 —— 而钻机其实一直在往那条带子上推货。实测撞到过：
     * 带子上明明堆着 2 个铜，sendsTo 却是 null。
     *
     * 「这台钻机挨着哪几个邻居」是**结构事实**，稳定、可缓存、能拿来布线；
     * 「此刻这一格收不收」是瞬时状态，要判也该由读的人结合 items 自己判。
     */
    private static void addNeighbour(arc.struct.IntSeq seq, int x, int y) {
        if (Vars.world.build(x, y) == null) return;
        seq.add(arc.math.geom.Point2.pack(x, y));
    }

    // ---------------------------------------------------------------- diff

    private static final arc.struct.IntSet knownUnits = new arc.struct.IntSet();
    private static final arc.struct.IntSet knownBuilds = new arc.struct.IntSet();
    private static boolean diffPrimed = false;

    /**
     * 用快照差分补齐引擎事件的缺口。
     *
     * 为什么需要：UnitCreateEvent 只在 UnitSpawnAbility / PayloadSource /
     * Reconstructor / UnitAssembler / UnitFactory 这五处触发 —— **核心生产单位
     * 和直接 spawn 都不触发**。若只依赖引擎事件，AI 不会知道敌方出现了新单位。
     *
     * 这里只补引擎不覆盖的那两类（unitAppear / unitGone），名字刻意与引擎的
     * unitCreate / unitDestroy 区分，避免语义混淆。
     *
     * 首次调用只建立基线、不产生事件，否则开局会把全图单位报一遍。
     */
    private static void diffEntities(UnitInfo[] units, BuildInfo[] builds) {
        try {
            if (!diffPrimed) {
                knownUnits.clear();
                knownBuilds.clear();
                for (UnitInfo u : units) knownUnits.add(u.id);
                for (BuildInfo b : builds) knownBuilds.add(b.x * 100000 + b.y);
                diffPrimed = true;
                return;
            }

            arc.struct.IntSet nowUnits = new arc.struct.IntSet();
            for (UnitInfo u : units) {
                nowUnits.add(u.id);
                if (!knownUnits.contains(u.id)) {
                    EventLog.addExternal("unitAppear", u.team, u.x, u.y,
                        new Json.Obj().put("unit", u.id).put("type", u.type)
                                      .put("health", u.health)
                                      .toString().replaceAll("^\\{|\\}$", ""));
                }
            }
            for (UnitInfo u : units) {
                if (knownUnits.contains(u.id)) continue;
                // 已在上面报过
            }
            // 消失的单位
            for (var it = knownUnits.iterator(); it.hasNext; ) {
                int id = it.next();
                if (!nowUnits.contains(id)) {
                    EventLog.addExternal("unitGone", -1, Float.NaN, Float.NaN,
                        new Json.Obj().put("unit", id).toString().replaceAll("^\\{|\\}$", ""));
                }
            }
            knownUnits.clear();
            knownUnits.addAll(nowUnits);

            arc.struct.IntSet nowBuilds = new arc.struct.IntSet();
            for (BuildInfo b : builds) {
                int key = b.x * 100000 + b.y;
                nowBuilds.add(key);
                if (!knownBuilds.contains(key)) {
                    EventLog.addExternal("buildAppear", b.team, b.x * Vars.tilesize, b.y * Vars.tilesize,
                        new Json.Obj().put("x", b.x).put("y", b.y).put("block", b.block)
                                      .toString().replaceAll("^\\{|\\}$", ""));
                }
            }
            for (var it = knownBuilds.iterator(); it.hasNext; ) {
                int key = it.next();
                if (!nowBuilds.contains(key)) {
                    EventLog.addExternal("buildGone", -1, (key / 100000) * Vars.tilesize,
                        (key % 100000) * Vars.tilesize,
                        new Json.Obj().put("x", key / 100000).put("y", key % 100000)
                                      .toString().replaceAll("^\\{|\\}$", ""));
                }
            }
            knownBuilds.clear();
            knownBuilds.addAll(nowBuilds);
        } catch (Throwable t) {
            AIArena.log("entity diff failed: " + t);
        }
    }

    /** 换图时重置差分基线。 */
    public static void resetDiff() {
        knownUnits.clear();
        knownBuilds.clear();
        diffPrimed = false;
    }

    public static State get() { return current; }
}
