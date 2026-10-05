#!/usr/bin/env python3
"""A8：shape=path —— 折线路径，服务端自动给每格算朝向。

原始痛点（FEATURE-REQUESTS A8）：
    「shape=line/rect/area 对『整行同向带子』很好用，但真实布线必然拐弯，
      而拐弯处每格朝向不同 —— 批量接口『所有格同一 rot』的设计正好卡在
      最需要的地方。我最后自己写了 route.py 生成折线坐标再逐格 place。」

朝向编码这里必须写死，别按屏幕直觉读：
    rotation 与 Tile.relativeTo 共用一套编码，0=东(+x) 1=南(+y) 2=西(-x) 3=北(-y)
    （Conveyor.java:357 用 `|relativeTo(源) - rotation|` 判方向，direction==0 是背面、
      direction==2 是正面。rot=0 背面在西 → 正面在东，与实机实测一致。）
"""
import pathlib
import sys

O = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Operations.java")
H = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\HttpApi.java")

# ---------------------------------------------------------------- Operations

ENUM_OLD = "    public enum Shape { point, line, rect, area, circle, outline }"

ENUM_NEW = "    public enum Shape { point, line, rect, area, circle, outline, path }"

SHAPE_CASE_OLD = """            case circle -> {
                for (int y = y1 - radius; y <= y1 + radius; y++) {"""

SHAPE_CASE_NEW = """            // path 的输入不是矩形两点，而是折线点列 —— 走下面的 path() 单独解析，
            // 这里返回空列表，调用方不会走到这。
            case path -> { }

            case circle -> {
                for (int y = y1 - radius; y <= y1 + radius; y++) {"""

