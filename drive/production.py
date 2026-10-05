#!/usr/bin/env python3
"""产线工具库：自动选点 + 布线。**不要再用写死的坐标。**

踩过的坑：前几版把某一局探查到的坐标写死进脚本（煤钻 (290,100)、沙钻
(289,108)…）。下一局 `-Map veins` 重新随机的矿脉位置一变，全线报
`1009 placement invalid`（那格没矿）或 `1008 footprint blocked`（被占了），
而错误信息不会告诉你「地图换了」。

正确做法：每局开跑前重新探查，坐标一律现算。

提供的原语：
    fetch(R)              拉核心周边地图（自动重试到快照就绪）
    free_map()            空地块集合 + 矿脉索引
    find_site(kind, size, near)   找离核心最近的、size×size 全空且有该矿的点位
    route(a, b)           BFS 布一条带子路径（返回经过的格，末端自动朝目标）
    place_path(pts, blk)  下单并校验 accepted == requested
"""
import collections
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

BASE_SIZE = {"core-nucleus": 5, "core-foundation": 4, "core-shard": 3}
BLOCK_SIZE = {}


class World:
    def __init__(self, agent="beta", R=24):
        toks, _ = load_tokens()
        self.a = Arena(agent, toks[agent])
        self.R = R
        self.core = None
        t0 = time.monotonic()
        while time.monotonic() - t0 < 120:
            try:
                self.core = next((b for b in self.a.buildings()
                                  if b["block"].startswith("core")), None)
            except Exception:
                self.core = None
            if self.core:
                break
            time.sleep(1)
        if not self.core:
            raise RuntimeError("等不到核心")
        self.cx, self.cy = self.core["x"], self.core["y"]
        self.refresh()

    # ---------------------------------------------------------------- 地图
    def refresh(self):
        R = self.R
        ts = self.a.map(self.cx - R, self.cy - R, 2 * R + 1, 2 * R + 1)
        self.g = {(t["x"], t["y"]): t for t in ts}
        self.occupied = set()
        for b in self.a.buildings():
            n = BLOCK_SIZE.get(b["block"])
            x, y = b["x"], b["y"]
            self.occupied.add((x, y))
        self.planned = set()

    def ore(self, p):
        t = self.g.get(p)
        if not t:
            return None
        o = (t.get("overlay") or "air").strip()
        if o.startswith("ore-"):
            return o[4:]
        d = (t.get("drop") or "").strip()
        return d or None

    def free(self, p):
        t = self.g.get(p)
        if not t or not t.get("visible"):
            return False
        if (t.get("block") or "air").strip() not in ("", "air"):
            return False
        return p not in self.planned

    def box(self, p, size):
        return [(p[0] + dx, p[1] + dy) for dy in range(size) for dx in range(size)]

    def site_ok(self, p, size):
        return all(self.free(q) for q in self.box(p, size))

    # ---------------------------------------------------------------- 选点
    def find_site(self, kind, size=2, max_d=40, min_ore=1):
        best = None
        for p in self.g:
            d = abs(p[0] - self.cx) + abs(p[1] - self.cy)
            if d > max_d:
                continue
            if not self.site_ok(p, size):
                continue
            n = sum(1 for q in self.box(p, size) if self.ore(q) == kind)
            if n < min_ore:
                continue
            key = (-n, d)
            if best is None or key < best[0]:
                best = (key, p, n)
        return (best[1], best[2]) if best else (None, 0)

    def find_site_near_core(self, size=2):
        """贴核心的空位（用于冶炼厂/压机这类要直接入库的）。"""
        cx, cy = self.cx, self.cy
        csz = 5
        out = []
        for p in self.g:
            if not self.site_ok(p, size):
                continue
            # 与核心脚印四邻相接
            touch = False
            for q in self.box(p, size):
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    n = (q[0] + dx, q[1] + dy)
                    if cx - 2 <= n[0] <= cx + 2 and cy - 2 <= n[1] <= cy + 2:
                        touch = True
            if touch:
                out.append((abs(p[0] - cx) + abs(p[1] - cy), p))
        out.sort()
        return out[0][1] if out else None

    # ---------------------------------------------------------------- 布线
    def route(self, a, b):
        """BFS 一条从 a 四邻到 b 四邻的路径。返回格列表（含起点终点）。"""
        if not self.free(a) or not self.free(b):
            return None
        prev = {a: None}
        q = collections.deque([a])
        while q:
            cur = q.popleft()
            if abs(cur[0] - b[0]) + abs(cur[1] - b[1]) == 1:
                path = [cur]
                while prev[path[-1]] is not None:
                    path.append(prev[path[-1]])
                path.reverse()
                path.append(b)
                return path
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (cur[0] + dx, cur[1] + dy)
                if n in prev or n == b:
                    continue
                if not self.free(n):
                    continue
                prev[n] = cur
                q.append(n)
        return None

    def ROT(self, frm, to):
        dx, dy = to[0] - frm[0], to[1] - frm[1]
        return {(1, 0): 0, (0, 1): 1, (-1, 0): 2, (0, -1): 3}[(dx, dy)]

    def lay(self, pts, block="conveyor", end_rot=1):
        """逐格下单（自己算朝向）。末格朝向必须由调用方给对 —— 它决定料往哪进，
        默认朝南只对「目标在末格下方」成立。"""
        ok, errs = 0, []
        for i, p in enumerate(pts):
            nxt = pts[i + 1] if i + 1 < len(pts) else None
            rot = end_rot if nxt is None else self.ROT(p, nxt)
            try:
                self.a.post("place", x=p[0], y=p[1], block=block, rot=rot)
                self.planned.add(p)
                ok += 1
            except ArenaError as e:
                errs.append(f"({p[0]},{p[1]}) {e.code}")
            time.sleep(0.12)
        return ok, errs

    def ready(self, coords, timeout=180):
        want = set(coords)
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            self.refresh()
            if want <= self.occupied:
                return True
            time.sleep(0.5)
        return False
