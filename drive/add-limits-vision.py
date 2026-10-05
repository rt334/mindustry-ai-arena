#!/usr/bin/env python3
"""A6 + 补4：把接口上限和视野半径暴露出来。

A6（部分已做）：/map 超限的 400 响应体里已经写明「max 4096 — use cursor」，
    缺的是「不用试探就知道上限」。这里在 /state 给一份 limits。
补4：403 的 body 里已经写明 "target tile is not visible to team X"，
    缺的是「提前知道能看多远」。这里给每个实体的 fogRadius 和全局 maxRadius。

视野半径是 fogRadius，不是 buildRange —— 后者是建造范围（UnitType.buildRange），
两回事。来源：FogControl.java:290 用 unit.type.fogRadius、
:186 用 build.fogRadius()。
"""
import pathlib
import sys

S = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Snapshot.java")
H = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\HttpApi.java")

# ---------------- Snapshot: BuildInfo ----------------

BI_OLD = """        public final int[] acceptsFrom;"""

BI_NEW = """        /**
         * 这个建筑的视野半径（`build.fogRadius()`）。
         *
         * 对等性：视野范围是玩家能直接看到的东西 —— 屏幕上雾的范围就是它决定的。
         * 注意这**不是**建造范围（那是 UnitType.buildRange），两回事。
         */
        public final float fogRadius;

        public final int[] acceptsFrom;"""

BI_CTOR_OLD = """                  int rotation, float powerStatus, int[] powerLinks,
                  int[] acceptsFrom, int[] sendsTo) {"""

BI_CTOR_NEW = """                  int rotation, float powerStatus, int[] powerLinks,
                  float fogRadius, int[] acceptsFrom, int[] sendsTo) {"""

BI_ASSIGN_OLD = """            this.acceptsFrom = acceptsFrom;
            this.sendsTo = sendsTo;
        }"""

BI_ASSIGN_NEW = """            this.fogRadius = fogRadius;
            this.acceptsFrom = acceptsFrom;
            this.sendsTo = sendsTo;
        }"""

BI_CAP_OLD = """                int[] acceptsFrom = null, sendsTo = null;
                try {"""

BI_CAP_NEW = """                float fogR = 0f;
                try { fogR = b.fogRadius(); } catch (Throwable ignored) { }

                int[] acceptsFrom = null, sendsTo = null;
                try {"""

BI_CALL_OLD = """                    b.rotation, pstat, plinks, acceptsFrom, sendsTo));"""

BI_CALL_NEW = """                    b.rotation, pstat, plinks, fogR, acceptsFrom, sendsTo));"""

# ---------------- Snapshot: UnitInfo ----------------

UI_OLD = """        /** 正在建什么方块；构造中该格可能是 ConstructBlock，所以取计划里的目标。 */
        public final String buildBlock;"""

UI_NEW = """        /** 正在建什么方块；构造中该格可能是 ConstructBlock，所以取计划里的目标。 */
        public final String buildBlock;

        /** 这个单位的视野半径（`u.type.fogRadius`）。 */
        public final float fogRadius;"""

UI_CTOR_OLD = """                 int buildX, int buildY, float buildProgress, String buildBlock) {"""

UI_CTOR_NEW = """                 int buildX, int buildY, float buildProgress, String buildBlock,
                 float fogRadius) {"""

UI_ASSIGN_OLD = """            this.buildProgress = buildProgress; this.buildBlock = buildBlock;
        }"""
UI_ASSIGN_NEW = """            this.buildProgress = buildProgress; this.buildBlock = buildBlock;
            this.fogRadius = fogRadius;
        }
"""

UI_CAP_OLD = """            out[i++] = new UnitInfo(
                u.id, u.type.name, u.team.id, u.x, u.y,
                u.health, u.maxHealth, u.rotation, u.canBuild(),
                stItems, stAmts, ctrl, cmd,
                shooting, tx, ty, tid, ttype, tteam,
                u.ammof(), u.type.ammoCapacity,
                bX, bY, bProg, bBlock);"""

UI_CAP_NEW = """            float fogR = 0f;
            try { fogR = u.type.fogRadius; } catch (Throwable ignored) { }

            out[i++] = new UnitInfo(
                u.id, u.type.name, u.team.id, u.x, u.y,
                u.health, u.maxHealth, u.rotation, u.canBuild(),
                stItems, stAmts, ctrl, cmd,
                shooting, tx, ty, tid, ttype, tteam,
                u.ammof(), u.type.ammoCapacity,
                bX, bY, bProg, bBlock, fogR);"""

