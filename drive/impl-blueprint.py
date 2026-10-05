#!/usr/bin/env python3
"""实现蓝图导入 / 导出 —— §2.2 的最后一项。

DESIGN.md 402-426 给的是 Mindustry `.msch` 那条路（readBase64 → 逐格 BuildPlan）。
**我没走那条路**，理由要说清楚：`.msch` 是 base64 包着一段自定义二进制
（format 字节 + version + tags + tiles），没有参考实现的情况下照猜写一个解析器，
产出的是「看着像对、其实错位」的东西 —— 那正是这个项目一直在避免的失败模式。
而且本轮不启游戏，写出来也验不了。

所以实现的是**我们自己的一种显式 JSON 蓝图**，格式写死、可读、能验：

    {"v":1,"name":"...","w":N,"h":N,
     "blocks":[{"dx":0,"dy":0,"block":"conveyor","rot":0}, ...]}

base64 编码后放在 `data=` 里。**与 DESIGN.md 的偏差记进 API.md**，
并把 `.msch` 读取器列为仍未实现。

为什么这东西值得做：这张图**每局重新随机**（见 PRODUCTION.md §一），
所以布局本来没法跨局复用。有了导出/导入，一局调好的产线可以存下来、
下一局搬到新的地形上。对现在这种「每局重铺」的处境是直接对症的。
"""
import pathlib
import sys

API = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\HttpApi.java")

CASE_OLD = '                case "stream"    -> handleStream(ex, agent);'
CASE_NEW = ('                case "stream"    -> handleStream(ex, agent);\n'
            '                case "blueprint" -> handleBlueprint(ex, agent);')

