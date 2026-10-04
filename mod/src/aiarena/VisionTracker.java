package aiarena;

import mindustry.Vars;
import mindustry.game.Team;
import mindustry.gen.Building;
import mindustry.gen.Unit;

import java.util.*;

/**
 * 视野进出追踪。
 *
 * 回答的问题：**AI 能不能知道有单位进入了它的视线？**
 *
 * 在补这个之前：不能。`/units` 只给「此刻可见的单位」，`/events` 里也没有
 * 任何视野相关事件 —— AI 只能自己每拍拉一次列表、跟上一拍做 diff，
 * 才知道「多了个东西」。这不只是麻烦：轮询周期决定了它能多快发现，
 * 而且单位在视野边缘一闪而过时（进视野 → 出视野都在两拍之间）会被完全漏掉。
 *
 * 玩家那边不存在这个问题 —— 屏幕上出现一个敌方单位就是立刻看见。
 *
 * 所以这里做的是**和玩家屏幕等价的事**：每 tick 按队伍算出可见实体集合，
 * 和上一 tick 比，进视野的发 unitSpotted / buildingSpotted，
 * 出视野的发 unitLost / buildingLost。
 *
 * 严格按安全可见性判定（FogControl.isVisible），和 /units、/buildings 用的是
 * 同一套规则，所以不会比玩家多知道任何东西。
 *
 * 性能：按 tick 间隔跑（默认每 6 tick = 10Hz），4 队 × 几十个实体，可忽略。
 */
public final class VisionTracker {

    /** 跑一次的间隔（tick）。60fps 下 6 tick ≈ 100ms。 */
    private static final int INTERVAL_TICKS = 6;

    /** 每队上一拍可见的单位 / 建筑 id。 */
    private static final Map<Integer, Set<Integer>> prevUnits = new HashMap<>();
    private static final Map<Integer, Set<Integer>> prevBuilds = new HashMap<>();

    private static long lastTick = -1;

    private VisionTracker() {}

    /** 由主线程每帧调用。内部自己限流。 */
    public static void update() {
        try {
            if (Vars.state == null || !Vars.state.isGame()) return;
            long tick = (long) Vars.state.tick;
            if (lastTick >= 0 && tick - lastTick < INTERVAL_TICKS) return;
            lastTick = tick;

            for (var td : Vars.state.teams.present) {
                Team team = td.team;
                if (team == null || team == Team.derelict) continue;

                Set<Integer> seenU = new HashSet<>();
                Set<Integer> seenB = new HashSet<>();

                for (Unit u : mindustry.gen.Groups.unit) {
                    if (u == null || !u.isAdded()) continue;
                    if (u.team == team) continue;                 // 自己人不算「进入视野」
                    if (!safeVisible(team, u.x, u.y)) continue;
                    seenU.add(u.id);
                }
                for (Building b : mindustry.gen.Groups.build) {
                    if (b == null || !b.isAdded()) continue;
                    if (b.team == team) continue;
                    if (!safeVisible(team, b.x, b.y)) continue;
                    seenB.add(b.id);
                }

                int tid = team.id;
                Set<Integer> wasU = prevUnits.getOrDefault(tid, Collections.emptySet());
                Set<Integer> wasB = prevBuilds.getOrDefault(tid, Collections.emptySet());

                for (Integer id : seenU) {
                    if (wasU.contains(id)) continue;
                    Unit u = mindustry.gen.Groups.unit.getByID(id);
                    if (u == null) continue;
                    // 「有一个东西进入视野」是玩家能看到的；它的 id 和类型也是
                    // —— 屏幕上就是一个具名单位在动。
                    EventLog.add("unitSpotted", tid, u.x, u.y,
                        "\"unit\":" + Json.str(u.type.name)
                        + ",\"unitId\":" + u.id
                        + ",\"enemyTeam\":" + u.team.id
                        + ",\"health\":" + (int) u.health);
                }
                for (Integer id : wasU) {
                    if (seenU.contains(id)) continue;
                    EventLog.add("unitLost", tid, Float.NaN, Float.NaN,
                        "\"unitId\":" + id);
                }

                for (Integer id : seenB) {
                    if (wasB.contains(id)) continue;
                    Building b = mindustry.gen.Groups.build.getByID(id);
                    if (b == null) continue;
                    EventLog.add("buildingSpotted", tid, b.x, b.y,
                        "\"block\":" + Json.str(b.block.name)
                        + ",\"enemyTeam\":" + b.team.id
                        + ",\"health\":" + (int) b.health);
                }
                for (Integer id : wasB) {
                    if (seenB.contains(id)) continue;
                    EventLog.add("buildingLost", tid, Float.NaN, Float.NaN,
                        "\"buildId\":" + id);
                }

                prevUnits.put(tid, seenU);
                prevBuilds.put(tid, seenB);
            }
        } catch (Throwable t) {
            // 追踪失败不能影响主循环
            arc.util.Log.err("vision tracker failed: " + t);
        }
    }

    /** 换图 / 重开一局时清空，避免把上一局的 id 当成「已经看过」。 */
    public static void clear() {
        prevUnits.clear();
        prevBuilds.clear();
        lastTick = -1;
    }

    private static boolean safeVisible(Team team, float wx, float wy) {
        try {
            if (!Vars.state.rules.fog) return true;
            return Vars.fogControl.isVisible(team, wx, wy);
        } catch (Throwable t) {
            return false;
        }
    }
}
