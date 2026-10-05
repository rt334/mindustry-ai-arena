#!/usr/bin/env python3
"""补2：/stalls 明确区分「上游没来货」和「推不出去」。

原始痛点（REVIEW-ADDENDUM 补2）：
    「核心铜满 → 铜线全堵 → 上游铜钻机全部 eff=0.0 且满仓。
      这不是『铜线有问题』，是核心吃饱了。」
    ⇒ 建议 /stalls 区分「上游来货不足」和「下游拒收」两种停机。

判据：`efficiency == 0` 且满仓 ⇒ 输出路径不通；缺料 ⇒ 输入路径不通。
原先这两条只是隐含在 outputAccepts / missing 两个字段里，得读的人自己拼。
"""
import pathlib
import sys

S = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\StallWatch.java")

CAUSE_METHOD = '''    /**
     * 停机的直接原因 —— 一句话说清该往上游查还是往下游查。
     *
     *   starved        上游没把料送来（缺输入），**往上游查**
     *   outputBlocked  自己有料且已满仓，出料侧不收 —— **往下游查**
     *   outputRefused  出料侧不收，但自己还没满仓（刚堵上）
     *   unknown        其它情况（电力、配方等），看 missing 数组
     *
     * 判据：`efficiency == 0` 且满仓 ⇒ 输出路径不通；缺料 ⇒ 输入路径不通。
     */
    private static String causeOf(Building b, String kind) {
        if ("missingInput".equals(kind)) return "starved";

        boolean accepts = sideAccepts(b, b.rotation);
        if (!accepts) {
            boolean full = b.block.hasItems && b.items != null
                && (b.block.itemCapacity <= 0 || b.items.total() >= b.block.itemCapacity);
            return full ? "outputBlocked" : "outputRefused";
        }
        return "unknown";
    }

    private static String entryJson(Building b, Team team, String kind, double secs) {'''

RULES = [
    ("    private static String entryJson(Building b, Team team, String kind, double secs) {",
     CAUSE_METHOD,
     "加 causeOf()"),
    ("""            .put("kind", kind)
            .put("rotation", b.rotation)""",
     """            .put("kind", kind)
            .put("cause", causeOf(b, kind))
            .put("rotation", b.rotation)""",
     "entryJson 输出 cause"),
]


def main():
    text = S.read_text(encoding="utf-8")
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
    S.write_text(text, encoding="utf-8")
    print("\nStallWatch.java 已更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
