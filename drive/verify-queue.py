#!/usr/bin/env python3
"""专抓一次队列非空：下完立刻查，不找连续空地。"""
import json
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])

core = next(b for b in a.buildings() if b["block"].startswith("core"))
cx, cy = core["x"], core["y"]

# 收集视野内所有可建空地
free = []
for y in range(max(0, cy - 50), cy + 51):
    for x in range(max(0, cx - 50), cx + 51):
        t = a.map(x, y, 1, 1)
        if not t or not t[0].get("visible"):
            continue
        if (t[0].get("block") or "air").strip() not in ("", "air"):
            continue
        if a.building_at(x, y):
            continue
        free.append((x, y))

print(f"可建空地 {len(free)} 格")
# 挑离核心最远的，逼单位走路，队列才会积压
free.sort(key=lambda p: -((p[0] - cx) ** 2 + (p[1] - cy) ** 2))

placed = 0
for (x, y) in free[:80]:
    try:
        a.place(x, y, "conveyor", rot=0)
        placed += 1
    except ArenaError as e:
        if e.code == 1004:
            print(f"  撞到队列上限: {e.message}")
            break

q = a.queue()
b0 = (q.get("builders") or [{}])[0]
print(f"\n连下 {placed} 个后立刻查 /queue：plans={b0.get('plans')}")
lst = b0.get("planList") or []
for p in lst[:6]:
    print(f"  {json.dumps(p, ensure_ascii=False)}")
if len(lst) > 6:
    print(f"  ...（共 {len(lst)} 条）")
if not lst:
    print("  （仍然为空 —— 单位消化得比 HTTP 往返还快）")
