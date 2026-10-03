package aiarena;

import mindustry.gen.Player;
import mindustry.game.Team;

/**
 * 影子 Player 池。
 *
 * 为什么需要它（DESIGN.md 4.7）：
 *
 *   引擎里所有需要 Player 参数的 @Remote 方法（commandUnits / setUnitCommand /
 *   setUnitStance / commandBuilding / requestItem / transferInventory）在服务器侧
 *   都没有本地 Player 可用。而 Administration.allowAction 的实现是：
 *
 *       public boolean allowAction(Player player, ActionType type, ...){
 *           //some actions are done by the server (null player) and thus are always allowed
 *           if(player == null) return true;          // ← 传 null 直接跳过全部校验
 *           ...
 *       }
 *
 *   所以要么传 null（放弃权限校验），要么造一个影子 Player（校验生效）。
 *   本类选择后者 —— 这样 AI 与将来的真人玩家走同一套规则。
 *
 * P0 实测结论：
 *   - Player.create() + add() 会进入 Groups.player，remove() 后回 0
 *   - team().data().players.size 保持 0 —— 不污染胜负判定与死队清理
 *   - player.set(x, y) 生效，可用于满足引擎自带的 within(...) 距离检查
 *
 * 线程约定：所有方法必须在游戏主线程调用（Player 的增删不是线程安全的）。
 */
public final class Shadow {

    private static final java.util.Map<Integer, Player> pool = new java.util.HashMap<>();

    private Shadow() {}

    /** 取得（必要时创建）指定队伍的影子 Player。 */
    public static Player of(Team team) {
        if (team == null) return null;

        Player p = pool.get(team.id);
        if (p == null || p.dead() && !p.isAdded()) {
            p = Player.create();
            p.team(team);
            p.name = "AI_" + team.name;
            p.add();
            pool.put(team.id, p);
        }
        return p;
    }

    /**
     * 取得影子 Player 并把它的位置设到给定坐标。
     *
     * 引擎自带的距离检查依赖这个位置，例如 InputHandler.requestItem 里的
     * player.within(build, itemTransferRange)（itemTransferRange = 220f ≈ 27.5 格）。
     * 因此调用这类方法前必须先把影子挪到操作点附近。
     */
    public static Player at(Team team, float x, float y) {
        Player p = of(team);
        if (p != null) p.set(x, y);
        return p;
    }

    /** 把影子挪到某个建筑旁边。 */
    public static Player at(Team team, mindustry.gen.Building build) {
        if (build == null) return of(team);
        return at(team, build.x, build.y);
    }

    /** 把影子挪到某个单位旁边。 */
    public static Player at(Team team, mindustry.gen.Unit unit) {
        if (unit == null) return of(team);
        return at(team, unit.x, unit.y);
    }

    /** 清空池并移除所有影子 Player。换图或重置对局时调用。 */
    public static void clear() {
        for (Player p : pool.values()) {
            if (p != null) p.remove();
        }
        pool.clear();
    }

    /** 当前影子数量（诊断用）。 */
    public static int size() { return pool.size(); }
}
