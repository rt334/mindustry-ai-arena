import aiarena.AIArena;
import aiarena.Audit;
import aiarena.Json;
import aiarena.Operations;
import aiarena.StallWatch;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;

/**
 * 离线断言 —— **不需要起游戏、不需要服务器**，直接调纯逻辑。
 *
 * 为什么要有它（docs/TODO.md §3.5）：这个项目此前所有验证都要起服务器或起游戏，
 * 成本高 → 于是"下次再验" → 验证债越积越多。而里面有一批逻辑本来就是纯函数
 * （JSON 转义、错误码映射、权限判定、token 生成），完全可以在 2 秒内跑完。
 *
 * 用法（由 drive/offline-checks.py 负责编译与调用，也可以手跑）：
 *   javac -cp "<Mindustry.jar>;mod\classes" -d <tmp> drive\checks\OfflineChecks.java
 *   java  -cp "<tmp>;<Mindustry.jar>;mod\classes" OfflineChecks
 *
 * 输出：每行一个 JSON —— {"name":..,"status":"PASS|FAIL|SKIP","detail":..}
 * 刻意手写拼接而不用 Json 类：**被测代码不该负责生成自己的测试报告**。
 */
public class OfflineChecks {
    private static final List<String> out = new ArrayList<>();
    private static int pass = 0, fail = 0, skip = 0;

    private static String esc(String s) {
        if (s == null) return "";
        StringBuilder sb = new StringBuilder();
        for (char c : s.toCharArray()) {
            if (c == '\\') sb.append("\\\\");
            else if (c == '"') sb.append("\\\"");
            else if (c == '\n') sb.append("\\n");
            else if (c == '\r') sb.append("\\r");
            else if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
            else sb.append(c);
        }
        return sb.toString();
    }

    private static void rec(String name, String status, String detail) {
        out.add("{\"name\":\"" + esc(name) + "\",\"status\":\"" + status
                + "\",\"detail\":\"" + esc(detail) + "\"}");
        if ("PASS".equals(status)) pass++;
        else if ("FAIL".equals(status)) fail++;
        else skip++;
    }

    private static void eq(String name, Object actual, Object expect) {
        boolean ok = (actual == null ? expect == null : actual.equals(expect));
        rec(name, ok ? "PASS" : "FAIL",
            ok ? "" : "actual=[" + actual + "] expect=[" + expect + "]");
    }

    private static void ok(String name, boolean cond, String detail) {
        rec(name, cond ? "PASS" : "FAIL", cond ? "" : detail);
    }

    /** 一组断言；整组抛异常时记一条 SKIP（而不是让整个套件崩掉）。 */
    private static void group(String name, Runnable body) {
        try {
            body.run();
        } catch (Throwable t) {
            rec(name, "SKIP", t.getClass().getSimpleName() + ": " + t.getMessage());
        }
    }

