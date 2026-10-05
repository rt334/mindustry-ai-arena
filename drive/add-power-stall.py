#!/usr/bin/env python3
"""电力断开：补上「需要电但没电」这一类报警。

红线是「人类肉眼能看到的」：
  ✓ 电力断开 —— 屏幕上电源方块旁边就是空的/红的电力条，连线断没断一眼可见
  ✓ 矿机不出货 —— 钻头不转
  ✓ 明显的堵点 —— 带子完全不动
  ✗ 减速瓶颈 —— 带子在动但慢，肉眼看不出来

现状缺口：classify() 只覆盖了「发电机缺燃料」，**消费电的方块没电时不报警** ——
laser-drill 没电挖不动，属于「矿机不出货」里肉眼可见的一种，却一条都报不出来。

字段选择：不能用 Block.consumesPower —— 它默认就是 true（Block.java:53），
每个方块都「消费电」。得遍历 block.consumers 找 ConsumePower。
"""
import pathlib
import sys

S = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\StallWatch.java")

CLASSIFY_OLD = """    private static String classify(Building b) {
        // ---- 传送带：引擎自己的 clogHeat ----
        if (b instanceof Conveyor.ConveyorBuild cb) {"""

CLASSIFY_NEW = """    private static String classify(Building b) {
        // ---- 需要电但没电：屏幕上就是空/红的电力条 ----
        //
        // 放在最前面：这是最根本的原因，也是肉眼最先看到的。
        // 发电机不消费电（它们输出电），所以不会被这条命中。
        if (needsPower(b) && b.power != null && b.power.status <= 0.001f) {
            int links = (b.power.links == null) ? 0 : b.power.links.size;
            // 没接任何线 / 接了线但没电 —— 两种都是玩家看得见的
            return links == 0 ? "powerUnconnected" : "powerStarved";
        }

        // ---- 传送带：引擎自己的 clogHeat ----
        if (b instanceof Conveyor.ConveyorBuild cb) {"""

HELPER_ANCHOR = """    /**
     * 列出这个方块当前缺什么。**这是本模块最有用的输出。**"""

HELPER = """    /**
     * 这个方块是否**消费**电。
     *
     * 不能用 Block.consumesPower —— 它默认就是 true（Block.java:53），
     * 每个方块都会命中。得看它有没有注册 ConsumePower。
     */
    private static boolean needsPower(Building b) {
        if (b.block.consumers == null) return false;
        for (var c : b.block.consumers) {
            if (c instanceof ConsumePower) return true;
        }
        return false;
    }

    /**
     * 列出这个方块当前缺什么。**这是本模块最有用的输出。**"""

CAUSE_OLD = """        if ("missingInput".equals(kind)) return "starved";
"""

CAUSE_NEW = """        if ("missingInput".equals(kind)) return "starved";
        // 电力问题既不是「上游没来货」也不是「下游不收」—— 查电网
        if ("powerUnconnected".equals(kind)) return "unpowered";
        if ("powerStarved".equals(kind)) return "underpowered";
"""

RULES = [
    (CLASSIFY_OLD, CLASSIFY_NEW, "classify 加电力检查"),
    (HELPER_ANCHOR, HELPER, "加 needsPower()"),
    (CAUSE_OLD, CAUSE_NEW, "causeOf 加 unpowered / underpowered"),
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
