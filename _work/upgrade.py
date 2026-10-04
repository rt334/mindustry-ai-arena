#!/usr/bin/env python3
"""升级器：石墨够就把机械钻替换成 pneumatic-drill（0.10 -> 0.15 每格每秒，且不需要电）。

用法：python upgrade.py [最多替换台数]
只在石墨 >= 需要的数量时才动手，避免拆了旧钻机却造不出新的。
"""
import sys, time
sys.path.insert(0, r"C:\dsh\ai-arena\_work")
from arena_ops import Arena, ALPHA

a = Arena("alpha", ALPHA)
want = int(sys.argv[1]) if len(sys.argv) > 1 else 4
COST_G = 10  # pneumatic-drill 需要石墨 10

# 候选：机械钻（沙钻机除外）
cands = [(k, b) for k, b in a.buildings().items() if b["block"] == "mechanical-drill"]
print("机械钻候选:", [(k, b.get("items")) for k, b in cands])

done = 0
for k, b in cands:
    if done >= want:
        break
    core = [x for x in a.buildings().values() if x["block"] == "core-nucleus"][0]["items"]
    if core.get("graphite", 0) < COST_G + 5:
        print(f"石墨不足 ({core.get('graphite', 0)})，停止")
        break
    print(f"替换 {k} ...")
    a.break_many([k], workers=1)
    t0 = time.time()
    while time.time() - t0 < 40:
        if k not in a.buildings():
            break
        time.sleep(0.5)
    a.place_many([(k[0], k[1], "pneumatic-drill", b.get("rotation") or 0)], workers=1)
    t0 = time.time()
    while time.time() - t0 < 60:
        nb = a.buildings().get(k)
        if nb and nb["block"] == "pneumatic-drill":
            break
        time.sleep(0.5)
    nb = a.buildings().get(k)
    print("   ->", nb["block"] if nb else "缺失")
    if nb and nb["block"] == "pneumatic-drill":
        done += 1
print("完成替换:", done)
print("core:", [x for x in a.buildings().values() if x["block"] == "core-nucleus"][0]["items"])
