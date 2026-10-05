#!/usr/bin/env python3
"""验证 P1 四条：A8 shape=path / A7 place 的 config / B2 buildingAt / 补2 stall cause。

性能注意：`/map` 与 `/buildings` 每次都是一次 HTTP 往返，逐格调用会把脚本拖死
（第一版就是这么卡住的）。这里一次性拉图、一次性拉建筑表，本地索引后复用。

A8 要验两件事：
  1. 拐点处的朝向跟着路径转（L 形：横段朝东、竖段朝南）
  2. 斜线自动补成正交阶梯 —— Bresenham 会产生对角步，而对角相邻的两格
     物理上接不上（传送带只认四邻）
"""
import json
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])

ROT_NAME = {0: "东", 1: "南", 2: "西", 3: "北"}
R = 30


def load_grid(cx, cy, r=R):
    """一次拉 (2r+1)² 格（≤4096），本地索引。"""
    w = 2 * r + 1
    return {(t["x"], t["y"]): t for t in a.map(cx - r, cy - r, w, w)}


def free(g, x, y):
    t = g.get((x, y))
    if not t or not t.get("visible"):
        return False
    return (t.get("block") or "air").strip() in ("", "air")


def find_rect(g, cx, cy, w, h):
    for y in range(cy - 26, cy + 27 - h):
        for x in range(cx - 26, cx + 27 - w):
            if all(free(g, x + dx, y + dy) for dy in range(h) for dx in range(w)):
                return x, y
    return None


def bidx():
    """一次拉建筑表，建坐标索引。"""
    return {(b["x"], b["y"]): b for b in a.buildings()}


def place_path(spec, block="conveyor"):
    """底层调用：客户端库的 post(path, ...) 首参名就叫 path，会和参数重名。"""
    return a._call("place", {"shape": "path", "path": spec, "block": block}, "POST")


def main():
    st = a.state()
    core = next(b for b in a.buildings() if b["block"].startswith("core"))
    cx, cy = core["x"], core["y"]
    print(f"tick={st['tick']}  核心锚点 ({cx},{cy})  {core['items']}")

    g = load_grid(cx, cy)
    print(f"地图已加载 {len(g)} 格（一次 HTTP）")

    # ================= A8 · L 形折线 =================
    print("\n== A8 shape=path · L 形拐点 ==")
    spot = find_rect(g, cx, cy, 6, 5)
    if not spot:
        print("  找不到 6x5 空地")
        return 1
    ox, oy = spot
    spec = f"{ox},{oy};{ox+5},{oy};{ox+5},{oy+4}"
    print(f"  路径 ({ox},{oy}) → ({ox+5},{oy}) → ({ox+5},{oy+4})")
    try:
        r = place_path(spec)
    except ArenaError as e:
        print(f"  ERR code={e.code} {e.message}")
        return 1
    print(f"  tiles={r.get('tiles')}  {r.get('message')}")
    rots = r.get("rotations") or []
    for (x, y, rot) in rots:
        print(f"    ({x:>3},{y:>3}) rot={rot} {ROT_NAME.get(rot, '?')}")

    hseg = sorted({t for (x, y, t) in rots if y == oy})
    vseg = sorted({t for (x, y, t) in rots if x == ox + 5})
    print(f"  横段(y={oy}) 朝向 {hseg}  期望 [0]=东")
    print(f"  竖段(x={ox+5}) 朝向 {vseg}  期望 [1]=南")

    # ================= A8 · 斜线补正交 =================
    print("\n== A8 shape=path · 斜线补正交点 ==")
    spot2 = find_rect(g, cx, cy, 8, 8)
    if spot2:
        sx, sy = spot2
        try:
            r2 = place_path(f"{sx},{sy};{sx+4},{sy+4}")
            pts = [(x, y) for (x, y, _) in (r2.get("rotations") or [])]
            gaps = []
            for i in range(1, len(pts)):
                dx = abs(pts[i][0] - pts[i-1][0])
                dy = abs(pts[i][1] - pts[i-1][1])
                if dx + dy != 1:
                    gaps.append((pts[i-1], pts[i]))
            print(f"  斜线 ({sx},{sy})→({sx+4},{sy+4})  展开 {len(pts)} 格（原始对角步只需 5 格）")
            print(f"  四邻连续: {not gaps}" + (f"  断裂={gaps}" if gaps else ""))
            print(f"  {' '.join(f'({x},{y})' for (x, y) in pts)}")
        except ArenaError as e:
            print(f"  ERR code={e.code} {e.message}")

    # ================= A7 · place 的 config =================
    print("\n== A7 /place 的 config 生效 ==")
    ct = a.get("content").get("blocks", [])
    sorter = next((b for b in ct if b.get("name") == "sorter"), None)
    print(f"  sorter 成本: {sorter.get('requirements') if sorter else '未找到'}")
    # 拿一个真实存在的、带配置的方块做对照
    print(f"  sorter 声明支持的配置类型: "
          f"{[k for k in (sorter or {}).keys() if k in ('configurations', 'configType')]}"
          f"（/content 不暴露这个字段，看响应里的 configWarning 更直接）")

    spot3 = find_rect(g, cx, cy, 3, 20)
    if spot3:
        tx, ty = spot3
        print(f"  在 ({tx},{ty}) 放 sorter config=coal")
        try:
            r3 = a.post("place", x=tx, y=ty, block="sorter", config="coal")
            print(f"  响应: {json.dumps(r3, ensure_ascii=False)[:300]}")
        except ArenaError as e:
            print(f"  ERR code={e.code} {e.message}")
        # 再试一个不支持的 config，看警告是否出现
        try:
            r4 = a.post("place", x=tx + 1, y=ty, block="conveyor", config="coal")
            print(f"  对照（给 conveyor 传 config）: {json.dumps(r4, ensure_ascii=False)[:240]}")
        except ArenaError as e:
            print(f"  对照 ERR code={e.code} {e.message}")

        idx = a.poll_until(lambda: bidx().get((tx, ty)), timeout=120)
        if idx:
            print(f"  sorter 建成后 config 字段 = {idx.get('config')!r}   ← 期望含 coal")

    # ================= B2 =================
    print("\n== B2 /units 的 buildingAt ==")
    row = find_rect(g, cx, cy, 8, 1)
    if row:
        rx, ry = row
        for i in range(8):
            try:
                a.place(rx + i, ry, "conveyor", rot=0)
            except ArenaError:
                pass
        u = (a.units() or [{}])[0]
        print(f"  unit {u.get('id')} {u.get('type')}  buildingAt={json.dumps(u.get('buildingAt'), ensure_ascii=False)}")
    else:
        print("  找不到空地")

    # ================= 补2 =================
    print("\n== 补2 /stalls 的 cause ==")
    stalls = a.stalls()
    print(f"  当前 stall 数 = {len(stalls)}")
    for s in stalls[:6]:
        print(f"    ({s['x']},{s['y']}) {s['block']} kind={s.get('kind')} "
              f"cause={s.get('cause')} outputAccepts={s.get('outputAccepts')}")
    if not stalls:
        print("  （当前没有堵点；cause 字段的取值逻辑见 StallWatch.causeOf）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
