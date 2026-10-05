package aiarena;

import mindustry.Vars;
import mindustry.game.Team;
import mindustry.gen.Building;
import mindustry.type.Item;
import mindustry.type.Liquid;
import mindustry.world.blocks.distribution.Conveyor;
import mindustry.world.blocks.production.Drill;
import mindustry.world.blocks.production.GenericCrafter;
import mindustry.world.blocks.units.UnitFactory;
import mindustry.world.consumers.*;

import java.util.HashMap;
import java.util.Map;

/**
 * 产线报警。
 *
 * 回答四类问题，都带**具体位置和原因**：
 *
 *   1. 传送带堵了        beltStall      —— 压着什么、出料侧是什么、它收不收
 *   2. 矿机满仓出不去    drillBlocked   —— 满的是什么、出料侧是什么
 *   3. 工厂停摆          factoryBlocked —— 有料但不干活（通常是产物堵住）
 *   4. 缺原料            missingInput   —— **明确列出缺哪几样、各缺多少**
 *
 * 第 4 条是这一版的重点。之前只能看到「冶炼厂 items={}」这种结果，
 * 得人肉对照配方才知道缺什么；现在直接告诉你 `[{"kind":"item","item":"coal","need":1,"have":0}]`。
 *
 * 判据用引擎自己的状态，不自己造轮子：
 *   传送带   clogHeat  —— 1/60 每帧涨落，涨到 1 约等于「堵了 1 秒」（Conveyor.java:291）
 *   矿机     items.total() >= itemCapacity
 *   工厂     shouldConsume() 为真但 efficiency 为 0（= 该干却干不了）
 *   缺料     遍历 block.consumers 逐项比对库存 / 电力
 */
public final class StallWatch {

    /** clogHeat 超过这个值就算堵住。1/60 每帧涨，0.98 ≈ 1 秒。 */
    private static final float CLOG_THRESHOLD = 0.98f;

    /** 同一格最短重复报警间隔（毫秒）。 */
    private static final long REPORT_INTERVAL_MS = 10_000L;

    /** 判定「持续 1 秒」用的时长。 */
    private static final long SUSTAIN_MS = 1_000L;

    private static final Map<String, Long> lastReport = new HashMap<>();
    /** 处于异常状态的方块，按 "x,y" 索引 -> 起始毫秒。 */
    private static final Map<String, Long> stalledSince = new HashMap<>();
    /** 每个方块的异常类型，用于状态变化时重置计时。 */
    private static final Map<String, String> stalledKind = new HashMap<>();

    private static volatile String lastSnapshot = "[]";

    private StallWatch() {}

    public static void clear() {
        lastReport.clear();
        stalledSince.clear();
        stalledKind.clear();
        lastSnapshot = "[]";
        planProgress.clear();
        planStuckSince.clear();
        unitPos.clear();
    }

    // ---------------------------------------------------------------- 计划停滞

    /** key = "unitId@x,y" -> 上次看到的进度（0~1）。 */
    private static final Map<String, Float> planProgress = new HashMap<>();
    /** key = "unitId@x,y" -> 进度**首次**不再变化的毫秒时刻。 */
    private static final Map<String, Long> planStuckSince = new HashMap<>();
    /** unitId -> [x, y]，判断建造单位自己有没有在动。 */
    private static final Map<Integer, float[]> unitPos = new HashMap<>();

    /**
     * 跟踪建造计划有没有卡住。
     *
     * 判据是**进度是否还在变** —— 同一个 progress 连续保持才算停滞，
     * 和 clogHeat 那套一样用的是状态而不是时长。真人判断「卡住了」也是这么看：
     * 单位站在原地不动、方块迟迟不出现。
     *
     * 动机：队列卡死时 AI 只能看到一个不变的计划数，既不知道卡在哪一格、
     * 也不知道卡了多久 —— 而这两件事抬眼就能看见。
     */
    /** 建造单位位置变化超过这个距离（格）就算「在动」。 */
    private static final float MOVING_EPS = 0.5f;