PATH_METHOD = '''
    // ---------------------------------------------------------------- path

    /**
     * 折线路径及其逐格朝向。
     *
     * `points` 是展开后的格坐标（保证四邻连续），`rotations` 与之一一对应。
     */
    public static final class PathPlan {
        public final Seq<Point2> points = new Seq<>();
        public final arc.struct.IntSeq rotations = new arc.struct.IntSeq();
        public String error;
    }

    /**
     * 解析 `path=x1,y1;x2,y2;...`，展开成逐格坐标，并算好每格朝向。
     *
     * **朝向是这一格指向下一格的方向**（0=东 1=南 2=西 3=北），
     * 也就是把整条折线连成一条能流起来的传送带所需的朝向。
     * 最后一格没有下一格，沿用前一格的朝向。
     *
     * **保证四邻连续**：Bresenham 在斜线段上会产生对角步（同时走 x 和 y），
     * 而对角相邻的两格在物理上接不上 —— 传送带只认四邻。这里对每个对角步
     * 插一个正交中间点补上，宁可多一格也不要断链。
     */
    public static PathPlan path(String spec) {
        PathPlan plan = new PathPlan();
        if (spec == null || spec.isBlank()) {
            plan.error = "required: path=x1,y1;x2,y2;...";
            return plan;
        }

        Seq<Point2> raw = new Seq<>();
        for (String seg : spec.split(";")) {
            String s = seg.trim();
            if (s.isEmpty()) continue;
            String[] parts = s.split(",");
            if (parts.length < 2) {
                plan.error = "bad point '" + s + "', expected x,y";
                return plan;
            }
            try {
                raw.add(new Point2(Integer.parseInt(parts[0].trim()),
                                   Integer.parseInt(parts[1].trim())));
            } catch (NumberFormatException e) {
                plan.error = "bad point '" + s + "', expected integers";
                return plan;
            }
        }
        if (raw.size < 2) {
            plan.error = "path needs at least 2 points, got " + raw.size;
            return plan;
        }

        // 逐段展开（复用 line 的 Bresenham），段与段之间不重复接点
        Seq<Point2> pts = new Seq<>();
        for (int i = 0; i + 1 < raw.size; i++) {
            Point2 a = raw.get(i), b = raw.get(i + 1);
            Seq<Point2> seg = shape(Shape.line, a.x, a.y, b.x, b.y, 0);
            if (seg.isEmpty()) continue;
            if (pts.isEmpty()) pts.add(seg.first());
            for (int k = 1; k < seg.size; k++) pts.add(seg.get(k));
        }
        if (pts.size < 2) {
            plan.error = "path degenerated to " + pts.size + " tile(s)";
            return plan;
        }

        // 对角步补正交中间点，保证四邻连续
        Seq<Point2> cont = new Seq<>();
        for (int i = 0; i < pts.size; i++) {
            if (i > 0) {
                Point2 prev = cont.peek(), cur = pts.get(i);
                int dx = cur.x - prev.x, dy = cur.y - prev.y;
                if (Math.abs(dx) == 1 && Math.abs(dy) == 1) {
                    // 优先水平补：先横后竖，比反过来更贴合常见的干线走向
                    cont.add(new Point2(cur.x, prev.y));
                }
            }
            cont.add(pts.get(i));
        }
        plan.points.addAll(cont);

        // 逐格朝向 = 指向下一格
        for (int i = 0; i < plan.points.size; i++) {
            if (i + 1 < plan.points.size) {
                Point2 cur = plan.points.get(i), nxt = plan.points.get(i + 1);
                plan.rotations.add(rotToward(nxt.x - cur.x, nxt.y - cur.y));
            } else {
                plan.rotations.add(plan.points.size > 1
                    ? plan.rotations.get(plan.rotations.size - 1) : 0);
            }
        }
        return plan;
    }

    /**
     * 从「指向下一格」的增量求出朝向。
     *
     * 编码与 rotation 一致：**0=东(+x) 1=南(+y) 2=西(-x) 3=北(-y)**。
     * y 向下增长，所以 +y 是屏幕下方 —— 编码 1 是南不是北。
     * 对角线优先取水平分量（带子只能四向，正交中点已在上面补过）。
     */
    private static int rotToward(int dx, int dy) {
        if (dx > 0) return 0;    // 东
        if (dx < 0) return 2;    // 西
        if (dy > 0) return 1;    // 南
        if (dy < 0) return 3;    // 北
        return 0;
    }
'''

BATCH_OLD = """    public static Actor.Result placeBatch(Team team, Seq<Point2> points, String blockName,
                                          int rotation, String config) {
        if (!Vars.state.isPlaying()) return Actor.Result.err(1005, "game not in playing state");"""

BATCH_NEW = """    public static Actor.Result placeBatch(Team team, Seq<Point2> points, String blockName,
                                          int rotation, String config) {
        return placeBatch(team, points, null, blockName, rotation, config);
    }

    /**
     * 批量下单，**每格可以有各自的朝向**（`path` 用）。
     *
     * @param rotations 与 points 等长的朝向表；传 null 则所有格用同一 rotation
     */
    public static Actor.Result placeBatch(Team team, Seq<Point2> points,
                                          arc.struct.IntSeq rotations, String blockName,
                                          int rotation, String config) {
        if (!Vars.state.isPlaying()) return Actor.Result.err(1005, "game not in playing state");"""

BATCH_LOOP_OLD = """        for (Point2 p : points) {
            if (r.accepted >= MAX_PLANS_PER_UNIT) {
                r.firstErrors.add("plan queue limit reached at " + r.accepted + " plans");
                break;
            }

            Actor.Result one = Actor.place(team, p.x, p.y, blockName, rotation, config);"""

BATCH_LOOP_NEW = """        for (int i = 0; i < points.size; i++) {
            if (r.accepted >= MAX_PLANS_PER_UNIT) {
                r.firstErrors.add("plan queue limit reached at " + r.accepted + " plans");
                break;
            }
            Point2 p = points.get(i);
            int rot = (rotations != null && i < rotations.size) ? rotations.get(i) : rotation;

            Actor.Result r1 = Actor.place(team, p.x, p.y, blockName, rot, config);
            Actor.Result one = r1;"""

