"""示例策略：只做一件事 —— 证明「感知 → 决策 → 执行 → 反馈」这一圈是通的。

它**刻意不是**一个能打的策略：不做采矿、不做物流规划、不做兵种。
真正的策略由 LLM 写（见 `bots/README.md`）。

它做的事：

1. `setup` 找到己方核心；
2. 从核心外环（与核心正交相邻的边格）挑一格可建的空地，铺一段朝核心的传送带；
3. 下一拍读 `world.buildings` —— 那一格**真的出现了**吗？`sendsTo` 指向核心吗？
4. 把结论记进 `mem`，并且此后不再重复下单。

第 3 步是关键：`/place` 返回 ok 只是**入队**。这个示例的策略价值不大，
验证价值很大 —— 它是「bot 到引擎」的最小闭环。

`rot` 的取值已在 `bots/actions.py` 里写明：0 东 / 1 南 / 2 西 / 3 北，顺时针。
"""
from __future__ import annotations

from .. import actions


def _rot_into(tx, ty, ax, ay, n):
    """外环格 → 指向核心**紧邻那一格**的朝向。

    **不能拿核心中心算方向**：核心 `size=5`，外环格到中心隔着好几格，
    「先横后纵」的近似会把它指向旁边一个空格（实测踩过：传送带建成了、
    方向也「对」，但货永远进不了核心）。
    正方块的外环格只与它的**一条边**正交相邻，按所在边直接给朝向才是准的。
    """
    if ty == ay - 1:
        return 1        # 在上边 → 朝南
    if ty == ay + n:
        return 3        # 在下边 → 朝北
    if tx == ax - 1:
        return 0        # 在左边 → 朝东
    if tx == ax + n:
        return 2        # 在右边 → 朝西
    return None


def _ring(ax, ay, n):
    """多格方块的外环格子 —— **只给正交相邻的边格，不含四角**。

    `/buildings` 的 `x,y` 是**中心**，不是左上角；多格方块（核心 `size=5`）
    的真实占位要用 `anchorX/anchorY/size` 算。用中心去 ±1 会全落在方块
    自己身上，于是每一格都「建不了」（实测踩过，还先被 `/place` 409 顶回一次）。

    对角格也排除：它不与方块任何一边相邻，传送带从那里出发无论朝哪个方向
    都进不了方块，而接口不会报错 —— 那是一条**完美对齐的死路**。
    """
    cells = []
    for x in range(ax, ax + n):
        cells.append((x, ay - 1))
    for x in range(ax, ax + n):
        cells.append((x, ay + n))
    for y in range(ay, ay + n):
        cells.append((ax - 1, y))
    for y in range(ay, ay + n):
        cells.append((ax + n, y))
    return cells


class Strategy:
    name = "demo-closed-loop"

    def setup(self, world):
        pass

    def decide(self, world, mem):
        cores = world.cores()
        if not cores:
            mem["note"] = "还没有核心"
            return []

        core = cores[0]
        cx, cy = core["x"], core["y"]
        ax = core.get("anchorX", cx)
        ay = core.get("anchorY", cy)
        n = core.get("size", 1)
        mem["core"] = (cx, cy)

        # ① 还没挑过格子 —— 挑一格核心外环上、**地块允许建造**的空地
        if "target" not in mem:
            if not world.tiles_loaded:
                mem["note"] = "等地形缓存"
                return []
            for tx, ty in _ring(ax, ay, n):
                if not (0 <= tx < world.world_w and 0 <= ty < world.world_h):
                    continue
                if not world.buildable(tx, ty):
                    continue
                rot = _rot_into(tx, ty, ax, ay, n)
                if rot is None:
                    continue
                mem["target"] = (tx, ty)
                mem["sent_at_tick"] = world.tick
                mem["verified"] = None
                return [actions.place(tx, ty, "conveyor", rot=rot)]

            mem["note"] = "核心外环没有可建的空地，放弃"
            return []

        # ② 已经下过单 —— 去看它到底有没有出现，**以及方向对不对**
        tx, ty = mem["target"]
        if mem.get("verified") is None:
            b = world.block_at(tx, ty)
            if b is not None:
                own = b.get("team") == world.team_id
                cells = {(x, y) for x in range(ax, ax + n)
                         for y in range(ay, ay + n)}
                sends = b.get("sendsTo") or []
                into = any(tuple(s) in cells for s in sends
                           if isinstance(s, (list, tuple)) and len(s) == 2)
                mem["verified"] = own and into
                mem["note"] = (
                    f"({tx},{ty}) 已建成 {b.get('block')}"
                    + ("" if own else "（不是我方的）")
                    + ("" if into else f" 但方向不对，sendsTo={sends}"))
            elif world.tick - mem.get("sent_at_tick", 0) > 60 * 10:
                mem["verified"] = False
                mem["note"] = f"({tx},{ty}) 下单 10 秒仍未出现"
            else:
                return []           # 还在建，别重复下单

        return []

    def teardown(self, world):
        pass