    public static void updatePlans() {
        long now = System.currentTimeMillis();
        java.util.HashSet<String> seen = new java.util.HashSet<>();
        java.util.HashSet<Integer> aliveUnits = new java.util.HashSet<>();

        for (mindustry.gen.Unit u : mindustry.gen.Groups.unit) {
            if (u == null) continue;
            aliveUnits.add(u.id);

            // 这个单位自己有没有在动？走路中的单位不算「卡住」——
            // 它只是还没走到工地。
            float[] pp = unitPos.get(u.id);
            boolean moved = pp == null
                || Math.abs(pp[0] - u.x) > MOVING_EPS
                || Math.abs(pp[1] - u.y) > MOVING_EPS;
            unitPos.put(u.id, new float[]{u.x, u.y});

            if (u.plans == null) continue;
            for (mindustry.entities.units.BuildPlan plan : u.plans) {
                if (plan == null) continue;
                String key = u.id + "@" + plan.x + "," + plan.y;
                seen.add(key);

                float prog = plan.progress;
                Building tb = Vars.world.build(plan.x, plan.y);
                if (tb instanceof mindustry.world.blocks.ConstructBlock.ConstructBuild cb) {
                    prog = cb.progress;          // 已在施工的格子，进度以它为准
                }

                // 单位在走动就一律重置计时：进度为 0 是「还没开工」，不是停滞
                Float prev = planProgress.get(key);
                boolean progressed = prev != null && Math.abs(prev - prog) > 1e-4f;
                planProgress.put(key, prog);

                if (moved || progressed) {
                    planStuckSince.remove(key);  // 有动作，重新计时
                } else if (!planStuckSince.containsKey(key)) {
                    planStuckSince.put(key, now); // 单位和进度都停住了
                }
            }
        }

        // 计划消失（建完了、被替换了、被清了）就丢掉
        planProgress.keySet().removeIf(k -> !seen.contains(k));
        planStuckSince.keySet().removeIf(k -> !seen.contains(k));
        unitPos.keySet().removeIf(id -> !aliveUnits.contains(id));
    }

    /** 该计划已经多久没动了（毫秒）；没停滞返回 0。 */
    public static long planStuckMillis(int unitId, int x, int y) {
        Long since = planStuckSince.get(unitId + "@" + x + "," + y);
        return since == null ? 0L : System.currentTimeMillis() - since;
    }

    /**
     * 扫描节流。
     *
     * 原先是每帧（60 Hz）遍历所有队伍的所有建筑，并且**给每栋楼拼一个
     * String key**（`b.tileX() + "," + b.tileY()`）、每帧新建两个 HashSet。
     * 建筑规模一大，光是字符串分配就是主要开销，而建筑状态根本不会
     * 以 60 Hz 变化。
     *
     * 判定阈值是 SUSTAIN_MS = 1000ms，10 Hz 采样的时间分辨率完全够用
     * （最多 100ms 的判定延迟）。
     */
    private static final double SCAN_INTERVAL_TICKS = 6;   // ≈10 Hz @ 60 FPS
    private static double lastScanTick = -1;

