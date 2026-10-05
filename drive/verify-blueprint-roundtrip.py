#!/usr/bin/env python3
"""蓝图往返验证 —— 证「导出去再导回来能重建」。

上一轮 `verify-all.py` 里这项只拿到 `placed:0/skipped:2`：导回的位置被地形或
视野挡了。端点给了结构化拒绝，那没错，但「能重建」这件事没被证明。

这次的做法：
  1. 在已知空地建 4 个方块（3 带子 + 1 钻机）
  2. 导出那一小块
  3. select 另一片**确认过的**空地导入
  4. 轮询 /buildings 直到导入的方块出现（判据是状态，不是时长）
  5. 比对位置与方块名是否与源一致

这样证明的是「往返保真」，不只是「端点不报错」。
"""
import base64
import json
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

ROT = {(1, 0): 0, (0, 1): 1, (-1, 0): 2, (0, -1): 3}


def main():
    toks, _ = load_tokens()
    a = Arena("beta", toks["beta"])

    core = None
    t0 = time.monotonic()
    while time.monotonic() - t0 < 120:
        try:
            core = next((b for b in a.buildings() if b["block"].startswith("core")), None)
        except Exception:
            core = None
        if core:
            break
        time.sleep(1)
    if not core:
        print("等不到核心")
        return 1
    cx, cy = core["x"], core["y"]
    print(f"核心 ({cx},{cy})")

    # ── 1. 在一小片空地里挑地方 ────────────────────────────────────────
    R = 22
    ts = a.map(cx - R, cy - R, 2 * R + 1, 2 * R + 1)
    g = {(t["x"], t["y"]): t for t in ts}

    def free(p):
        t = g.get(p)
        return bool(t and (t.get("block") or "air").strip() in ("", "air"))

    def free_rect(x, y, w, h):
        return all(free((x + dx, y + dy)) for dy in range(h) for dx in range(w))

    src = dst = None
    for y in range(cy - R, cy + R + 1):
        for x in range(cx - R, cx + R + 1):
            if src is None and free_rect(x, y, 4, 2):
                src = (x, y)
            elif src and dst is None and free_rect(x, y, 4, 2) \
                    and abs(x - src[0]) + abs(y - src[1]) > 6:
                dst = (x, y)
            if src and dst:
                break
        if src and dst:
            break
    if not src or not dst:
        print(f"找不到两块空地 src={src} dst={dst}")
        return 1
    print(f"源 {src}  目标 {dst}")

    # ── 2. 在源位置建 4 个方块 ────────────────────────────────────────
    want = {(src[0] + i, src[1]): "conveyor" for i in range(3)}
    want[(src[0], src[1] + 1)] = "router"
    print("\n== 建源方块 ==")
    for (x, y), blk in want.items():
        try:
            a.post("place", x=x, y=y, block=blk, rot=0)
            print(f"  ({x},{y}) {blk}")
        except ArenaError as e:
            print(f"  ({x},{y}) {blk} 失败 {e.code}")
        time.sleep(0.2)

    print("  等建成（判据是状态）……")
    t0 = time.monotonic()
    while time.monotonic() - t0 < 90:
        try:
            got = {(b["x"], b["y"]) for b in a.buildings()}
        except Exception:
            got = set()
        if set(want) <= got:
            break
        time.sleep(0.5)
    got = {(b["x"], b["y"]) for b in a.buildings()}
    print(f"  到位 {len(set(want) & got)}/{len(want)}")

    # ── 3. 导出 ───────────────────────────────────────────────────────
    print("\n== 导出 ==")
    try:
        r = a.get("blueprint", x=src[0] - 1, y=src[1] - 1, w=6, h=4)
    except ArenaError as e:
        print(f"  失败 {e.code} {e.message[:120]}")
        return 1
    print(f"  count={r.get('count')}  format={r.get('format')}")
    plain = base64.b64decode(r["data"]).decode("utf-8")
    src_blocks = json.loads(plain)["blocks"]
    for b in src_blocks:
        print(f"    dx={b['dx']} dy={b['dy']} {b['block']} rot={b['rot']}")
    if not any(b["block"] == "router" for b in src_blocks):
        print("  !! 导出的内容里没有 router —— 说明导错了地方")
        return 1

    # ── 4. 导入到目标位置 ─────────────────────────────────────────────
    print("\n== 导入 ==")
    try:
        r2 = a.post("blueprint", x=dst[0] - 1, y=dst[1] - 1, data=r["data"])
        print(f"  {json.dumps(r2, ensure_ascii=False)[:220]}")
    except ArenaError as e:
        print(f"  被拒 {e.code}: {e.message[:200]}")

    # ── 5. 验证重建 ───────────────────────────────────────────────────
    print("\n== 等导入的方块出现（判据是状态）==")
    expect = {(dst[0] - 1 + b["dx"], dst[1] - 1 + b["dy"]): b["block"]
              for b in src_blocks}
    t0 = time.monotonic()
    hit = set()
    while time.monotonic() - t0 < 90:
        try:
            got = {(b["x"], b["y"]): b["block"] for b in a.buildings()}
        except Exception:
            got = {}
        hit = {p for p, blk in expect.items() if got.get(p) == blk}
        if len(hit) == len(expect):
            break
        time.sleep(1)
    print(f"  位置+方块名都一致: {len(hit)}/{len(expect)}")
    for p, blk in sorted(expect.items()):
        mark = "✓" if p in hit else "✗"
        print(f"    {mark} {p} 期望 {blk}")
    print()
    if len(hit) == len(expect):
        print("  **蓝图往返保真：通过**")
        return 0
    print("  **往返没完全对** —— 见上面的 ✗")
    return 1


if __name__ == "__main__":
    sys.exit(main())
