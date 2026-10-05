#!/usr/bin/env python3
"""/diag 加规则快照 —— 让 setup 的规则恢复可验证。

之前只能靠读代码确认 setup 有没有还原 enemyCoreBuildRadius 等，
因为没有任何端点暴露这些规则值。加一个 rules 块，以后一眼可查。
"""
import pathlib
import sys

H = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena\HttpApi.java")

OLD = """                .put("teamBatchSends", Diag.teamBatchSends())
                .put("fullViewSends", Diag.fullViewSends())
                .put("spectatorRouted", Diag.spectatorRouted())
                .putRaw("fogState", fogStateJson())"""

NEW = """                .put("teamBatchSends", Diag.teamBatchSends())
                .put("fullViewSends", Diag.fullViewSends())
                .put("spectatorRouted", Diag.spectatorRouted())
                // 规则快照。setup 会临时改其中几项（关保护圈、清禁用表、关 staticFog），
                // 不暴露出来就只能靠读代码确认它有没有还原。
                .putRaw("rules", new Json.Obj()
                    .put("enemyCoreBuildRadius", r.enemyCoreBuildRadius)
                    .put("blockWhitelist", r.blockWhitelist)
                    .put("bannedBlocks", r.bannedBlocks.size)
                    .put("editor", r.editor)
                    .put("fog", r.fog)
                    .put("staticFog", r.staticFog)
                    .put("infiniteResources", r.infiniteResources)
                    .put("buildCostMultiplier", r.buildCostMultiplier)
                    .put("buildSpeedMultiplier", r.buildSpeedMultiplier)
                    .toString())
                .putRaw("fogState", fogStateJson())"""


def main():
    text = H.read_text(encoding="utf-8")
    n = text.count(OLD)
    if n != 1:
        print(f"!! {n} 次命中（应为 1），未写盘")
        return 1
    H.write_text(text.replace(OLD, NEW), encoding="utf-8")
    print("HttpApi.java：/diag 加了 rules 快照")
    return 0


if __name__ == "__main__":
    sys.exit(main())
