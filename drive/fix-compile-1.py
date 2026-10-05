#!/usr/bin/env python3
"""修三个编译错误（都是我写错类型/字段名）。

  · Vars.state.tick 是 double，赋给 int/long 要显式转
  · Agent 上没有 team 字段，是 team() 方法（route 里就是这么用的）
"""
import pathlib
import sys

MOD = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena")

RULES = [
    (MOD / "Audit.java",
     "try { tick = Vars.state == null ? -1 : Vars.state.tick; }",
     "try { tick = Vars.state == null ? -1 : (int) Vars.state.tick; }"),
    (MOD / "HttpApi.java",
     "try { nowTick = Vars.state == null ? -1 : Vars.state.tick; }",
     "try { nowTick = Vars.state == null ? -1L : (long) Vars.state.tick; }"),
    (MOD / "HttpApi.java",
     "Audit.log(agentId, agent.team == null ? -1 : agent.team.id, action,",
     "Audit.log(agentId, agent.team() == null ? -1 : agent.team().id, action,"),
]


def main():
    ok = True
    for path, old, new in RULES:
        t = path.read_text(encoding="utf-8")
        n = t.count(old)
        if n != 1:
            print(f"  !! {path.name}: {n} 次")
            ok = False
            continue
        path.write_text(t.replace(old, new, 1), encoding="utf-8")
        print(f"  ✓ {path.name}: {old[:48]}…")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
