#!/usr/bin/env python3
"""setup 泄漏的三项规则 —— 存了原值才能恢复。

现状：setup 只保存并恢复了 editor 与 staticFog：
    boolean prevEditor = r.editor;         (3134)
    boolean prevStaticFog = r.staticFog;   (3142)
    ... 
    r.editor = prevEditor;                 (3293)
    r.staticFog = prevStaticFog;           (3294)

而中途还改了三项，**没存也没恢复**：
    r.enemyCoreBuildRadius = 0f;      (2988)  默认 400f ≈ 50 格
    r.blockWhitelist = false;         (3006)
    r.bannedBlocks.clear();           (3007)

后果：
  · 核心保护圈没了（Rules.java:295 是 protectCores ? enemyCoreBuildRadius + extra : 0），
    归零之后就没人拦得住「贴着别人核心造炮塔」—— 对等性直接被破坏。
  · 地图若用 bannedBlocks 禁过某些方块，setup 之后变成可建。

修法照抄同文件里 editor/staticFog 的写法：先存原值，再在恢复段还原。
"""
import pathlib
import sys

H = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\HttpApi.java")

SAVE_OLD = """            boolean prevStaticFog = r.staticFog;
            r.staticFog = false;"""

SAVE_NEW = """            boolean prevStaticFog = r.staticFog;
            r.staticFog = false;

            // 下面还会临时关掉核心保护圈、清空禁用方块表 —— 同样必须先存原值。
            // 漏了恢复的后果比 staticFog 更重：
            //   enemyCoreBuildRadius 默认 400f（≈50 格），Rules.java:295 是
            //       protectCores ? enemyCoreBuildRadius + extraCoreBuildRadius : 0
            //   归零之后再没人拦得住「贴着别人核心造炮塔」。
            //   bannedBlocks 则可能被地图用来禁方块，清空后那些方块变成可建。
            float prevCoreRadius = r.enemyCoreBuildRadius;
            boolean prevBlockWhitelist = r.blockWhitelist;
            arc.struct.ObjectSet<mindustry.world.Block> prevBanned = new arc.struct.ObjectSet<>();
            prevBanned.addAll(r.bannedBlocks);"""

RESTORE_OLD = """            // 恢复 editor 与 staticFog 状态
            r.editor = prevEditor;
            r.staticFog = prevStaticFog;"""

RESTORE_NEW = """            // 恢复 editor / staticFog / 核心保护圈 / 禁用方块表
            r.editor = prevEditor;
            r.staticFog = prevStaticFog;
            r.enemyCoreBuildRadius = prevCoreRadius;
            r.blockWhitelist = prevBlockWhitelist;
            r.bannedBlocks.clear();
            r.bannedBlocks.addAll(prevBanned);"""

RULES = [
    (SAVE_OLD, SAVE_NEW, "存原值"),
    (RESTORE_OLD, RESTORE_NEW, "恢复原值"),
]


def main():
    text = H.read_text(encoding="utf-8")
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
    H.write_text(text, encoding="utf-8")
    print("\nHttpApi.java：setup 的规则泄漏已修")
    return 0


if __name__ == "__main__":
    sys.exit(main())
