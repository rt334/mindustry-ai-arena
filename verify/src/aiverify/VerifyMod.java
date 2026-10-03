package aiverify;

import arc.Core;
import arc.util.Log;
import arc.util.Time;
import mindustry.Vars;
import mindustry.core.GameState;
import mindustry.game.Rules;
import mindustry.game.Team;
import mindustry.gen.Groups;
import mindustry.gen.Unit;
import mindustry.maps.Map;
import mindustry.mod.Mod;
import mindustry.type.UnitType;
import mindustry.world.Block;
import mindustry.world.Tile;
import mindustry.world.blocks.storage.CoreBlock;
import mindustry.entities.units.BuildPlan;

/**
 * AI Arena P0 verification - batch 4 (final).
 *
 * Batch 3 taught us: loadMap alone does not enter playing state nor apply our rules.
 * Batch 4 sets rules explicitly, enters playing, finds real buildable ground,
 * places cores, spawns units, then re-checks FogControl with actual vision sources.
 */
public class VerifyMod extends Mod {

    private static final String TAG = "[AIVERIFY]";
    private static void log(String s) { Log.info(TAG + " " + s); System.out.println(TAG + " " + s); }
    private static void ok(String s)   { log("PASS  " + s); }
    private static void fail(String s) { log("FAIL  " + s); }
    private static void info(String s) { log("      " + s); }

