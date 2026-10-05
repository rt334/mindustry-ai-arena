#!/usr/bin/env python3
"""给建筑加 id —— 否则 /command?action=commandBuilding 根本没法调用。

实测：/buildings 的字段是
    ['x','y','team','block','health','maxHealth','enabled','efficiency',
     'rotation','items','liquids','fogRadius']
**没有 id**。而 commandBuilding 的签名是
    commandBuilding(Team team, int[] buildingIds, float tx, float ty)
必须传 buildingIds —— 于是这个 action 对任何客户端都是死路：
拿不到 id，就调不了。

三处改动：
  Snapshot.BuildInfo   加 id 字段与构造参数
  采集处                传 b.id
  visibleBuildings     输出 id
"""
import pathlib
import sys

SNAP = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\Snapshot.java")
API = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\HttpApi.java")

RULES = [
    (SNAP, "        public final int rotation;",
     "        /** 建筑的唯一 id。**必须暴露** —— /command?action=commandBuilding\n"
     "         *  要求传 buildingIds，没有它这个 action 谁都调不了。 */\n"
     "        public final int id;\n\n"
     "        public final int rotation;", 1, "BuildInfo 加 id 字段"),

    (SNAP, "BuildInfo(int x, int y, int team, String block,",
     "BuildInfo(int id, int x, int y, int team, String block,", 1, "构造签名加 id"),

    (SNAP, """            this.x = x; this.y = y; this.team = team; this.block = block;""",
     """            this.id = id;
            this.x = x; this.y = y; this.team = team; this.block = block;""", 1,
     "构造体赋值"),

    (SNAP, """                list.add(new BuildInfo(
                    b.tileX(), b.tileY(), b.team.id, b.block.name,""",
     """                list.add(new BuildInfo(
                    b.id, b.tileX(), b.tileY(), b.team.id, b.block.name,""", 1, "采集处传 b.id"),
]


def main():
    texts = {SNAP: SNAP.read_text(encoding="utf-8"), API: API.read_text(encoding="utf-8")}
    bad = []
    for path, old, new, want, label in RULES:
        t = texts[path]
        n = t.count(old)
        if n != want:
            bad.append(f"{path.name}: {n} 次（期望 {want}）→ {label}")
            print(f"  !! {n}/{want}  {label}")
            continue
        texts[path] = t.replace(old, new, 1)
        print(f"  ✓ {n} 处  {label}")

    # 序列化：把 id 加在 team 之后
    t = texts[API]
    anchor = '.put("team", b.team)'
    n = t.count(anchor)
    print(f"  · /buildings 序列化锚点 {anchor} 命中 {n} 处")
    if n >= 1:
        texts[API] = t.replace(anchor, anchor + '.put("id", b.id)', 1)
        print(f"  ✓ 已在第 1 处加上 id")
    else:
        bad.append("找不到 /buildings 的序列化锚点")

    if bad:
        print("\n有问题，未写盘：")
        for b in bad:
            print("   " + b)
        return 1
    for p, t in texts.items():
        p.write_text(t, encoding="utf-8")
    print("\n建筑 id 已暴露")
    return 0


if __name__ == "__main__":
    sys.exit(main())