    /** 由主线程每帧调用（内部节流到 10 Hz）。 */
    public static void update() {
        try {
            if (Vars.state == null || !Vars.state.isGame()) return;

            double tickNow = Vars.state.tick;
            if (lastScanTick >= 0 && tickNow - lastScanTick < SCAN_INTERVAL_TICKS) return;
            lastScanTick = tickNow;

            long now = System.currentTimeMillis();
            StringBuilder snap = new StringBuilder("[");
            boolean first = true;
            // ⚠ 两个集合必须分开：
            //   seen  本帧出现异常的方块（用于清理计时器）
            //   alive 已达阈值的方块（用于输出）
            // 早先把清理挂到 alive 上，导致「还没到 1 秒」的条目每帧都被删掉、
            // 计时归零，永远涨不到阈值 —— 整个模块静默失效。
            java.util.HashSet<String> seen = new java.util.HashSet<>();
            java.util.HashSet<String> alive = new java.util.HashSet<>();

            for (var td : Vars.state.teams.present) {
                Team team = td.team;
                if (team == null || team == Team.derelict) continue;

                for (Building b : td.buildings) {
                    if (b == null || b.block == null) continue;

                    String key = b.tileX() + "," + b.tileY();
                    String kind = classify(b);
                    if (kind == null) {
                        stalledSince.remove(key);
                        stalledKind.remove(key);
                        continue;
                    }

                    // 类型变了就重新计时（例如「缺料」变成「产物堵住」）
                    String prevKind = stalledKind.get(key);
                    if (prevKind == null || !prevKind.equals(kind)) {
                        stalledSince.put(key, now);
                        stalledKind.put(key, kind);
                    }

                    long since = stalledSince.getOrDefault(key, now);
                    long held = now - since;
                    seen.add(key);
                    if (held < SUSTAIN_MS) continue;      // 不到 1 秒不算

                    alive.add(key);
                    double secs = held / 1000.0;

                    if (!first) snap.append(',');
                    first = false;
                    snap.append(entryJson(b, team, kind, secs));

                    Long last = lastReport.get(key);
                    if (last == null || now - last >= REPORT_INTERVAL_MS) {
                        lastReport.put(key, now);
                        EventLog.add(kind, team.id, b.x, b.y,
                            "\"block\":" + Json.str(b.block.name)
                            + ",\"rotation\":" + b.rotation
                            + ",\"items\":" + itemsJson(b)
                            + ",\"heldSeconds\":" + (float) (Math.round(secs * 10) / 10.0)
                            + ",\"outputSide\":" + Json.str(sideName(b, b.rotation))
                            + ",\"outputAccepts\":" + sideAccepts(b, b.rotation)
                            + ",\"missing\":" + missingJson(b));
                    }
                }
            }
            snap.append(']');
            lastSnapshot = snap.toString();

            // 清掉已经恢复的条目（用 seen，不是 alive）
            stalledSince.keySet().removeIf(k -> !seen.contains(k));
            stalledKind.keySet().removeIf(k -> !seen.contains(k));

        } catch (Throwable t) {
            arc.util.Log.err("stall watch failed: " + t);
        }
    }

    /**
     * 判断一个方块现在处于什么异常状态。
     * @return 报警类型；null 表示正常
     */
    private static String classify(Building b) {
        // ---- 需要电但没电：屏幕上就是空/红的电力条 ----
        //
        // 放在最前面：这是最根本的原因，也是肉眼最先看到的。
        // 发电机不消费电（它们输出电），所以不会被这条命中。
        if (needsPower(b) && b.power != null && b.power.status <= 0.001f) {
            int links = (b.power.links == null) ? 0 : b.power.links.size;
            // 没接任何线 / 接了线但没电 —— 两种都是玩家看得见的
            return links == 0 ? "powerUnconnected" : "powerStarved";
        }

        // ---- 传送带：引擎自己的 clogHeat ----
        if (b instanceof Conveyor.ConveyorBuild cb) {
            boolean hasItems = b.items != null && b.items.total() > 0;
            return (hasItems && cb.clogHeat >= CLOG_THRESHOLD) ? "beltStall" : null;
        }

        // ---- 矿机：满仓推不出去 ----
        if (b instanceof Drill.DrillBuild db) {
            if (b.items != null && b.items.total() >= b.block.itemCapacity) {
                return "drillBlocked";
            }
            return null;
        }

        // ---- 工厂 / 冶炼厂：该干却干不了 ----
        if (b instanceof GenericCrafter.GenericCrafterBuild || b instanceof UnitFactory.UnitFactoryBuild) {
            // shouldConsume 为真说明「原料够、产物没满」-> 本该在生产
            // 此时 efficiency 仍为 0，只可能是被别的东西卡住（电力、产物堵塞）
            boolean wants = b.shouldConsume();
            boolean idle = b.efficiency <= 0.001f;
            if (wants && idle) {
                // 区分「缺料」和「产物堵住」：缺料时 missingJson 非空
                String miss = missingJson(b);
                return miss.equals("[]") ? "factoryBlocked" : "missingInput";
            }
            return null;
        }

        // ---- 发电机：缺燃料 ----
        if (b.block.hasPower && b.block.consumers != null) {
            boolean isGen = false;
            for (var c : b.block.consumers) {
                if (c instanceof ConsumeItemFilter || c instanceof ConsumeItems) { isGen = true; break; }
            }
            if (isGen && b.efficiency <= 0.001f) {
                String miss = missingJson(b);
                return miss.equals("[]") ? null : "missingInput";
            }
        }

        return null;
    }

