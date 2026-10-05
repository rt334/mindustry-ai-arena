#!/usr/bin/env python3
"""让 /command?action=move 真的能移动单位。

实测（drive/compare-move-order.py，同一目标、同一单位 #219 gamma）：
    /command?action=move  → 应答 "commanded 1 unit(s) to position"，位移 0.00 格
    /control?op=order     → 应答 "moving gamma id=219 toward (271,118)"，位移 23.14 格

原因：两条路不同。
    command()  用 Call.commandUnits(...)  —— 那是喂给 CommandAI 的引擎 RPC
    order()    写 moveOrders，由 tickMoveOrders 每帧直接改 u.vel 与朝向，绕过控制器

而本竞技场里**每个单位都被影子 Player 持有**（controller=Player#218），
玩家持有的单位不理会 AI 指挥 —— 所以 command 那条链路整段是空的，
返回成功但什么都不会发生。

修法：位置类指令额外挂上 moveOrders，复用已验证有效的那条路。
引擎 RPC 保留（无害），它管的是 AI 控制器单位的场景。
"""
import pathlib
import sys

C = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Commander.java")

OLD = """        mindustry.gen.Call.commandUnits(shadow, ids, buildTarget, unitTarget, posTarget, queue, true);
        return Actor.Result.ok("commanded " + ids.length + " unit(s) to " + kind);"""

NEW = """        mindustry.gen.Call.commandUnits(shadow, ids, buildTarget, unitTarget, posTarget, queue, true);

        // ⚠ 光靠上面那条 RPC 没用。它是喂给 CommandAI 的，而本竞技场里
        // **每个单位都被影子 Player 持有**（controller=Player#NNN）——
        // 玩家持有的单位不理会 AI 指挥。实测同目标同单位：
        //   /command?action=move → 应答成功，位移 0.00 格
        //   /control?op=order    → 位移 23.14 格
        // 差别在于 order 走 moveOrders，由 tickMoveOrders 每帧直接改 u.vel
        // 与朝向，绕过控制器。位置类指令这里额外挂上它。
        if (kind == TargetKind.position) {
            long until = System.currentTimeMillis() + 20_000L;
            for (int id : ids) moveOrders.put(id, new MoveOrder(team, tx, ty, until));
        }
        return Actor.Result.ok("commanded " + ids.length + " unit(s) to " + kind);"""


def main():
    t = C.read_text(encoding="utf-8")
    n = t.count(OLD)
    if n != 1:
        print(f"!! 锚点 {n} 次（期望 1），未写盘")
        return 1
    C.write_text(t.replace(OLD, NEW), encoding="utf-8")
    print("Commander：move 现在会真的驱动单位")
    return 0


if __name__ == "__main__":
    sys.exit(main())
