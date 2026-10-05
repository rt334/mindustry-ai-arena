#!/usr/bin/env python3
"""dump 核心东北那片格子的真实状态 —— 为什么 (290,102) / (290,103) 不可建。

/place 的 1008 只说「被 (290,103) 挡住」，不说是被什么挡住的。
这里把每格的 block / overlay / drop / solid 摊开看。
"""
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])

core = next(b for b in a.buildings() if b["block"].startswith("core"))
cx, cy = core["x"], core["y"]

x0, y0, w, h = cx - 4, cy - 12, 14, 22
tiles = a.map(x0, y0, w, h)
g = {(t["x"], t["y"]): t for t in tiles}

print(f"核心锚点 ({cx},{cy})  核心占 x[{cx},{cx+4}] y[{cy},{cy+4}]")
print(f"dump x[{x0},{x0+w-1}] y[{y0},{y0+h-1}]\n")

# 建筑表
bidx = {(b["x"], b["y"]): b for b in a.buildings()}

hdr = "     " + "".join(f"{x % 100:>3}" for x in range(x0, x0 + w))
print(hdr)
for y in range(y0, y0 + h):
    row = f"{y:>4} "
    for x in range(x0, x0 + w):
        t = g.get((x, y))
        b = bidx.get((x, y))
        if b:
            row += "  @" if not b["block"].startswith("core") else "  O"
        elif t is None:
            row += "  ?"
        elif not t.get("visible"):
            row += "  #"
        else:
            blk = (t.get("block") or "air").strip()
            ov = (t.get("overlay") or "air").strip()
            if blk not in ("", "air"):
                row += "  X"          # 有实体方块
            elif ov != "air":
                row += "  o"          # 矿
            else:
                row += "  ."          # 空地
    print(row)

print("\n图例: O=核心  @=其它建筑  X=有方块(不可建)  o=矿  .=空地  #=不可见  ?=拉不到")

print("\n== 关键格明细 ==")
for (x, y) in [(290, 102), (290, 103), (289, 103), (291, 103), (290, 101), (290, 99),
               (288, 105), (288, 106), (287, 106), (294, 106)]:
    t = g.get((x, y))
    b = bidx.get((x, y))
    if t is None:
        print(f"  ({x},{y}) 拉不到")
        continue
    blk = (t.get("block") or "air").strip()
    ov = (t.get("overlay") or "air").strip()
    print(f"  ({x},{y}) block={blk:<14} overlay={ov:<14} drop={t.get('drop')!r:<8} "
          f"build={t.get('build')} "
          + (f"建筑={b['block']}" if b else ""))
