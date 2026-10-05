#!/usr/bin/env python3
"""B2：/units 给出「这个建造单位正在建哪一格、建到几成」。

原始痛点（FEATURE-REQUESTS B2）：
    「我全程只有一个 gamma，但完全不知道它建一个方块要多久、现在在哪、
      下次空闲是什么时候。/units 给了坐标，但没有『当前正在建哪个方块』。」

有这个字段，建造加速器才能精确到「建完一个就送去下一个」，
而不是按自维护的清单盲撞 —— 而那份清单会因为丢单和服务端状态对不上。
"""
import pathlib
import sys

S = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Snapshot.java")
H = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\HttpApi.java")

FIELD_OLD = """        public final float ammo;
        public final int ammoCapacity;

        UnitInfo(int id, String type, int team, float x, float y,
                 float health, float maxHealth, float rotation, boolean canBuild,
                 String[] stackItems, int[] stackAmounts, int controllerId, String command,
                 boolean shooting, float targetX, float targetY,
                 int targetId, String targetType, int targetTeam,
                 float ammo, int ammoCapacity) {"""

FIELD_NEW = """        public final float ammo;
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

        UnitInfo(int id, String type, int team, float x, float y,
                 float health, float maxHealth, float rotation, boolean canBuild,
                 String[] stackItems, int[] stackAmounts, int controllerId, String command,
                 boolean shooting, float targetX, float targetY,
                 int targetId, String targetType, int targetTeam,
                 float ammo, int ammoCapacity,
                 int buildX, int buildY, float buildProgress, String buildBlock) {"""

CTOR_OLD = """            this.ammo = ammo; this.ammoCapacity = ammoCapacity;
        }
    }"""

CTOR_NEW = """            this.ammo = ammo; this.ammoCapacity = ammoCapacity;
            this.buildX = buildX; this.buildY = buildY;
            this.buildProgress = buildProgress; this.buildBlock = buildBlock;
        }
    }"""

CAPTURE_OLD = """            out[i++] = new UnitInfo(
                u.id, u.type.name, u.team.id, u.x, u.y,
                u.health, u.maxHealth, u.rotation, u.canBuild(),
                stItems, stAmts, ctrl, cmd,
                shooting, tx, ty, tid, ttype, tteam,
                u.ammof(), u.type.ammoCapacity);"""

CAPTURE_NEW = """            // 建造队列的队首就是它下一步要建的格子（BuilderComp 按 plans.first() 推进）
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

            out[i++] = new UnitInfo(
                u.id, u.type.name, u.team.id, u.x, u.y,
                u.health, u.maxHealth, u.rotation, u.canBuild(),
                stItems, stAmts, ctrl, cmd,
                shooting, tx, ty, tid, ttype, tteam,
                u.ammof(), u.type.ammoCapacity,
                bX, bY, bProg, bBlock);"""

OUT_OLD = """                .put("rotation", u.rotation).put("canBuild", u.canBuild)
                .putRaw("stack", stack.toString());"""

OUT_NEW = """                .put("rotation", u.rotation).put("canBuild", u.canBuild)
                .putRaw("stack", stack.toString());

            // 正在建哪一格。轮询这个字段的 progress 就能知道它还要多久、
            // 或者是不是卡住了（progress 长时间不动）。
            if (u.buildX >= 0) {
                o.putRaw("buildingAt", new Json.Obj()
                    .put("x", u.buildX).put("y", u.buildY)
                    .put("progress", u.buildProgress)
                    .put("block", u.buildBlock == null ? "" : u.buildBlock)
                    .toString());
            }"""

JOBS = [
    (S, [(FIELD_OLD, FIELD_NEW, "UnitInfo 加 buildX/Y/progress/block"),
         (CTOR_OLD, CTOR_NEW, "构造函数赋值"),
         (CAPTURE_OLD, CAPTURE_NEW, "采集队首计划"),
         ]),
    (H, [(OUT_OLD, OUT_NEW, "visibleUnits 输出 buildingAt")]),
]


def main():
    bad = []
    for path, rules in JOBS:
        text = path.read_text(encoding="utf-8")
        print(f"  {path.name}")
        for old, new, label in rules:
            n = text.count(old)
            if n != 1:
                bad.append(f"{path.name}: {n} 次命中 -> {label}")
                print(f"      !! {n} 次  {label}")
                continue
            text = text.replace(old, new)
            print(f"      1 处  {label}")
        path.write_text(text, encoding="utf-8")
    print()
    if bad:
        print("有问题：")
        for b in bad:
            print("  " + b)
        return 1
    print("B2 已落地")
    return 0


if __name__ == "__main__":
    sys.exit(main())
