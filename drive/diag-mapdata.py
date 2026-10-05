#!/usr/bin/env python3
"""给 mapDataJson 加诊断日志 —— 定位 ores 全 null 的原因。

现象：同一循环里 floors（11674 段）和 walls（6786 段）都正常，
     唯独 ores 只有 1 段 [null, 70000]，像全图没矿。
     但 /map 端点用同样的 t.overlay() 能读到 241 格矿。

在函数末尾打一行日志，把三样的段数和前几个非 null 的 overlay 名报出来。
"""
import pathlib
import sys

R = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Recorder.java")

OLD = """            return new Json.Obj()
                .put("w", w).put("h", h)
                .putRaw("floors", floors.toString())
                .putRaw("ores", ores.toString())
                .putRaw("walls", walls.toString())
                .toString();"""

NEW = """            // 诊断：三样各多少段、矿样本长什么样
            AIArena.log("mapData: floors=" + (countRuns(floors) / 2)
                + " ores=" + (countRuns(ores) / 2)
                + " walls=" + (countRuns(walls) / 2)
                + " oreSample=" + firstNonNullName(ores));

            return new Json.Obj()
                .put("w", w).put("h", h)
                .putRaw("floors", floors.toString())
                .putRaw("ores", ores.toString())
                .putRaw("walls", walls.toString())
                .toString();"""

HELPER_OLD = """    /** RLE 的一段。name 为 null 表示「这一段的格子上什么都没有」。 */"""

HELPER_NEW = """    /** 数一数字符串里有多少个元素（逗号分隔，用于诊断）。 */
    private static int countRuns(StringBuilder sb) {
        int n = 0;
        for (int i = 0; i < sb.length(); i++) {
            if (sb.charAt(i) == ',') n++;
        }
        return n + 1;
    }

    /** 取 RLE 里第一个非 null 的名称，用于诊断。 */
    private static String firstNonNullName(StringBuilder sb) {
        String s = sb.toString();
        int i = 0, n = 0;
        while (true) {
            int comma = s.indexOf(',', i);
            if (comma < 0) return "(none)";
            String tok = s.substring(i, comma).trim();
            if (!tok.equals("null") && tok.length() > 2) return tok;
            i = s.indexOf(',', comma + 1);
            if (i < 0) return "(none)";
            i++;
            if (++n > 20000) return "(none)";
        }
    }

    /** RLE 的一段。name 为 null 表示「这一段的格子上什么都没有」。 */"""

RULES = [
    (OLD, NEW, "加诊断日志"),
    (HELPER_OLD, HELPER_NEW, "加诊断辅助方法"),
]


def main():
    text = R.read_text(encoding="utf-8")
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
    R.write_text(text, encoding="utf-8")
    print("\nRecorder.java：诊断已加")
    return 0


if __name__ == "__main__":
    sys.exit(main())
