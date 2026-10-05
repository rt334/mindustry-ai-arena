#!/usr/bin/env python3
"""没传 units 时报错误导。

实测：POST /command?action=move&unit=219（参数名传错，正确的是 units=）
服务端回：1002 no valid units for crux（HTTP 404）

这句话会把人引去查「这个单位是不是不属于 crux 队」，而真实原因是
**根本没传 units 参数** —— Commander 拿到的 id 数组是空的。

加一道前置检查：需要单位的 action 若 units 为空，直接报
1001 required: units=<id>[,<id>...]，并在消息里点明是逗号分隔的复数参数。
"""
import pathlib
import sys

API = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\HttpApi.java")

OLD = """        int[] unitIds = p.getIntArray("units");
        int[] buildingIds = p.getIntArray("buildings");"""

NEW = """        int[] unitIds = p.getIntArray("units");
        int[] buildingIds = p.getIntArray("buildings");

        // 需要单位的 action：units 为空时给明确提示。
        // 不能让它落到 Commander 去报「no valid units for <team>」—— 那读起来
        // 像是「你给的 id 不属于这队」，而真实原因往往只是参数名写成了单数
        // unit=，或者忘了传。
        if (unitsRequired(op) && (unitIds == null || unitIds.length == 0)) {
            respond(ex, 400, Json.error(1001,
                "required: units=<id>[,<id>...] — 复数参数、逗号分隔；"
                + "本 action 需要至少一个己方单位"));
            return;
        }"""

HELPER_ANCHOR = """    private static void handleCommand(HttpExchange ex, AIArena.Agent agent) {"""

HELPER = """    /** 哪些 /command action 必须带 units。 */
    private static boolean unitsRequired(String op) {
        return switch (op) {
            case "move", "attackUnit", "assistBuilding", "setCommand", "setStance" -> true;
            default -> false;
        };
    }

    private static void handleCommand(HttpExchange ex, AIArena.Agent agent) {"""

RULES = [
    (OLD, NEW, "units 为空时报明确错误"),
    (HELPER_ANCHOR, HELPER, "加 unitsRequired 辅助"),
]


def main():
    t = API.read_text(encoding="utf-8")
    bad = []
    for old, new, label in RULES:
        n = t.count(old)
        if n != 1:
            bad.append(f"{n} 次命中: {label}")
            print(f"  !! {n} 次  {label}")
            continue
        t = t.replace(old, new)
        print(f"  ✓ 1 处  {label}")
    if bad:
        print("\n有问题，未写盘")
        return 1
    API.write_text(t, encoding="utf-8")
    print("\nHttpApi：units 缺失的报错已明确")
    return 0


if __name__ == "__main__":
    sys.exit(main())