METHOD = r'''
    /**
     * 蓝图导入 / 导出。
     *
     *   GET  /v1/{agent}/blueprint?x=&y=&w=&h=        导出该矩形区域
     *   POST /v1/{agent}/blueprint?x=&y=&data=<base64> 把蓝图放在 (x,y)
     *
     * 格式是我们自己的显式 JSON（见本文件顶部说明与 API.md），
     * **不是 Mindustry 的 .msch 二进制** —— 后者在没有参考实现的情况下
     * 照猜写解析器，产出的是「看着像对、其实错位」的东西。
     *
     * 为什么值得做：这张图每局重新随机，布局本来没法跨局复用。
     * 有了它，一局调好的产线能存下来、下一局搬到新地形上。
     */
    private static void handleBlueprint(HttpExchange ex, AIArena.Agent agent) {
        Params p = Params.of(ex);
        Team team = agent.team();
        if (team == null) { respond(ex, 403, Json.error(1403, "agent has no team")); return; }

        String data = p.get("data", null);

        // ── 导出 ──────────────────────────────────────────────────────
        if (data == null) {
            int x = p.getInt("x", Integer.MIN_VALUE);
            int y = p.getInt("y", Integer.MIN_VALUE);
            int w = p.getInt("w", 0), h = p.getInt("h", 0);
            if (x == Integer.MIN_VALUE || y == Integer.MIN_VALUE) {
                respond(ex, 400, Json.error(1001, "required: x, y, w, h (for export)"));
                return;
            }
            if (w <= 0 || h <= 0 || w * h > MAX_MAP_TILES) {
                respond(ex, 400, Json.error(1004, "w*h must be in 1.." + MAX_MAP_TILES));
                return;
            }
            postToGame(ex, () -> {
                StringBuilder blocks = new StringBuilder("[");
                int n = 0;
                for (int dy = 0; dy < h; dy++) {
                    for (int dx = 0; dx < w; dx++) {
                        var tile = Vars.world.tile(x + dx, y + dy);
                        if (tile == null || tile.build == null) continue;
                        // 多格方块只在锚点记一次，否则导入时会重复放
                        if (tile.build.tileX() != x + dx || tile.build.tileY() != y + dy) continue;
                        if (n > 0) blocks.append(',');
                        blocks.append(new Json.Obj()
                            .put("dx", dx).put("dy", dy)
                            .put("block", tile.build.block.name)
                            .put("rot", tile.build.rotation)
                            .toString());
                        n++;
                    }
                }
                blocks.append(']');
                String plain = new Json.Obj()
                    .put("v", 1).put("w", w).put("h", h).put("count", n)
                    .putRaw("blocks", blocks.toString()).toString();
                String b64 = java.util.Base64.getEncoder()
                    .encodeToString(plain.getBytes(java.nio.charset.StandardCharsets.UTF_8));
                return Json.ok(new Json.Obj()
                    .put("x", x).put("y", y).put("w", w).put("h", h)
                    .put("count", n).put("data", b64)
                    .put("format", "ai-arena-blueprint-json/1")
                    .put("message", "exported " + n + " block(s)").toString());
            });
            return;
        }

        // ── 导入 ──────────────────────────────────────────────────────
        int x = p.getInt("x", Integer.MIN_VALUE);
        int y = p.getInt("y", Integer.MIN_VALUE);
        if (x == Integer.MIN_VALUE || y == Integer.MIN_VALUE) {
            respond(ex, 400, Json.error(1001, "required: x, y (top-left anchor for import)"));
            return;
        }
        postToGame(ex, () -> {
            String plain;
            try {
                plain = new String(java.util.Base64.getDecoder().decode(data.trim()),
                                   java.nio.charset.StandardCharsets.UTF_8);
            } catch (IllegalArgumentException bad) {
                return Json.error(1001, "data is not valid base64");
            }
            arc.util.serialization.Jval root;
            try {
                root = arc.util.serialization.Jval.read(plain);
            } catch (Throwable t) {
                return Json.error(1001, "blueprint is not valid JSON: " + t);
            }
            var arr = root.get("blocks");
            if (arr == null || !arr.isArray()) {
                return Json.error(1001, "blueprint has no blocks[] array");
            }

            int ok = 0, skipped = 0, firstBad = -1;
            StringBuilder reasons = new StringBuilder();
            int idx = 0;
            for (arc.util.serialization.Jval b : arr.asArray()) {
                String block = b.getString("block", null);
                if (block == null) { skipped++; idx++; continue; }
                int dx = b.getInt("dx", 0), dy = b.getInt("dy", 0);
                int rot = b.getInt("rot", 0);
                Actor.Result r = Actor.place(team, x + dx, y + dy, block, rot, null);
                if (r.ok) {
                    ok++;
                } else {
                    skipped++;
                    if (firstBad < 0) firstBad = (x + dx) * 100000 + (y + dy);
                    if (reasons.length() < 240)
                        reasons.append('(').append(x + dx).append(',').append(y + dy)
                               .append(")=").append(r.code).append(' ');
                }
                idx++;
            }
            Json.Obj body = new Json.Obj()
                .put("placed", ok).put("skipped", skipped).put("total", idx)
                .put("format", "ai-arena-blueprint-json/1");
            if (firstBad >= 0) body.put("firstFailureTile", firstBad);
            if (reasons.length() > 0) body.put("failureCodes", reasons.toString());
            body.put("message", "blueprint: placed " + ok + "/" + idx
                + (skipped > 0 ? ", skipped " + skipped + " (see failureCodes)" : ""));
            return ok > 0 ? Json.ok(body.toString())
                          : Json.error(1005, "blueprint placed nothing: " + body);
        });
    }
'''


def main():
    t = API.read_text(encoding="utf-8")
    if t.count(CASE_OLD) != 1:
        print(f"!! case 锚点 {t.count(CASE_OLD)} 次")
        return 1
    t = t.replace(CASE_OLD, CASE_NEW, 1)
    print('  ✓ 1 处  加 case "blueprint"')

    anchor = "    /** 同时在流的 SSE 连接数上限。"
    if t.count(anchor) != 1:
        print(f"!! 方法锚点 {t.count(anchor)} 次，未写盘")
        return 1
    t = t.replace(anchor, METHOD.rstrip() + "\n\n" + anchor, 1)
    print("  ✓ 1 处  插入 handleBlueprint")
    API.write_text(t, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