    /**
     * 这个方块是否**消费**电。
     *
     * 不能用 Block.consumesPower —— 它默认就是 true（Block.java:53），
     * 每个方块都会命中。得看它有没有注册 ConsumePower。
     */
    private static boolean needsPower(Building b) {
        if (b.block.consumers == null) return false;
        for (var c : b.block.consumers) {
            if (c instanceof ConsumePower) return true;
        }
        return false;
    }

    /**
     * 列出这个方块当前缺什么。**这是本模块最有用的输出。**
     *
     * 逐项遍历 block.consumers：
     *   ConsumeItems       固定配方 -> 比对每种物品的数量
     *   ConsumeItemFilter  燃料过滤器（发电机）-> 检查有没有任何被接受的物品
     *   ConsumeLiquid(s)   液体
     *   ConsumePower       电力（用 power.status 判断）
     */
    private static String missingJson(Building b) {
        StringBuilder sb = new StringBuilder("[");
        boolean f = true;
        // 去重：同一个 block 可能有多个同类 consumer（例如燃烧发电机有两个
        // ConsumeItemFilter），不去重就会把同一条「没燃料」报两遍。
        java.util.HashSet<String> seenKeys = new java.util.HashSet<>();
        try {
            if (b.block.consumers == null) return "[]";

            for (var c : b.block.consumers) {
                if (c instanceof ConsumeItems ci) {
                    for (var st : ci.items) {
                        int have = b.items == null ? 0 : b.items.get(st.item);
                        if (have < st.amount) {
                            if (!seenKeys.add("item:" + st.item.name)) continue;
                            if (!f) sb.append(',');
                            f = false;
                            sb.append(new Json.Obj().put("kind", "item")
                                .put("item", st.item.name)
                                .put("need", st.amount).put("have", have).toString());
                        }
                    }
                } else if (c instanceof ConsumeItemFilter cif) {
                    // 过滤器没有固定配方 —— 只能说「一个被接受的物品都没有」
                    int total = 0;
                    for (Item it : Vars.content.items()) {
                        try {
                            if (cif.filter.get(it) && b.items != null && b.items.get(it) > 0) {
                                total += b.items.get(it);
                            }
                        } catch (Throwable ignored) {}
                    }
                    if (total == 0) {
                        if (!seenKeys.add("item-filter")) continue;
                        if (!f) sb.append(',');
                        f = false;
                        sb.append(new Json.Obj().put("kind", "item-filter")
                            .put("note", "没有任何被接受的燃料/原料").toString());
                    }
                } else if (c instanceof ConsumeLiquid cl) {
                    float have = b.liquids == null ? 0f : b.liquids.get(cl.liquid);
                    if (have < cl.amount) {
                        if (!seenKeys.add("liquid:" + cl.liquid.name)) continue;
                        if (!f) sb.append(',');
                        f = false;
                        sb.append(new Json.Obj().put("kind", "liquid")
                            .put("liquid", cl.liquid.name)
                            .put("need", cl.amount).put("have", (float) have).toString());
                    }
                } else if (c instanceof ConsumeLiquids cls) {
                    for (var st : cls.liquids) {
                        float have = b.liquids == null ? 0f : b.liquids.get(st.liquid);
                        if (have < st.amount) {
                            if (!seenKeys.add("liquid:" + st.liquid.name)) continue;
                            if (!f) sb.append(',');
                            f = false;
                            sb.append(new Json.Obj().put("kind", "liquid")
                                .put("liquid", st.liquid.name)
                                .put("need", st.amount).put("have", (float) have).toString());
                        }
                    }
                } else if (c instanceof ConsumePower cp) {
                    float st = b.power == null ? 0f : b.power.status;
                    if (st <= 0.01f) {
                        if (!seenKeys.add("power")) continue;
                        if (!f) sb.append(',');
                        f = false;
                        sb.append(new Json.Obj().put("kind", "power")
                            .put("need", cp.usage).put("status", (float) st).toString());
                    }
                }
            }
        } catch (Throwable t) {
            sb.append(new Json.Obj().put("kind", "error").put("message", String.valueOf(t)).toString());
        }
        return sb.append(']').toString();
    }