    @Override
    public void init() {
        log("===== P0 batch 4 start =====");

        Team t1 = Team.get(100), t2 = Team.get(101);

        // ---------- 1. load map ----------
        Map chosen = null;
        try {
            for (Map m : Vars.maps.all()) { chosen = m; break; }
            Vars.world.loadMap(chosen, new Rules());
            ok("V4.1 loadMap " + chosen.name() + " -> " + Vars.world.width() + "x" + Vars.world.height());
        } catch (Throwable t) { fail("V4.1 " + t); t.printStackTrace(); }

        // ---------- 2. set rules explicitly, then enter playing ----------
        try {
            Rules r = Vars.state.rules;
            r.pvp = true;
            r.fog = true;
            r.staticFog = true;
            r.canGameOver = false;
            r.waves = false;
            r.attackMode = false;
            r.infiniteResources = true;
            r.editor = false;
            info("V4.2 rules set: pvp=" + r.pvp + " fog=" + r.fog + " staticFog=" + r.staticFog
                 + " infinite=" + r.infiniteResources);

            Vars.state.set(GameState.State.playing);
            ok("V4.2 state.set(playing) -> isPlaying=" + Vars.state.isPlaying());
            info("     rules after set: pvp=" + Vars.state.rules.pvp + " fog=" + Vars.state.rules.fog);
        } catch (Throwable t) { fail("V4.2 " + t); t.printStackTrace(); }

        // ---------- 3. find buildable ground ----------
        int cx = -1, cy = -1;
        Block coreBlock = null;
        try {
            for (Block b : Vars.content.blocks()) {
                if (b instanceof CoreBlock && !b.isHidden()) { coreBlock = b; break; }
            }
            info("V4.3 core block = " + (coreBlock == null ? "null" : coreBlock.name));

            outer:
            for (int y = 3; y < Vars.world.height() - 3; y++) {
                for (int x = 3; x < Vars.world.width() - 3; x++) {
                    Tile t = Vars.world.tile(x, y);
                    if (t == null) continue;
                    if (t.block() != mindustry.content.Blocks.air) continue;
                    if (t.solid()) continue;
                    if (mindustry.world.Build.validPlace(coreBlock, t1, x, y, 0)) {
                        cx = x; cy = y; break outer;
                    }
                }
            }
            if (cx < 0) fail("V4.3 no valid ground for core found");
            else        ok("V4.3 buildable spot at (" + cx + "," + cy + ")");
        } catch (Throwable t) { fail("V4.3 " + t); t.printStackTrace(); }

        // ---------- 4. place two cores ----------
        try {
            if (cx >= 0 && coreBlock != null) {
                Tile a = Vars.world.tile(cx, cy);
                a.setBlock(coreBlock, t1, 0);
                info("V4.4 core1 at (" + cx + "," + cy + ") team=" + t1.name
                     + " build=" + (a.build != null));

                int dx = -1, dy = -1;
                outer2:
                for (int y = Vars.world.height() - 4; y > 3; y--) {
                    for (int x = Vars.world.width() - 4; x > 3; x--) {
                        if (Math.abs(x - cx) < 40 && Math.abs(y - cy) < 40) continue;
                        Tile t = Vars.world.tile(x, y);
                        if (t == null || t.block() != mindustry.content.Blocks.air || t.solid()) continue;
                        if (mindustry.world.Build.validPlace(coreBlock, t2, x, y, 0)) { dx = x; dy = y; break outer2; }
                    }
                }
                if (dx >= 0) {
                    Vars.world.tile(dx, dy).setBlock(coreBlock, t2, 0);
                    info("V4.4 core2 at (" + dx + "," + dy + ") team=" + t2.name);
                } else info("V4.4 no far spot for core2");

                info("     t1 cores=" + t1.data().cores.size + "  t2 cores=" + t2.data().cores.size);
                info("     t1 isAlive=" + t1.isAlive() + "  isAI=" + t1.isAI() + " (pvp=true, expect false)");
                info("     state.teams.present.size = " + Vars.state.teams.present.size);
                ok("V4.4 cores placed for custom teams");
            }
        } catch (Throwable t) { fail("V4.4 " + t); t.printStackTrace(); }

        // ---------- 5. FogControl before any unit ----------
        try {
            info("V4.5 --- fog before spawning units ---");
            if (cx >= 0) info("     t1 own core (" + cx + "," + cy + ") visible="
                              + Vars.fogControl.isVisibleTile(t1, cx, cy));
            info("     t1 (30,30) visible=" + Vars.fogControl.isVisibleTile(t1, 30, 30));
            info("     t1 (128,128) visible=" + Vars.fogControl.isVisibleTile(t1, 128, 128));
        } catch (Throwable t) { fail("V4.5 " + t); }

        // ---------- 6. spawn a unit for t1 ----------
        try {
            UnitType ut = null;
            for (UnitType u : Vars.content.units()) {
                if (u.fogRadius > 0 && !u.isHidden()) { ut = u; break; }
            }
            info("V4.6 unit type = " + (ut == null ? "null" : (ut.name + " fogRadius=" + ut.fogRadius)));

            if (ut != null && cx >= 0) {
                Unit spawned = ut.create(t1);
                spawned.set(cx * Vars.tilesize + 4f, cy * Vars.tilesize + 4f);
                spawned.add();
                ok("V4.6 spawned " + ut.name + " for " + t1.name
                   + " at (" + spawned.x + "," + spawned.y + ")");
                info("     Groups.unit.size = " + Groups.unit.size());
                info("     canBuild() = " + spawned.canBuild());
                info("     controller = " + spawned.controller().getClass().getSimpleName());
            }
        } catch (Throwable t) { fail("V4.6 " + t); t.printStackTrace(); }

        // ---------- 7. build pipeline ----------
        try {
            Block conveyor = null;
            for (Block b : Vars.content.blocks()) {
                if (b.name != null && b.name.equals("conveyor")) { conveyor = b; break; }
            }
            if (conveyor == null) {
                fail("V4.7 conveyor not found");
            } else {
                int bx = cx + 3, by = cy;
                boolean valid = mindustry.world.Build.validPlace(conveyor, t1, bx, by, 0);
                info("V4.7 validPlace(conveyor," + t1.name + "," + bx + "," + by + ",0) = " + valid);

                Unit builder = null;
                for (Unit u : Groups.unit) { if (u.team == t1 && u.canBuild()) { builder = u; break; } }
                info("     builder found = " + (builder != null));

                if (valid && builder != null) {
                    BuildPlan plan = new BuildPlan(bx, by, 0, conveyor);
                    info("     plan: breaking=" + plan.breaking + " block=" + plan.block.name);
                    builder.addBuild(plan);
                    ok("V4.7 builder.addBuild(plan) called");
                } else {
                    info("     skipping addBuild (valid=" + valid + " builder=" + (builder != null) + ")");
                }
            }
        } catch (Throwable t) { fail("V4.7 " + t); t.printStackTrace(); }

        // ---------- 8. delayed checks ----------
        final int tickStart = (int) Vars.state.tick;
        final int fcx = cx, fcy = cy;
        Time.run(120f, () -> {
            log("===== P0 batch 4 delayed (2s) =====");
            int tickNow = (int) Vars.state.tick;
            info("tick " + tickStart + " -> " + tickNow
                 + (tickNow > tickStart ? "   [TICK WORKS]" : "   [TICK STALLED]"));
            info("isPlaying = " + Vars.state.isPlaying());
            info("Groups: unit=" + Groups.unit.size() + " build=" + Groups.build.size()
                 + " player=" + Groups.player.size());

            try {
                info("--- fog after units exist ---");
                long vis = 0, dis = 0;
                for (int y = 0; y < Vars.world.height(); y += 4)
                    for (int x = 0; x < Vars.world.width(); x += 4) {
                        if (Vars.fogControl.isVisibleTile(t1, x, y)) vis++;
                        if (Vars.fogControl.isDiscovered(t1, x, y)) dis++;
                    }
                info("t1 visible samples = " + vis + "   discovered = " + dis);
                if (fcx >= 0) info("t1 own core visible = " + Vars.fogControl.isVisibleTile(t1, fcx, fcy));

                info("units:");
                for (Unit u : Groups.unit)
                    info("   " + u.type.name + " team=" + u.team.name + " (" + (int)u.x + "," + (int)u.y + ")");
                info("buildings:");
                for (var b : Groups.build)
                    info("   " + b.block.name + " team=" + b.team.name + " (" + b.tileX() + "," + b.tileY() + ")");
            } catch (Throwable t) { info("delayed -> " + t); }
            log("===== P0 batch 4 end =====");
        });

        startHttp();
        log("batch 4 sync part done");
    }

