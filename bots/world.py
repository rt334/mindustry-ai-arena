#!/usr/bin/env python3
"""世界快照：把 WS 的增量帧合成一个可查询的只读视图。

**这是策略唯一能看到的东西。** 它等于「一个真人玩家在同队时看到的一切」——
不含任何接口没给的信息（`docs/DESIGN.md` §7.9：只暴露规则，不暴露结论）。

### 八个通道里有什么

| 通道 | 内容 |
|---|---|
| `state` | tick / playing / paused / fog / team / teamId / worldW / worldH / 计数 |
| `units` | 己方全部 + **当前视野内**的敌方（fog 生效，`visibleUnits` 按 `safeVisible` 裁） |
| `buildings` | 己方全部 + 视野内敌方；**库存只给自己的队伍** |
| `factory` | 己方工厂：plan / progress / requirements / items / front |
| `drill` | 己方矿机：dominantItem / itemsPerSecond |
| `events` | 最近 40 条事件 |
| `rates` | 核心库存的净速率，**固定 5 秒窗口**（`{team, windowSeconds, core, stored}`） |
| `stalls` | 产线警报数组（与 REST `/stalls` 的 `stalls` 同源、同一份快照） |

`rates` 与 `stalls` 是后加的（2026-10-20）。在此之前 bot 只能 1 Hz 轮询它们，
而 `/stalls` 一次请求在服务端要等一个 tick。现在它们和其他通道同频推。

**加通道会摊薄每通道频率**：实测 6 通道时约 53 Hz/通道，8 通道时约 40 Hz/通道
（总吞吐约 320 帧/秒是上限）。bot 用 `hz=20`，离上限很远。
"""
from __future__ import annotations

import threading
import time