# ---------------- HttpApi ----------------

STATE_OLD = """        data.put("snapshotFresh", s.heavyFresh);
        if (seeAll) data.put("view", "all");
        else if (myTeam >= 0) data.put("view", Team.get(myTeam).name);"""

STATE_NEW = """        data.put("snapshotFresh", s.heavyFresh);
        if (seeAll) data.put("view", "all");
        else if (myTeam >= 0) data.put("view", Team.get(myTeam).name);

        // 接口自身的上限。写在响应里，免得靠反复试探才知道边界在哪。
        data.putRaw("limits", new Json.Obj()
            .put("mapWindowTiles", MAX_MAP_TILES)
            .put("batchMax", Operations.MAX_BATCH)
            .put("plansPerUnit", Operations.MAX_PLANS_PER_UNIT)
            .toString());

        // 视野：每个视野源的位置与半径。fogRadius 才是「能看多远」，
        // 不是 UnitType.buildRange（那是建造范围）。
        float maxR = 0f;
        StringBuilder vs = new StringBuilder("[");
        boolean vf = true;
        for (Snapshot.UnitInfo u : s.units) {
            if (u.team != myTeam && !seeAll) continue;
            if (u.fogRadius <= 0f) continue;
            if (u.fogRadius > maxR) maxR = u.fogRadius;
            if (!vf) vs.append(',');
            vf = false;
            vs.append(new Json.Obj().put("kind", "unit").put("id", u.id)
                .put("x", (int) (u.x / 8f)).put("y", (int) (u.y / 8f))
                .put("radius", u.fogRadius).toString());
        }
        for (Snapshot.BuildInfo b : s.builds) {
            if (b.team != myTeam && !seeAll) continue;
            if (b.fogRadius <= 0f) continue;
            if (b.fogRadius > maxR) maxR = b.fogRadius;
            if (!vf) vs.append(',');
            vf = false;
            vs.append(new Json.Obj().put("kind", "building").put("x", b.x).put("y", b.y)
                .put("radius", b.fogRadius).toString());
        }
        vs.append(']');
        data.putRaw("vision", new Json.Obj()
            .put("maxRadius", maxR).putRaw("sources", vs.toString()).toString());"""

UNITS_OUT_OLD = """            if (u.buildX >= 0) {"""
UNITS_OUT_NEW = """            if (u.fogRadius > 0f) o.put("fogRadius", u.fogRadius);

            if (u.buildX >= 0) {"""

BUILDS_OUT_OLD = """            if (b.config != null) o.put("config", b.config);"""
BUILDS_OUT_NEW = """            if (b.fogRadius > 0f) o.put("fogRadius", b.fogRadius);
            if (b.config != null) o.put("config", b.config);"""

JOBS = [
    (S, [
        (BI_OLD, BI_NEW, "BuildInfo 加 fogRadius 字段"),
        (BI_CTOR_OLD, BI_CTOR_NEW, "BuildInfo 构造签名"),
        (BI_ASSIGN_OLD, BI_ASSIGN_NEW, "BuildInfo 赋值"),
        (BI_CAP_OLD, BI_CAP_NEW, "建筑采集 fogRadius"),
        (BI_CALL_OLD, BI_CALL_NEW, "建筑构造调用"),
        (UI_OLD, UI_NEW, "UnitInfo 加 fogRadius 字段"),
        (UI_CTOR_OLD, UI_CTOR_NEW, "UnitInfo 构造签名"),
        (UI_ASSIGN_OLD, UI_ASSIGN_NEW, "UnitInfo 赋值"),
        (UI_CAP_OLD, UI_CAP_NEW, "单位采集 fogRadius"),
    ]),
    (H, [
        (STATE_OLD, STATE_NEW, "/state 加 limits 与 vision"),
        (UNITS_OUT_OLD, UNITS_OUT_NEW, "/units 输出 fogRadius"),
        (BUILDS_OUT_OLD, BUILDS_OUT_NEW, "/buildings 输出 fogRadius"),
    ]),
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
        print("有问题（注意上面已写盘的部分）：")
        for b in bad:
            print("  " + b)
        return 1
    print("A6 + 补4 已落地")
    return 0


if __name__ == "__main__":
    sys.exit(main())