    private void startHttp() {
        try {
            com.sun.net.httpserver.HttpServer server =
                com.sun.net.httpserver.HttpServer.create(new java.net.InetSocketAddress("127.0.0.1", 7199), 0);

            server.createContext("/ping", ex -> respond(ex, "{\"ok\":true,\"headless\":" + Vars.headless
                + ",\"tick\":" + (int)Vars.state.tick + "}"));

            server.createContext("/state", ex -> Core.app.post(() -> {
                StringBuilder sb = new StringBuilder();
                sb.append("{\"ok\":true,\"tick\":").append((int)Vars.state.tick)
                  .append(",\"playing\":").append(Vars.state.isPlaying())
                  .append(",\"pvp\":").append(Vars.state.rules.pvp)
                  .append(",\"fog\":").append(Vars.state.rules.fog)
                  .append(",\"units\":").append(Groups.unit.size())
                  .append(",\"builds\":").append(Groups.build.size())
                  .append(",\"teams\":[");
                boolean first = true;
                for (var td : Vars.state.teams.present) {
                    if (!first) sb.append(",");
                    first = false;
                    sb.append("{\"id\":").append(td.team.id).append(",\"name\":\"").append(td.team.name)
                      .append("\",\"cores\":").append(td.cores.size)
                      .append(",\"isAI\":").append(td.team.isAI())
                      .append(",\"alive\":").append(td.team.isAlive()).append("}");
                }
                sb.append("]}");
                respond(ex, sb.toString());
            }));

            server.createContext("/units", ex -> Core.app.post(() -> {
                StringBuilder sb = new StringBuilder("{\"ok\":true,\"units\":[");
                boolean first = true;
                for (Unit u : Groups.unit) {
                    if (!first) sb.append(",");
                    first = false;
                    sb.append("{\"type\":\"").append(u.type.name).append("\"")
                      .append(",\"team\":\"").append(u.team.name).append("\"")
                      .append(",\"x\":").append((int)u.x).append(",\"y\":").append((int)u.y)
                      .append(",\"health\":").append((int)u.health).append("}");
                }
                sb.append("]}");
                respond(ex, sb.toString());
            }));

            server.createContext("/fog", ex -> {
                String q = ex.getRequestURI().getQuery();
                int teamId = 100, x = 0, y = 0;
                if (q != null) for (String kv : q.split("&")) {
                    String[] p = kv.split("=", 2);
                    if (p.length < 2) continue;
                    if (p[0].equals("team")) teamId = Integer.parseInt(p[1]);
                    if (p[0].equals("x"))    x = Integer.parseInt(p[1]);
                    if (p[0].equals("y"))    y = Integer.parseInt(p[1]);
                }
                final int ft = teamId, fx = x, fy = y;
                Core.app.post(() -> respond(ex,
                    "{\"ok\":true,\"team\":" + ft + ",\"x\":" + fx + ",\"y\":" + fy
                    + ",\"visible\":" + Vars.fogControl.isVisibleTile(Team.get(ft), fx, fy)
                    + ",\"discovered\":" + Vars.fogControl.isDiscovered(Team.get(ft), fx, fy)
                    + ",\"tick\":" + (int)Vars.state.tick + "}"));
            });

            server.setExecutor(java.util.concurrent.Executors.newFixedThreadPool(4, r -> {
                Thread th = new Thread(r, "AIARENA-HTTP"); th.setDaemon(true); return th;
            }));
            server.start();
            ok("V4.8 HTTP on 127.0.0.1:7199  (/ping /state /units /fog)");
        } catch (Throwable t) { fail("V4.8 " + t); }
    }

    private static void respond(com.sun.net.httpserver.HttpExchange ex, String json) {
        try {
            byte[] b = json.getBytes("UTF-8");
            ex.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
            ex.sendResponseHeaders(200, b.length);
            ex.getResponseBody().write(b);
            ex.getResponseBody().close();
        } catch (Exception ignored) {}
    }
}