class World:
    """线程安全的只读世界视图。读线程写、决策线程读。"""

    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        with self._lock:
            self.tick = 0
            self.playing = False
            self.paused = False
            self.fog = True
            self.team = ""
            self.team_id = -1
            self.world_w = 0
            self.world_h = 0

            self.units: list[dict] = []
            self.buildings: list[dict] = []
            self.factory: list[dict] = []
            self.drill: list[dict] = []
            self.events: list[dict] = []

            # 静态地形缓存（`/map` 拉一次）。**WS 没有 map 通道**，
            # 因为地形一次就定死、推它属于浪费；但 bot 选址离不开它 ——
            # 不知道地块就下单，等于拿 `/place` 的 409 当探测器
            # （`skill/SKILL.md` 明令禁止这么干，实测也确实踩到了）。
            self.tiles: dict[tuple[int, int], dict] = {}
            self.tiles_loaded = False

            # 轮询来的两样（不是推送）
            self.rates_core: dict[str, float] = {}
            self.rates_stored: dict[str, float] = {}
            self.rates_tick = 0
            self.stalls: list[dict] = []
            self.stalls_tick = 0

            self.state_at = 0.0       # 最后一次 state 帧的墙钟
            self.frames = 0

    # ---------------------------------------------------------------- 写入

    def on_frame(self, ch, data, tick):
        with self._lock:
            self.frames += 1
            if ch == "state" and isinstance(data, dict):
                self.tick = data.get("tick", self.tick)
                self.playing = bool(data.get("playing"))
                self.paused = bool(data.get("paused"))
                self.fog = bool(data.get("fog"))
                self.team = data.get("team", self.team)
                self.team_id = data.get("teamId", self.team_id)
                self.world_w = data.get("worldW", self.world_w)
                self.world_h = data.get("worldH", self.world_h)
                self.state_at = time.time()
            elif ch == "units" and isinstance(data, list):
                self.units = data
            elif ch == "buildings" and isinstance(data, list):
                self.buildings = data
            elif ch == "factory" and isinstance(data, list):
                self.factory = data
            elif ch == "drill" and isinstance(data, list):
                self.drill = data
            elif ch == "events" and isinstance(data, list):
                self.events = data
            elif ch == "rates" and isinstance(data, dict):
                # WS 推的是**裸的** rates 对象；REST 那边多一层 {"rates": ...} 包装
                self._apply_rates(data.get("core"), data.get("stored"))
            elif ch == "stalls" and isinstance(data, list):
                self.stalls = data
                self.stalls_tick = self.tick

    def _apply_rates(self, core, stored):
        self.rates_core = {k: v.get("perSecond", 0.0)
                           for k, v in (core or {}).items()}
        self.rates_stored = {k: v.get("perSecond", 0.0)
                             for k, v in (stored or {}).items()}
        self.rates_tick = self.tick

    def set_rates(self, payload):
        """`/rates` 的响应体：`{"agent":..,"rates":{"core":{..},"stored":{..}}}`。

        WS 的 `rates` 通道走 `_apply_rates`（少一层包装）。两者保留是因为
        `--poll-hz` 还留着做兜底：推送通道万一断，轮询能把数据接上。
        """
        rates = (payload or {}).get("rates") or {}
        with self._lock:
            self._apply_rates(rates.get("core"), rates.get("stored"))

    def set_stalls(self, payload):
        with self._lock:
            self.stalls = (payload or {}).get("stalls") or []
            self.stalls_tick = self.tick

    def set_tiles(self, items):
        """`/map` 的 `tiles` 数组。按 (x,y) 索引；只收可见格。"""
        with self._lock:
            for t in items or []:
                self.tiles[(t.get("x"), t.get("y"))] = t
            self.tiles_loaded = True

    # ---------------------------------------------------------------- 查询

    def tile(self, x, y):
        with self._lock:
            return self.tiles.get((x, y))

    def buildable(self, x, y):
        """这一格能不能下建造单。

        ⚠ 这是**保守估计**，不是引擎判据：`/map` 给 `floor` / `block` /
        `overlay` / `liquid` / `deep` / `drop`，但**没给 `solid` / `passable`**。
        所以这里只能排除明显不能建的情况。真正的判据仍是引擎，
        我们只是把「一眼就知道会失败」的那些先筛掉。

        **`liquid` 为 `"air"` 表示没有液体**（`HttpApi.putLiquidInfo:4934`），
        不是「有液体」—— 把 `"air"` 当真会把整张图判成不可建
        （实测踩过一次：核心四周全被判死）。

        `block == "air"` 只说明**没有建筑**，不说明地面平 ——
        矿脉挂 `overlay`，而矿脉上是可以建的（钻机就建在上面）。
        """
        t = self.tile(x, y)
        if not t or not t.get("visible"):
            return False
        if t.get("block") != "air":
            return False
        if t.get("deep"):
            return False
        floor = str(t.get("floor", ""))
        if "water" in floor:
            return False
        liquid = str(t.get("liquid", ""))
        if liquid and liquid != "air":
            return False
        return True

    def age(self) -> float:
        """距上一帧 state 多久（秒）。用来发现「连接活着但游戏没在推」。"""
        with self._lock:
            return time.time() - self.state_at if self.state_at else 1e9

    def rate(self, item) -> float:
        """核心库存里某物品的净速率（/秒）。窗口内没变化就是 0。"""
        with self._lock:
            return self.rates_core.get(item, 0.0)

    def own(self, arr):
        """过滤出己方的条目（推送里也含视野内敌方）。"""
        tid = self.team_id
        return [b for b in arr if b.get("team") == tid]

    def cores(self):
        """己方核心。引擎里核心的 block 名都以 `core` 开头。"""
        return [b for b in self.own(self.buildings)
                if str(b.get("block", "")).startswith("core")]

    def block_at(self, x, y):
        for b in self.buildings:
            if b.get("x") == x and b.get("y") == y:
                return b
        return None

    def builders(self):
        """能建造的己方单位（`canBuild`）。"""
        return [u for u in self.own(self.units) if u.get("canBuild")]

    def unit_ids(self, pred=None):
        return [u["id"] for u in self.own(self.units)
                if pred is None or pred(u)]

    def stall_count(self) -> int:
        with self._lock:
            return len(self.stalls)

    def ready(self) -> bool:
        """够不够开始决策：有 tick、有队伍、有建筑表。"""
        with self._lock:
            return (self.tick > 0 and self.team_id >= 0
                    and self.world_w > 0 and self.state_at > 0)

    def snapshot(self) -> dict:
        """给日志/轨迹用的浅拷贝（**不要**交给策略去改）。"""
        with self._lock:
            return {
                "tick": self.tick,
                "playing": self.playing,
                "team": self.team,
                "teamId": self.team_id,
                "units": len(self.units),
                "buildings": len(self.buildings),
                "stalls": len(self.stalls),
                "rates": dict(self.rates_core),
            }