# ---------------------------------------------------------------- HttpApi

HP_DOC_OLD = """     * POST /place?shape=circle&x=&y=&radius=&block=              实心圆
     *"""

HP_DOC_NEW = """     * POST /place?shape=circle&x=&y=&radius=&block=              实心圆
     * POST /place?shape=path&path=x1,y1;x2,y2;...&block=          折线路径
     *
     * `shape=path` 与其它形状的区别：**每一格的朝向由服务端按路径走向算**，
     * 把折线连成一条能流起来的传送带。不用再自己生成坐标再逐格 place。
     *"""

HP_PARSE_OLD = """        Operations.Shape shape;
        try { shape = Operations.Shape.valueOf(shapeName.toLowerCase()); }
        catch (IllegalArgumentException e) {
            respond(ex, 400, Json.error(1001, "unknown shape: " + shapeName
                + " (point|line|rect|area|outline|circle)"));
            return;
        }"""

HP_PARSE_NEW = """        Operations.Shape shape;
        try { shape = Operations.Shape.valueOf(shapeName.toLowerCase()); }
        catch (IllegalArgumentException e) {
            respond(ex, 400, Json.error(1001, "unknown shape: " + shapeName
                + " (point|line|rect|area|outline|circle|path)"));
            return;
        }

        // path 走单独的解析：它的输入是点列，并且逐格朝向由走向推出来
        if (shape == Operations.Shape.path) {
            Operations.PathPlan pp = Operations.path(p.get("path", null));
            if (pp.error != null) {
                respond(ex, 400, Json.error(1001, pp.error));
                return;
            }
            postToGame(ex, () -> {
                Actor.Result r = Operations.placeBatch(team, pp.points, pp.rotations,
                                                       block, rot, config);
                if (!r.ok) return Json.error(r.code, r.message);
                return Json.ok(new Json.Obj()
                    .put("shape", "path")
                    .put("tiles", pp.points.size)
                    .putRaw("rotations", rotationsJson(pp))
                    .put("message", r.message)
                    .toString());
            });
            return;
        }"""

HP_HELPER = """    /** path 的逐格朝向，压缩成 `[x,y,rot, x,y,rot, ...]` —— 紧凑且够读。 */
    static String rotationsJson(Operations.PathPlan pp) {
        StringBuilder s = new StringBuilder("[");
        for (int i = 0; i < pp.points.size(); i++) {
            if (i > 0) s.append(',');
            s.append('[').append(pp.points.get(i).x).append(',')
             .append(pp.points.get(i).y).append(',')
             .append(pp.rotations.get(i)).append(']');
        }
        return s.append(']').toString();
    }

    private static void handlePlace(HttpExchange ex, AIArena.Agent agent) {"""

JOBS = [
    (O, [
        (ENUM_OLD, ENUM_NEW, "Shape 枚举加 path"),
        (SHAPE_CASE_OLD, SHAPE_CASE_NEW, "shape() 里给 path 留位"),
        (BATCH_OLD, BATCH_NEW, "placeBatch 加逐格朝向重载"),
        (BATCH_LOOP_OLD, BATCH_LOOP_NEW, "循环改成按索引取朝向"),
    ]),
    (H, [
        (HP_DOC_OLD, HP_DOC_NEW, "handlePlace 注释补 path"),
        (HP_PARSE_OLD, HP_PARSE_NEW, "path 分支"),
        ("    private static void handlePlace(HttpExchange ex, AIArena.Agent agent) {",
         HP_HELPER, "rotationsJson 辅助"),
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
        print("有问题，注意上面已写盘的部分：")
        for b in bad:
            print("  " + b)
        return 1
    print("A8 已落地")
    return 0


if __name__ == "__main__":
    sys.exit(main())