    /** 当前所有异常方块。 */
    public static String stallsJson() {
        return lastSnapshot;
    }

    public static int stalledCount() {
        return stalledSince.size();
    }

    /**
     * 停机的直接原因 —— 一句话说清该往上游查还是往下游查。
     *
     *   starved        上游没把料送来（缺输入），**往上游查**
     *   outputBlocked  自己有料且已满仓，出料侧不收 —— **往下游查**
     *   outputRefused  出料侧不收，但自己还没满仓（刚堵上）
     *   unknown        其它情况（电力、配方等），看 missing 数组
     *
     * 判据：`efficiency == 0` 且满仓 ⇒ 输出路径不通；缺料 ⇒ 输入路径不通。
     */
    private static String causeOf(Building b, String kind) {
        if ("missingInput".equals(kind)) return "starved";
        // 电力问题既不是「上游没来货」也不是「下游不收」—— 查电网
        if ("powerUnconnected".equals(kind)) return "unpowered";
        if ("powerStarved".equals(kind)) return "underpowered";

        boolean accepts = sideAccepts(b, b.rotation);
        if (!accepts) {
            boolean full = b.block.hasItems && b.items != null
                && (b.block.itemCapacity <= 0 || b.items.total() >= b.block.itemCapacity);
            return full ? "outputBlocked" : "outputRefused";
        }
        return "unknown";
    }

    private static String entryJson(Building b, Team team, String kind, double secs) {
        return new Json.Obj()
            .put("x", b.tileX()).put("y", b.tileY())
            .put("team", team.name)
            .put("block", b.block.name)
            .put("kind", kind)
            .put("cause", causeOf(b, kind))
            .put("rotation", b.rotation)
            .putRaw("items", itemsJson(b))
            .put("efficiency", b.efficiency)
            .put("heldSeconds", (float) (Math.round(secs * 10) / 10.0))
            .put("outputSide", sideName(b, b.rotation))
            .put("outputAccepts", sideAccepts(b, b.rotation))
            .put("inputSide", sideName(b, (b.rotation + 2) % 4))
            .putRaw("missing", missingJson(b))
            .toString();
    }

    private static String itemsJson(Building b) {
        StringBuilder sb = new StringBuilder("{");
        boolean f = true;
        if (b.items != null) {
            for (Item it : Vars.content.items()) {
                int amt = b.items.get(it);
                if (amt <= 0) continue;
                if (!f) sb.append(',');
                f = false;
                sb.append(Json.str(it.name)).append(':').append(amt);
            }
        }
        return sb.append('}').toString();
    }

    private static String sideName(Building b, int dir) {
        try {
            Building n = b.nearby(dir);
            return n == null ? "air" : n.block.name;
        } catch (Throwable t) {
            return "?";
        }
    }

    private static boolean sideAccepts(Building b, int dir) {
        try {
            Building n = b.nearby(dir);
            if (n == null) return false;
            if (b.items != null) {
                for (Item it : Vars.content.items()) {
                    if (b.items.get(it) > 0) return n.acceptItem(b, it);
                }
            }
            return false;
        } catch (Throwable t) {
            return false;
        }
    }
}
