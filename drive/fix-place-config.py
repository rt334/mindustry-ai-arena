#!/usr/bin/env python3
"""A7：/place 的 config 参数真正生效。

现象（FEATURE-REQUESTS A7）：
    「/place?block=sorter&config=coal 建出来之后 config 字段是 None，
      必须再发一次 /config 才生效。」

根因：Actor.place 把 HTTP 传来的 **字符串** 直接塞进 BuildPlan.config，
而 BuildingComp.configured() 是按 value.getClass() 去查 block.configurations 的，
String 一律匹配不上 —— 配置静默失效。Actor.configure 里早就有解析函数
（resolveConfigValue），只是 place 这条路径没走它。

顺带加一个警告：解析结果仍是字符串、而该方块确实声明了配置类型时，
明确告诉调用方「这个 config 不会被接受」，而不是等它建完了才发现。
"""
import pathlib
import sys

A = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Actor.java")

RESOLVE_OLD = """    private static Object resolveConfigValue(Building build, String value) {
        var configs = build.block.configurations;
"""

RESOLVE_NEW = """    private static Object resolveConfigValue(Building build, String value) {
        return resolveConfigValue(build.block, value);
    }

    /**
     * 同上，但按**方块定义**解析 —— /place 下单时建筑还不存在，只有 Block。
     */
    private static Object resolveConfigValue(Block block, String value) {
        var configs = block.configurations;
"""

PLACE_OLD = """        // ---- 约束 4：入队，交给引擎 ----
        BuildPlan plan = (config == null)
            ? new BuildPlan(x, y, rotation, block)
            : new BuildPlan(x, y, rotation, block, config);"""

PLACE_NEW = """        // ---- 约束 4：解析 config，再入队 ----
        //
        // 必须在这里把字符串解析成引擎对象：BuildingComp.configured() 按
        // value.getClass() 查 block.configurations，直接传 String 一律匹配不上，
        // 配置会**静默失效**（方块建出来了，但 config 是空的）。
        Object resolvedConfig = null;
        String configWarning = null;
        if (config != null) {
            String raw = String.valueOf(config);
            resolvedConfig = resolveConfigValue(block, raw);
            if (resolvedConfig instanceof String && !block.configurations.isEmpty()) {
                configWarning = "config '" + raw + "' was not recognised; " + block.name
                    + " expects " + block.configurations.keySet()
                    + " — it would silently do nothing";
            }
        }

        BuildPlan plan = (resolvedConfig == null)
            ? new BuildPlan(x, y, rotation, block)
            : new BuildPlan(x, y, rotation, block, resolvedConfig);"""

EXTRA_OLD = """        if (mat != null) extra.putRaw("materials", mat.toString());

        String verb = previous == null"""

EXTRA_NEW = """        if (mat != null) extra.putRaw("materials", mat.toString());
        if (resolvedConfig != null) extra.put("config", describeConfig(resolvedConfig));
        if (configWarning != null) extra.put("configWarning", configWarning);

        String verb = previous == null"""

RULES = [
    (RESOLVE_OLD, RESOLVE_NEW, "resolveConfigValue 加 Block 重载"),
    (PLACE_OLD, PLACE_NEW, "place 里解析 config"),
    (EXTRA_OLD, EXTRA_NEW, "响应回显解析结果与警告"),
]


def main():
    text = A.read_text(encoding="utf-8")
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
    A.write_text(text, encoding="utf-8")
    print("\nActor.java 已更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