    public static void main(String[] args) {
        // ---------------------------------------------------------- Json.str
        group("Json.str", () -> {
            eq("Json.str 引号", Json.str("a\"b"), "\"a\\\"b\"");
            eq("Json.str 反斜杠", Json.str("a\\b"), "\"a\\\\b\"");
            eq("Json.str 换行", Json.str("a\nb"), "\"a\\nb\"");
            eq("Json.str 回车", Json.str("a\rb"), "\"a\\rb\"");
            eq("Json.str 制表", Json.str("a\tb"), "\"a\\tb\"");
            eq("Json.str 控制字符", Json.str("\u0001"), "\"\\u0001\"");
            eq("Json.str 中文原样", Json.str("铜"), "\"铜\"");
            eq("Json.str 空串", Json.str(""), "\"\"");
        });

        // ---------------------------------------------------------- Json.num
        group("Json.num", () -> {
            eq("Json.num NaN", Json.num(Float.NaN), "null");
            eq("Json.num +Inf", Json.num(Float.POSITIVE_INFINITY), "null");
            eq("Json.num -Inf", Json.num(Float.NEGATIVE_INFINITY), "null");
            eq("Json.num 裁到两位", Json.num(1.2000000476837158f), "1.2");
            eq("Json.num 负数", Json.num(-2.5f), "-2.5");
        });

        // ---------------------------------------------------------- Json.Obj
        group("Json.Obj", () -> {
            eq("Obj 空对象", new Json.Obj().toString(), "{}");
            eq("Obj put 字符串", new Json.Obj().put("a", "b").toString(), "{\"a\":\"b\"}");
            eq("Obj put 整数", new Json.Obj().put("n", 3).toString(), "{\"n\":3}");
            eq("Obj put 布尔", new Json.Obj().put("b", true).toString(), "{\"b\":true}");
            eq("Obj putRaw 原样嵌入", new Json.Obj().putRaw("r", "[1,2]").toString(), "{\"r\":[1,2]}");
            eq("Obj 键名也转义", new Json.Obj().put("a\"b", "c").toString(), "{\"a\\\"b\":\"c\"}");
            eq("Obj 多字段用逗号", new Json.Obj().put("a", 1).put("b", 2).toString(), "{\"a\":1,\"b\":2}");
        });

        // ---------------------------------------------------- Json 信封结构
        // 「错误响应以 {"ok":false 开头」是修过的事故（CHANGELOG：成功响应曾被回成 400）——
        // 这条断言把它钉住，防止再退回子串匹配的写法。
        group("Json 信封", () -> {
            ok("ok() 以 {\"ok\":true,\"data\": 开头",
               Json.ok("{}").startsWith("{\"ok\":true,\"data\":"), Json.ok("{}"));
            ok("error() 以 {\"ok\":false 开头",
               Json.error(1001, "x").startsWith("{\"ok\":false"), Json.error(1001, "x"));
            eq("error() 带 code 与 error",
               Json.error(1008, "blocked"), "{\"ok\":false,\"code\":1008,\"error\":\"blocked\"}");
            ok("error() 三参数带 data",
               Json.error(1008, "b", new Json.Obj().put("short", 1)).contains("\"data\":{\"short\":1}"),
               Json.error(1008, "b", new Json.Obj().put("short", 1)));
            ok("ok(null) 不产出非法 JSON",
               Json.ok(null).equals("{\"ok\":true,\"data\":null}"), Json.ok(null));
        });

        // ------------------------------------------------------- Audit 判定
        group("Audit", () -> {
            ok("isMutating(place)", Audit.isMutating("place"), "place 应为 mutating");
            ok("isMutating(state)=false", !Audit.isMutating("state"), "读端点不该记");
            ok("isMutating(null)=false", !Audit.isMutating(null), "null 不该 NPE");
            // 下面三个是 2026-10-06 补的：它们改游戏状态却漏记
            ok("isMutating(host)", Audit.isMutating("host"), "host 漏记过");
            ok("isMutating(start)", Audit.isMutating("start"), "start 漏记过");
            ok("isMutating(fog)", Audit.isMutating("fog"), "fog 漏记过");
            ok("isPrivileged(view=all)", Audit.isPrivileged("view=all"), "特权读要留痕");
            ok("isPrivileged(无 view)=false", !Audit.isPrivileged("x=1&y=2"), "普通读不该记");
            ok("isPrivileged(null)=false", !Audit.isPrivileged(null), "null 不该 NPE");
        });

        // -------------------------------------------------- Operations.Shape
        group("Operations.Shape", () -> {
            Operations.Shape[] all = Operations.Shape.values();
            eq("shape 取值个数", all.length, 7);
            for (String want : new String[]{"point", "line", "rect", "area", "outline", "circle", "path"}) {
                boolean found = false;
                for (Operations.Shape s : all) if (s.name().equals(want)) found = true;
                ok("shape 含 " + want, found, "缺 " + want);
            }
        });

        // ---------------------------------------------------- randomToken
        group("AIArena.randomToken", () -> {
            String t = AIArena.randomToken();
            eq("token 长度 48", t.length(), 48);
            ok("token 全为 hex", t.matches("[0-9a-f]{48}"), t);
            ok("两次不同", !t.equals(AIArena.randomToken()), "随机性可疑");
        });

        // ------------------------------------------------ statusFor（私有，反射）
        group("HttpApi.statusFor", () -> {
            try {
                Class<?> c = Class.forName("aiarena.HttpApi");
                Method m = c.getDeclaredMethod("statusFor", String.class);
                m.setAccessible(true);
                int[][] cases = {
                    {1001, 400}, {1003, 400}, {1009, 400}, {1002, 404}, {1004, 429},
                    {1005, 403}, {1403, 403}, {1006, 410}, {1007, 504}, {1008, 409}, {1429, 429},
                };
                for (int[] cs : cases) {
                    Object got = m.invoke(null, Json.error(cs[0], "x"));
                    eq("statusFor " + cs[0], got, cs[1]);
                }
                // 未映射的码走 default -> 400。1401/1500 就是这一类：
                // 它们在调用点里硬编码了 401/500，不经过 statusFor。
                eq("statusFor 1401 -> 400（调用点硬编码 401）", m.invoke(null, Json.error(1401, "x")), 400);
                eq("statusFor 1500 -> 400（调用点硬编码 500）", m.invoke(null, Json.error(1500, "x")), 400);
            } catch (ReflectiveOperationException e) {
                throw new RuntimeException(e);      // 由 group() 记成 SKIP
            }
        });

        // ------------------------------------------------ StallWatch 快照一致性
        //
        // 动机：`/stalls` 曾经分别调 `stalledCount(viewId)` + `stallsJson(viewId)`，
        // 而这两个方法各自读一次快照引用 —— 两次读之间主线程可能已完成一次
        // update()，于是响应里「计数来自上一拍、数组来自这一拍」，自己和自己
        // 对不上（裁判视角的窗口尤其宽：totalCount 的赋值与 JSON 拼接之间隔着
        // 一整个字符串构造循环）。现在两个值走同一次 `viewOf(viewId)`。
        //
        // 用 group 包住：StallWatch 是游戏内类，万一静态初始化在无 Vars 的
        // 裸 JVM 里出问题，应该记 SKIP，而不是让整套断言一起崩。
        // （这里刻意不写死项数：那个数字加一条就变，写了迟早是错的。）
        group("StallWatch 快照", () -> {
            for (int view : new int[]{-1, 0, 1}) {
                Object[] v = StallWatch.viewOf(view);
                eq("viewOf(" + view + ") 返回 [count, json]", v.length, 2);
                ok("viewOf(" + view + ")[0] 是 Integer", v[0] instanceof Integer,
                   "actual=" + v[0]);
                ok("viewOf(" + view + ")[1] 是 String", v[1] instanceof String,
                   "actual=" + v[1]);
                // 单独读的两条路径，答案必须和同源读一致
                eq("stalledCount(" + view + ") 与 viewOf 一致",
                   StallWatch.stalledCount(view), v[0]);
                eq("stallsJson(" + view + ") 与 viewOf 一致",
                   StallWatch.stallsJson(view), v[1]);
            }
            // 未开局时快照是空表，也不该抛
            eq("未开局 stalledCount(-1)", StallWatch.stalledCount(-1), 0);
            eq("未开局 stallsJson(-1)", StallWatch.stallsJson(-1), "[]");
        });

        for (String line : out) System.out.println(line);
        System.err.println("PASS=" + pass + " FAIL=" + fail + " SKIP=" + skip);
        System.exit(fail > 0 ? 1 : 0);
    }
}
