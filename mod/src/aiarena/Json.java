package aiarena;

/**
 * 零依赖 JSON 输出工具。
 *
 * 设计取舍：Mindustry 自带 arc.util.serialization.Json，但它是通用序列化器，
 * 输出格式不可控（字段顺序、空格、null 处理）。Mod 的 HTTP 响应需要稳定、
 * 紧凑、可预测的形状，所以手写一个最小实现。
 *
 * 与 eve-assistant 的 CommandResult 相比，本实现在 escape() 中补全了
 * \b \f \n \r \t 与 U+0000–U+001F 控制字符的转义 —— 原实现只处理了
 * 引号和反斜杠，遇到控制字符会产出非法 JSON。
 */
public final class Json {

    private Json() {}

    /** 转义字符串内容（不含外层引号）。 */
    public static void escape(StringBuilder sb, String s) {
        if (s == null) { sb.append("null"); return; }
        sb.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"':  sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\b': sb.append("\\b");  break;
                case '\f': sb.append("\\f");  break;
                case '\n': sb.append("\\n");  break;
                case '\r': sb.append("\\r");  break;
                case '\t': sb.append("\\t");  break;
                default:
                    if (c < 0x20) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
            }
        }
        sb.append('"');
    }

    public static String str(String s) {
        StringBuilder sb = new StringBuilder();
        escape(sb, s);
        return sb.toString();
    }

    /**
     * 数值裁到合理精度后输出。
     * 直接输出 float 会产生 1.2000000476837158 这类噪声，
     * AI 侧解析后用于决策时会造成困惑。
     */
    public static String num(float v) {
        if (Float.isNaN(v) || Float.isInfinite(v)) return "null";
        return String.valueOf(Math.round(v * 100f) / 100f);
    }

    /** 构造器风格的键值追加。 */
    public static class Obj {
        private final StringBuilder sb = new StringBuilder("{");
        private boolean first = true;

        private void sep() { if (!first) sb.append(','); first = false; }

        public Obj put(String k, String v)      { sep(); escape(sb, k); sb.append(':'); escape(sb, v); return this; }
        public Obj putRaw(String k, String raw) { sep(); escape(sb, k); sb.append(':').append(raw); return this; }
        public Obj put(String k, int v)         { sep(); escape(sb, k); sb.append(':').append(v); return this; }
        public Obj put(String k, long v)        { sep(); escape(sb, k); sb.append(':').append(v); return this; }
        public Obj put(String k, boolean v)     { sep(); escape(sb, k); sb.append(':').append(v); return this; }
        public Obj put(String k, float v)       { sep(); escape(sb, k); sb.append(':').append(num(v)); return this; }
        public Obj putNull(String k)            { sep(); escape(sb, k); sb.append(":null"); return this; }

        @Override public String toString() { return sb.append('}').toString(); }
    }

    /** 成功信封。 */
    public static String ok(String data) {
        return new Obj().put("ok", true).putRaw("data", data == null ? "null" : data).toString();
    }

    /** 失败信封。 */
    public static String error(int code, String message) {
        return new Obj().put("ok", false).put("code", code).put("error", message).toString();
    }
}
