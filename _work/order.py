#!/usr/bin/env python3
"""下单工具：place 后把坐标追加进 pending.json，供动态加速器使用。"""
import json, sys
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

PATH = r"C:\dsh\ai-arena\_work\pending.json"


def order(specs, note=""):
    a = Arena("alpha", ALPHA)
    errs = a.place_many(specs, workers=6)
    try:
        cur = [tuple(p) for p in json.load(open(PATH))]
    except Exception:
        cur = []
    cur += [(s[0], s[1]) for s in specs]
    json.dump([list(p) for p in dict.fromkeys(cur)], open(PATH, "w"))
    print(f"{note} 下单 {len(specs)} errs={errs} pending={len(set(cur))}")
    return errs


if __name__ == "__main__":
    # 阶段 27 的西南煤线并入清单
    S = []
    for x in range(27, 33):
        S.append((x, 131, "conveyor", 2))
    for y in range(107, 131):
        S.append((27, y, "conveyor", 3))
    for x in range(27, 36):
        S.append((x, 106, "conveyor", 0))
    S += [(28, 128, "mechanical-drill", 0), (29, 129, "mechanical-drill", 0)]
    order(S, "西南煤线登记")
