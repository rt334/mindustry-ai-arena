#!/usr/bin/env python3
"""补插 A8 漏掉的部分：PathPlan 类 + path() 方法；清掉循环里的冗余中转变量。"""
import pathlib
import sys

O = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Operations.java")

PATH_METHOD = '''    // ---------------------------------------------------------------- path

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

RULES = [
    ("    public static final class BatchResult {",
     PATH_METHOD + "    public static final class BatchResult {",
     "插入 PathPlan 类与 path() / rotToward()"),
    ("""            Actor.Result r1 = Actor.place(team, p.x, p.y, blockName, rot, config);
            Actor.Result one = r1;""",
     """            Actor.Result one = Actor.place(team, p.x, p.y, blockName, rot, config);""",
     "清掉冗余中转变量"),
]


def main():
    text = O.read_text(encoding="utf-8")
    bad = []
    for old, new, label in RULES:
        n = text.count(old)
        if n != 1:
            bad.append(f"{n} 次命中: {label}")
            print(f"  !! {n} 次  {label}")
            continue
        text = text.replace(old, new)
        print(f"  1 处  {label}")
    if bad:
        print("\n有问题，未写盘")
        return 1
    O.write_text(text, encoding="utf-8")
    print("\nOperations.java 已补齐")
    return 0


if __name__ == "__main__":
    sys.exit(main())
