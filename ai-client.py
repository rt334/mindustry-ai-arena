#!/usr/bin/env python3
"""
AI 竞技场 · 示例 AI 客户端

它通过 HTTP 读局面、做决策、下达指令，完整打一局 PvP。
存在的意义是验证一件事：**这套 API 是否足够让 AI 真的打完一局**
（DESIGN.md P4 的验收标准：从开局建造到摧毁对方核心）。

策略是一个朴素的四阶段状态机：

    建设期   造太阳能板供电 + duo 炮塔防守
    造兵期   从核心生成攻击单位
    推进期   指挥部队向敌方核心方向推进（受视野约束，逐步扩展）
    攻击期   抵达后围攻敌方核心

关键约束（客户端必须自己处理）：
  - 单位与指挥目标都必须在己方视野内（指挥范围，唯一的自实现对等约束）
  - 单位视野半径约 21.75 格，所以推进必须是渐进的
  - spawn 只能在核心附近（也要满足视野约束）

用法：
    python ai-client.py --agent alpha --token <token>
    python ai-client.py --agent alpha --token <token> --verbose
"""

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------- 配置

# 单位视野半径（从 /content 查得，全单位统一 21.75）
VISION_RADIUS = 21.75

# 推进时每一步的目标距离，留出安全余量（视野边缘会出现抖动）
PUSH_STEP = 16.0

# 各阶段的目标数量
# 用大型太阳能板而不是小太阳能板。
# 小太阳能板只有 0.12 出力，喂不饱要 1.2 的工厂（Blocks.java:2621）
WANT_SOLAR_LARGE = 3
WANT_SOLAR = 6
# 防御
WANT_DUO = 6
WANT_SCATTER = 2
WANT_FACTORY_SOLAR = 5
WANT_TURRET = 5
# 出击门槛。真实 RTS 不会等满编才推 —— 而且产能是持续的，
# 攒够一支小部队就该压上去，让压力连续。实测等 8 架 flare 会因为
# 产能爬坡慢而一直卡在造兵期出不来。
WANT_ARMY = 6

# 工厂要生产的单位。单位只能从工厂出来 —— /spawn 已被服务端禁用。
# flare 是 air-factory 最便宜的产线（15 秒 / 15 硅）。
WANT_UNIT = "flare"

# 启动资金门槛：核心库存低于这个数就先去手动挖矿
# 冶炼链要攒够的硅。air-factory 要硅60，solar-panel 要硅8，
# 留点余量免得建到一半断料
RESERVE_SILICON = 150
RESERVE_COPPER = 350
RESERVE_LEAD = 250


class ArenaError(Exception):
    """HTTP 层或业务层的失败。"""

    def __init__(self, code, message):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


class Arena:
    """HTTP 客户端。统一响应信封与错误码处理都在这里。

    自带**自动重连**：服务端重启（改 mod 后很常见）或网络抖动时，请求会按指数
    退避重试，而不是让 AI 直接退出。重试期间 online 置 False，恢复后置回 True。

    注意「重连」在这里是幂等的：agent 与队伍的绑定保存在服务端，客户端只要
    重新发出请求即可，不需要重新注册。
    """

    def __init__(self, host, port, agent, token, verbose=False,
                 max_retries=6, base_delay=0.4, max_delay=8.0):
        # 注意结尾的斜杠：所有端点都在 /v1/{agent}/ 之下，
        # 拼路径时若不补这个斜杠会变成 /v1/alphastate。
        self.base = f"http://{host}:{port}/v1/{agent}/"
        self.root = f"http://{host}:{port}/"
        self.token = token
        self.verbose = verbose
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.online = True
        self.reconnects = 0
        self.stats = {"get": 0, "post": 0, "errors": 0, "retries": 0}

    def _delay_for(self, attempt):
        return min(self.base_delay * (2 ** attempt), self.max_delay)

    def _backoff(self, attempt, why):
        """退避等待。第一次掉线时把 online 置 False 并计数。"""
        if self.online:
            self.online = False
            self.reconnects += 1
        self.stats["retries"] += 1
        wait = self._delay_for(attempt)
        if self.verbose:
            print(f"[net] {why}；{wait:.1f}s 后重试 "
                  f"(第 {attempt + 1}/{self.max_retries} 次)")
        time.sleep(wait)

    def wait_online(self, timeout=120.0, interval=1.0):
        """轮询 /ping 直到服务端回来。用于启动时等服务器拉起。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                req = urllib.request.Request(self.root + "ping", method="GET")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    if json.loads(resp.read().decode("utf-8")).get("ok"):
                        if not self.online:
                            self.online = True
                            print(f"[net] 服务端已恢复（累计重连 {self.reconnects} 次）")
                        return True
            except Exception:
                pass
            time.sleep(interval)
        return False

    def _call(self, method, path, params=None):
        url = self.base + path.lstrip("/")
        if params:
            url += "?" + urllib.parse.urlencode(params)

        body = None
        code = 0
        last = None

        for attempt in range(self.max_retries + 1):
            req = urllib.request.Request(url, method=method)
            req.add_header("Authorization", f"Bearer {self.token}")
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    body = resp.read().decode("utf-8")
                    code = resp.status
                last = None
                break
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8")
                code = e.code
                last = None
                # 5xx = 服务端暂时不可用，值得重试；4xx 是业务错误，立刻返回
                if code >= 500 and attempt < self.max_retries:
                    self._backoff(attempt, f"HTTP {code}")
                    continue
                break
            except Exception as e:
                last = e
                if attempt < self.max_retries:
                    self._backoff(attempt, f"transport: {e}")
                    continue
                self.stats["errors"] += 1
                raise ArenaError(0, f"transport: {e}")

        if last is not None:
            self.stats["errors"] += 1
            raise ArenaError(0, f"transport: {last}")

        # 成功走到这里说明链路是通的
        if not self.online:
            self.online = True
            print(f"[net] 已重连（累计 {self.reconnects} 次）")

        self.stats["get" if method == "GET" else "post"] += 1

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.stats["errors"] += 1
            raise ArenaError(code, f"bad json: {body[:120]}")

        if not data.get("ok"):
            self.stats["errors"] += 1
            raise ArenaError(data.get("code", code), data.get("error", "unknown"))

        return data.get("data", {})

    def get(self, path, **params):
        return self._call("GET", path, params or None)

    def post(self, path, **params):
        return self._call("POST", path, params or None)


class Brain:
    """决策逻辑。四阶段状态机。"""

    def __init__(self, arena, verbose=False):
        self.a = arena
        self.verbose = verbose
        self.phase = "bootstrap"
        self.solar_built = 0
        self.turret_built = 0
        self.army_spawned = 0
        self.team_id = None
        self._last_builds = []
        self.placed_tiles = set()
        # 已下单的传送带格子。`_bfs_path` 允许穿过它们（见那里的注释），
        # 但 `placed_tiles` 里还混着矿机/工厂等实体，必须分开记。
        self.conveyor_tiles = set()
        self.occupied = set()
        self._why_last = {}
        self._sizes = {}
        self.pending_tiles = {}
        self._facnode_try = 0.0
        self.mine_unit = None
        self.mine_target = None
        self.mining_started = False
        self.drill_spot = None
        self.conveyor_done = 0
        self.conveyor_done_for = set()
        self.smelter_spot = None
        self.smelter_rebuild_at = 0.0
        self.power_node_placed = False
        self.power_node_spot = None
        self.factory_spot = None
        self.factory_rot = 0
        self.factory_front = None
        self.factory_done = False
        self.last_factory_progress = 0.0
        self.known_enemy_core = None      # (tileX, tileY) —— 一旦看见就记住
        self.own_core = None
        self.push_dist = 16.0             # 当前推进距离（格）
        self.last_push = 0.0
        self.last_extend = 0.0
        self.max_reach = 0.0              # 己方单位最远推进到多少格
        self.map_w = 350
        self.map_h = 200
        self.world_center = (175.0, 100.0)
        self._map_loaded = False

    def log(self, msg):
        if self.verbose:
            print(f"    {msg}", flush=True)

    # ------------------------------------------------------------ 主循环

    def tick(self):
        state = self.a.get("state")
        units = self.a.get("units")["units"]
        builds = self.a.get("buildings")["buildings"]

        # 地图尺寸只查一次
        if not self._map_loaded:
            self._map_loaded = True
            try:
                m = self.a.get("map", x=0, y=0, w=1, h=1)
                self.map_w = m.get("worldW", 350)
                self.map_h = m.get("worldH", 200)
                self.world_center = (self.map_w / 2.0, self.map_h / 2.0)
            except ArenaError:
                pass

        my_core = self._find_core(builds)
        if my_core is None:
            self.log("没有核心，等待…")
            return
        self.own_core = (my_core["x"], my_core["y"])

        # 记住敌方核心（从视野内的建筑）
        for b in builds:
            if b["block"].startswith("core-") and b["team"] != my_core["team"]:
                if self.known_enemy_core is None:
                    print(f"  [发现敌方核心] {b['block']} @ ({b['x']},{b['y']}) "
                          f"hp={b['health']:.0f}", flush=True)
                self.known_enemy_core = (b["x"], b["y"])

        self._update_progress(units, builds)

        self._last_builds = builds
        self._refresh_occupied(builds)
        if self.phase == "bootstrap":
            self._phase_bootstrap(units, builds)
        elif self.phase == "smelt":
            self._phase_smelt(builds, units)
        elif self.phase == "power":
            self._phase_power(builds)
        elif self.phase == "defense":
            self._phase_defense(builds)
        elif self.phase == "factory":
            self._phase_factory(builds)
        elif self.phase == "army":
            self._phase_army(units)
        else:
            self._phase_push(units)

    # ------------------------------------------------------------ 经济

    def _phase_bootstrap(self, units, builds):
        """启动资金：手动挖矿。

        建造和物料都不免费（rules.infiniteResources = false），核心的初始库存
        来自地图，只够放头几个建筑。想造矿机和工厂就得先有料，而料只能靠挖。

        走的是**原版路径**：/mine 只是把 unit.mineTile 设上，剩下的
        挖矿速率、硬度判定、以及「玩家控制的单位会把矿直接送进
        mineTransferRange 内的核心」全是 MinerComp 自己的逻辑。
        """
        need = self._core_items(builds)
        if need is None:
            return

        # 够了就转下一阶段。
        #
        # ⚠ 不能只看库存阈值。原实现要求铜>=350 且铅>=250，但 AI 一旦进入
        # smelt 铺传送带就会把这些料花掉（实测花到铜 335），库存跌回阈值以下
        # 之后就再也回不到 smelt —— 重启后从 bootstrap 开始，卡死在
        # 「等挖够 350 铜」上，`建筑=55` 冻结几万 tick 不动。
        #
        # 判据改成：库存够 **或** 已经有 2 台矿机。有矿机说明 bootstrap
        # 的实际目的（搞到启动产能）已经达成，就不该再用一个会被自己花掉的
        # 阈值把自己锁住。
        _drills_now = [b for b in builds if b["block"] == "mechanical-drill"]
        enough = need.get("copper", 0) >= RESERVE_COPPER and need.get("lead", 0) >= RESERVE_LEAD
        if enough or len(_drills_now) >= 2:
            self.phase = "smelt"
            self.log(f"=== 进入冶炼 (铜{need.get('copper')} 铅{need.get('lead')} "
                     f"矿机{len(_drills_now)} 库存够={enough}) ===")
            return

        # 先找一个能挖的矿，把单位挪过去
        if self.mine_target is None:
            self.mine_target = self._find_ore()
            if self.mine_target is None:
                self.log("附近找不到可挖的矿")
                return
            self.log(f"目标矿脉 {self.mine_target[2]} @ ({self.mine_target[0]},{self.mine_target[1]})")
            self._send_unit_to(self.mine_target[0], self.mine_target[1])

        if self.mine_unit is None and units:
            self.mine_unit = units[0]["id"]

        if self.mine_unit is None:
            return

        # 到位了才开始挖（原版要求单位在 mineRange=8 格内）
        if not self.mining_started:
            u = next((u for u in units if u["id"] == self.mine_unit), None)
            if u is None:
                return
            d = math.hypot(u["x"] / 8 - self.mine_target[0], u["y"] / 8 - self.mine_target[1])
            if d <= 7:
                try:
                    r = self.a.post("mine", unit=self.mine_unit,
                                    x=self.mine_target[0], y=self.mine_target[1])
                    self.mining_started = True
                    self.log(f"开始挖矿: {r.get('message', '')} ({r.get('drop', '')})")
                except ArenaError as e:
                    self.log(f"挖矿失败: {e.message}")
                    self.mine_target = None
            return

        # 挖到了就报一次进度
        if self.mine_unit:
            self.log(f"挖矿中… 核心 铜={need.get('copper')} 铅={need.get('lead')}")

    def _phase_smelt(self, builds, units):
        """硅冶炼链：铜矿机 + 煤矿机 -> 传送带 -> silicon-smelter -> 核心。

        为什么必须有这一步：核心现在只给 500 铜 + 500 铅，硅、石墨、钛、钍
        一律为 0。而几乎所有东西都要硅：
            solar-panel        铅10 硅8
            solar-panel-large  铅60 硅70 相织物15
            air-factory        铜60 铅70 硅60
            unloader           钛25 硅30
        没有硅，建造请求会正常排队（/place 返回 ok），但 hasAll(plan) 永远
        是 false，建筑一个都不会出现 —— 从外面看就像「AI 卡死 / 没视野」。

        能只靠铜铅起步的方块（实测 Blocks.java）：
            mechanical-drill  铜12     conveyor         铜1
            silicon-smelter   铜30 铅25  power-node     铜2 铅6
            duo               铜35     combustion-gen   铜25 铅15

        地图事实（veins，各核心 30 格内）：
            铜矿就在核心脚下（1~7 格），但多被核心 footprint 压住
            煤矿在 13~24 格外 —— 所以必须铺传送带
        """
        cx, cy = self.own_core

        # ---- 临时探针：看清每拍从哪一步退出 ----
        if getattr(self, "_smeltTrace", 0) < 25:
            self._smeltTrace = getattr(self, "_smeltTrace", 0) + 1
            _dr = [b for b in builds if b["block"] == "mechanical-drill"]
            _sm = [b for b in builds if b["block"] == "silicon-smelter"]
            self.log(f"[trace] drills={len(_dr)} smelters={len(_sm)} "
                     f"spot={self.smelter_spot} done={len(self.conveyor_done_for)} "
                     f"core={self._core_items(builds)}")

        # ---- 1. 两台矿机（沙 + 煤）----
        #
        # ⚠ 配方是 sand 2 + coal 1 -> silicon 1，**不是铜+煤**。
        # 早先按「铜+煤」写，硅永远为 0，整条经济链哑火。
        # 沙在地板层（darksand / sand-floor），veins 上满地图都是（实测核心
        # 附近 60x50 内 1057 格），煤只有 47 格 —— 所以先沙后煤。
        drills = [b for b in builds if b["block"] == "mechanical-drill"]
        if len(drills) + self._pending_count("mechanical-drill") < 2:
            have = {b["block"] for b in builds}
            _ = have
            core = next((b for b in builds if b["block"].startswith("core-")), None)
            avoid = self._footprint(core["x"], core["y"], core["block"]) if core else None
            want = "coal" if len(drills) >= 1 else "sand"
            # 只挑 mechanical-drill 挖得动的矿（tier=2 -> 硬度<=2）。
            #
            # ⚠ 不能再随便 fallback 到「任意矿」。实测找煤失败后退到了 ore-thorium，
            # 而钍硬度 4 挖不动，矿机永远空转、整条链哑火。
            # 找不到就等下一拍重试 —— 视野会随核心/单位扩张，之后就能看到更远的矿。
            ore = self._find_ore(want, avoid=avoid, max_hardness=2) \
                  or self._find_ore(want, max_hardness=2)
            if ore is None:
                self.log(f"附近没有挖得动的 {want}（mechanical-drill tier=2），等待视野扩张")
                return
            if self._try_place(ore[0], ore[1], "mechanical-drill", f"(矿机 {ore[2]})"):
                self.log(f"=== 矿机落位 ({ore[0]},{ore[1]}) 于 {ore[2]} ===")
            return

        # ---- 2. 冶炼厂贴着核心，硅直接 dump 进核心 ----
        if self._count(builds, "silicon-smelter") + self._pending_count("silicon-smelter") < 1:
            core = next((b for b in builds if b["block"].startswith("core-")), None)
            if core is None:
                return
            cs = self._block_size(core["block"])
            ss = self._block_size("silicon-smelter")
            d = (cs - 1) // 2 + 1 + (ss - 1) // 2
            for ox, oy in ((d, 0), (-d, 0), (0, d), (0, -d),
                           (d, d), (-d, -d), (d, -d), (-d, d)):
                if self._try_place(core["x"] + ox, core["y"] + oy, "silicon-smelter", "(硅冶炼厂)"):
                    self.smelter_spot = (core["x"] + ox, core["y"] + oy)
                    self.log(f"=== 冶炼厂落位 ({core['x']+ox},{core['y']+oy})，紧贴核心 ===")
                    return
            return

        # ---- 3. 两台矿机各铺一条传送带到冶炼厂 ----
        if self.smelter_spot and len(self.conveyor_done_for) < 2:
            for dr in drills:
                key = (dr["x"], dr["y"])
                if key in self.conveyor_done_for:
                    continue
                if self._conveyor_to(dr, self.smelter_spot, "silicon-smelter"):
                    self.conveyor_done_for.add(key)
                    self.log(f"传送带 ({key[0]},{key[1]}) -> 冶炼厂")
                return
            return

        # ---- 3b. 冶炼厂被单一物料塞死就拆了重建 ----
        #
        # silicon-smelter 的 itemCapacity = 10，每次合成吃 1 铜 + 1 煤。
        # 如果煤先到、铜后到，厂子会被 10 个煤塞满 —— 满了之后铜进不来，
        # 没有铜就永远不合成就永远不消耗煤，死锁。实测就是这么卡住的
        # （items={"coal":10}，铜全堵在最后一格传送带上）。
        sm = next((b for b in builds if b["block"] == "silicon-smelter"), None)
        if sm is not None:
            it = sm.get("items") or {}
            if it.get("coal", 0) >= 8 and it.get("copper", 0) == 0:
                if self.smelter_rebuild_at == 0.0:
                    self.smelter_rebuild_at = time.time()
                elif time.time() - self.smelter_rebuild_at > 12.0:
                    self.log("冶炼厂被煤塞死，拆掉重建")
                    try:
                        self.a.post("break", x=sm["x"], y=sm["y"])
                    except ArenaError as e:
                        self.log(f"拆除失败: {e.message}")
                    self.placed_tiles.discard((sm["x"], sm["y"]))
                    self.smelter_spot = None
                    self.conveyor_done_for.clear()
                    self.smelter_rebuild_at = 0.0
                    return
            else:
                self.smelter_rebuild_at = 0.0

        # ---- 4. 等核心攒到够用的硅 ----
        items = self._core_items(builds) or {}
        si = items.get("silicon", 0)
        if si >= RESERVE_SILICON:
            self.phase = "power"
            self.log(f"=== 硅 {si} 到位，进入供电 ===")
            return
        self.log(f"冶炼中… 核心硅={si} 铜={items.get('copper')} 铅={items.get('lead')}")

    def _conveyor_to(self, src, target_xy, target_block):
        """从 src 建筑铺传送带到 target 建筑，路径绕开已有建筑。

        ⚠ 不能用「先横后竖」的直线 L 形。实测核心 (59..63,102..106) 正好挡在
        煤矿机 (38,103) 和冶炼厂 (64,104) 之间，直线铺到 (58,103) 就断了 ——
        煤永远送不到，冶炼厂一颗料都没有，整条链哑火。

        改用 BFS 在空格上找最短路，再按路径方向给每段传送带设朝向。

        朝向约定（BuildingComp.nearby(int rotation)）：
            0=东(+x)  1=北(+y)  2=西(-x)  3=南(-y)
        """
        ts = self._block_size(target_block)
        toff = -((ts - 1) // 2)
        tfp = {(target_xy[0] + toff + dx, target_xy[1] + toff + dy)
               for dx in range(ts) for dy in range(ts)}

        sx, sy = int(src["x"]), int(src["y"])
        ss = self._block_size(src["block"])
        soff = -((ss - 1) // 2)
        sfp = {(sx + soff + dx, sy + soff + dy) for dx in range(ss) for dy in range(ss)}

        # 目标建筑四周一圈 = 合法终点
        goals = set()
        for (ax, ay) in tfp:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                p = (ax + dx, ay + dy)
                if p not in tfp:
                    goals.add(p)

        # 起点必须紧邻源建筑的**锚点格**，不是 footprint 的任意边。
        #
        # ⚠ 实测：矿机 (65,104) 是 2×2，锚点就是 (65,104)。传送带放在
        # footprint 下沿的 (65,106) 时，矿机一直满仓（items=10）推不出去；
        # 换成紧邻锚点的 (67,104) 之后立刻开始出货（10 -> 4）。
        # 原因是 Conveyor.acceptItem 用 Edges.getFacingEdge(source.tile, tile)
        # 算朝向，而 source.tile 是锚点格 —— 锚点不相邻时这个朝向是错的。
        starts = set()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            p = (sx + dx, sy + dy)
            if p not in sfp:
                starts.add(p)

        path = self._bfs_path(starts, goals, tfp | sfp)
        if not path:
            # ⚠ 失败必须出声。原实现静默返回 False，而调用方无论成败都 return，
            # 于是死循环没有任何日志痕迹（实测卡了上万 tick 才发现）。
            self._why("conveyor", (sx, sy), f"no path {sorted(starts)[:2]} -> {sorted(goals)[:2]}")
            return False

        placed = 0
        for i, (x, y) in enumerate(path):
            if i == len(path) - 1:
                # 最后一段朝向目标中心，方向错了物品不流动
                dx, dy = target_xy[0] - x, target_xy[1] - y
                if abs(dx) >= abs(dy):
                    rot = 0 if dx > 0 else 2
                else:
                    rot = 1 if dy > 0 else 3
            else:
                nx, ny = path[i + 1]
                if nx > x:   rot = 0
                elif nx < x: rot = 2
                elif ny > y: rot = 1
                else:        rot = 3
            if self._try_place(x, y, "conveyor", "(传送带)", rot=rot):
                placed += 1
        # 路径有效即算成功 —— 即使整条路都已经是传送带（`_try_place` 会因
        # 重复下单而返回 False）。否则调用方会永远重试。
        return placed > 0 or len(path) > 0

    def _bfs_path(self, starts, goals, blocked):
        """在空格上 BFS 找最短路；blocked 是必须绕开的格子。

        ⚠ **已铺的传送带必须可通行**，不能当墙。

        原实现把 `placed_tiles` 里所有格子都判成障碍，于是每铺一段就把
        BFS 的可走空间削掉一块 —— 铺得越多越找不到路。实测表现是
        AI 卡在 smelt 阶段空转：`_conveyor_to` 返回 False，而调用它的
        循环无论成败都 `return`，于是每拍静默重试、永不记录、建筑数冻结
        （51 条传送带全是一次次失败尝试的残留）。

        现在：`conveyor_tiles` 里的格子**允许穿过**（只是不作为起点/终点），
        因为它们本来就是要承载物品流的。
        """
        import collections

        w, h = self.map_w, self.map_h
        passable = getattr(self, "conveyor_tiles", set())

        def ok(p, as_endpoint):
            x, y = p
            if x < 1 or y < 1 or x >= w - 1 or y >= h - 1:
                return False
            if p in blocked or p in self.occupied:
                return False
            if p in self.placed_tiles and not (p in passable):
                return False
            # 起点/终点不能落在已有传送带上（那样「连接」就没有意义了）
            if as_endpoint and p in passable:
                return False
            return True

        starts = {p for p in starts if ok(p, True)}
        goals = {p for p in goals if ok(p, True)}
        if not starts or not goals:
            return None

        prev = {}
        seen = set(starts)
        dq = collections.deque(starts)
        hit = None
        while dq:
            cur = dq.popleft()
            if cur in goals:
                hit = cur
                break
            x, y = cur
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                p = (nx, ny)
                if p in seen or not ok(p, False):
                    continue
                seen.add(p)
                prev[p] = cur
                dq.append(p)

        if hit is None:
            return None
        path = [hit]
        while path[-1] in prev:
            path.append(prev[path[-1]])
        path.reverse()
        return path

    def _phase_power(self, builds):
        """电力：大型太阳能板 + power-node。

        ⚠ 不能用 solar-panel。原版数值（Blocks.java:2621）：
            solar-panel        powerProduction = 0.12f   尺寸 1
            solar-panel-large  powerProduction = 1.6f    尺寸 3
        而 air-factory 要 consumePower(1.2f) —— 一块小太阳能板只有 0.12，
        **要 10 块才喂得饱一座工厂**。实测铺了 8~10 块板，工厂 efficiency
        也只有 0.4，一架 flare 要 40 秒。

        大型太阳能板一块 1.6 出力、无消耗，成本是 铅60 硅70 相织物15 ——
        相织物属于高阶材料，正好是「用更高级的材料优化产线」。

        电力网络仍然需要 power-node 连线：太阳能板只发电，不连线就是孤岛。
        """
        cx, cy = self.own_core

        if self._count(builds, "solar-panel-large") + self._pending_count("solar-panel-large") < WANT_SOLAR_LARGE and self._count(builds, "solar-panel") == 0:
            # 3×3 要一块空地，多给几个半径
            for radius in (6, 7, 8, 9, 10, 11, 12):
                for x, y in self._ring_spots(cx, cy, radius, 12):
                    if self._try_place(x, y, "solar-panel-large", "(大型供电)"):
                        return
            # 大板要相织物，核心没有时退回小板（只要铅10 硅8）
            for radius in (6, 7, 8, 9, 10, 11, 12):
                for x, y in self._ring_spots(cx, cy, radius, 16):
                    if self._try_place(x, y, "solar-panel", "(供电)"):
                        return
            return

        if not self._count(builds, "power-node") and not self._pending_count("power-node"):
            for radius in (5, 6, 7, 8, 9, 10):
                for x, y in self._ring_spots(cx, cy, radius, 12):
                    if self._try_place(x, y, "power-node", "(电力节点)"):
                        self.power_node_spot = (int(x), int(y))
                        self.phase = "defense"
                        self.log("=== 供电就绪，进入防御 ===")
                        return
            return

        self.phase = "defense"

    def _phase_defense(self, builds):
        """必要的防御。

        目标里明确要求「建造必要的防御」。早期版本这里一座炮塔都没有，
        敌人只要推过来核心就直接没了 —— 实测 crux 就是这么被推平的。

        duo      1×1  铜35            地面点防御，便宜、射速快
        scatter  2×2  铜85 铅45       对空散射，防 flare/mono 这类飞行单位
        """
        cx, cy = self.own_core

        if self._count(builds, "duo") + self._pending_count("duo") < WANT_DUO:
            for radius in (7, 8, 9, 10, 11, 12, 13):
                for x, y in self._ring_spots(cx, cy, radius, 16):
                    if self._try_place(x, y, "duo", "(对地炮塔)"):
                        return
            return

        if self._count(builds, "scatter") + self._pending_count("scatter") < WANT_SCATTER:
            for radius in (9, 10, 11, 12, 13, 14):
                for x, y in self._ring_spots(cx, cy, radius, 16):
                    if self._try_place(x, y, "scatter", "(对空炮塔)"):
                        return
            return

        self.phase = "factory"
        self.log("=== 防御就绪，进入建厂 ===")

    def _phase_factory(self, builds):
        """矿机 + 工厂。

        原版里 Drill.updateTile() 会 dump() 到相邻的接收方块，而
        UnitFactoryBuild.acceptItem 正好接受当前产线需要的物品 ——
        所以矿机贴着工厂就能直接供料，不一定要传送带。
        两者放不下相邻时才铺传送带。
        """
        cx, cy = self.own_core

        # ---- 1) 工厂：贴着核心放 ----
        #
        # 位置很关键：卸载器要**同时**挨着核心和工厂，所以工厂必须紧贴核心的
        # 5×5 边界。放到十几格开外就得铺传送带，多一层失败点。
        if not self.factory_done and self._count(builds, "air-factory") + self._pending_count("air-factory") < 1:
            core = next((b for b in builds if b["block"].startswith("core-")), None)
            if core is not None:
                cs = self._block_size(core["block"])
                fs = self._block_size("air-factory")
                # 中心到中心的距离：让工厂的边正好贴住核心的边
                d = (cs - 1) // 2 + 1 + (fs - 1) // 2

                # 朝向必须满足**两个**条件，缺一工厂就永久卡死：
                #
                #   1. 背对核心 —— 正前方不能是实心的核心
                #   2. 正前方**完全没有建筑** —— 太阳能板、节点、传送带都不行
                #
                # 原因在 PayloadBlock.moveOutPayload()：
                #     canDump = front == null || !front.tile.solid()
                #     canMove = front.block.outputsPayload || acceptsPayload
                # 只要 front 是个实心且不收 payload 的方块，两个分支都不成立，
                # 成品单位就永远待在工厂里，shouldConsume() 里 payload == null
                # 那一项永久为 false，efficiency 归 0。实测就是产线爬到 100%
                # 之后再不动、单位一个都不出来。
                #
                # rotation: 0=东(+x) 1=北(+y) 2=西(-x) 3=南(-y)
                # front() 的坐标是 中心 + 方向 * size
                for ox, oy, rot in ((d, 0, 0), (-d, 0, 2), (0, d, 1), (0, -d, 3),
                                    (d, d, 0), (-d, -d, 2), (d, -d, 0), (-d, d, 2)):
                    fx, fy = core["x"] + ox, core["y"] + oy
                    if rot == 0:
                        front = (fx + fs, fy)
                    elif rot == 2:
                        front = (fx - fs, fy)
                    elif rot == 1:
                        front = (fx, fy + fs)
                    else:
                        front = (fx, fy - fs)

                    if front in self.occupied:
                        self._why("air-factory", (fx, fy), f"front {front} blocked by building")
                        continue
                    if self._try_place(fx, fy, "air-factory", f"(工厂贴核心 rot={rot})", rot=rot):
                        self.factory_spot = (fx, fy)
                        self.factory_rot = rot
                        self.factory_front = front
                        self.factory_done = True
                        self.log(f"=== 工厂落位 ({fx},{fy}) 朝向 {rot}，前方 {front} 是空地 ===")
                        return
            return

        fac = next((b for b in builds if b["block"] == "air-factory"), None)
        if fac is None:
            return

        # ---- 2) 卸载器：同时挨着核心和工厂 ----
        #
        # 这是「物料不免费」之后最关键的一环。原版 Unloader 的 allowCoreUnload = true，
        # 而且它的比较器里写着 `//priority to core and core containers always` ——
        # 只要它同时挨着核心和工厂，就会把核心里的物品搬进工厂。
        # 工厂的 acceptItem 只接受当前产线需要的物品，所以只有硅会流动。
        if self._count(builds, "unloader") + self._pending_count("unloader") < 1:
            core = next((b for b in builds if b["block"].startswith("core-")), None)
            if core is None:
                return
            spot = self._unloader_spot(core, fac)
            if spot is None:
                self.log("找不到同时挨着核心和工厂的位置放卸载器")
                return
            if self._try_place(spot[0], spot[1], "unloader", "(卸载器)"):
                self.log(f"=== 卸载器落位 ({spot[0]},{spot[1]})，核心 -> 工厂 ===")
            return

        # ---- 3) 工厂供电 ----
        #
        # 不只看 powered 标志，还要看 efficiency。实测 powered=True 但 eff=0.1 ——
        # 电力网络接上了，可板子只有一块，air-factory 吃 1.2 电根本不够，
        # 一架 flare 要 150 秒而不是 15 秒。
        #
        # 但门槛不能设高：太阳能板受日照影响，而 air-factory 吃 1.2 电、
        # 一块板满日照才给 1.0，eff 根本到不了 0.8。设 0.8 的结果是
        # 「补电 -> 还是不够 -> 再补电」，卡在建厂阶段出不来（实测单位已经
        # 造了 10 架，阶段还停在 factory）。
        # 只把「严重缺电」当成要继续补的信号，够用就往前走。
        live_fac = self._live_factory(fac)
        eff = live_fac.get("efficiency", 0) if live_fac else 0
        if not self._factory_powered(builds, fac):
            self._power_the_factory(fac)
            return
        if eff < 0.5 and self._pending_count("solar-panel-large") == 0:
            self._power_the_factory(fac)
            return

        # ---- 4) 选定产线 ----
        # /factory 里的 plan 为空说明还没配
        try:
            fdata = self.a.get("factory")
            facs = fdata.get("factories") or []
        except ArenaError:
            facs = []
        live = next((f for f in facs if f.get("x") == fac["x"] and f.get("y") == fac["y"]), None)
        if live is not None and not live.get("plan"):
            try:
                self.a.post("config", x=fac["x"], y=fac["y"], value=WANT_UNIT)
                self.log(f"工厂产线 -> {WANT_UNIT}")
            except ArenaError as e:
                self.log(f"配置工厂失败: {e.message}")
            return

        self.phase = "army"
        self.log("=== 产能就绪，进入造兵期 ===")

    def _unloader_spot(self, core, fac):
        """找一个同时挨着核心和工厂的格子。

        1×1 的卸载器要满足：与核心 footprint 相邻、与工厂 footprint 相邻
        （都是切比雪夫距离 1，含对角）。

        ⚠ 必须用 _footprint()，不能用角坐标手写 covers()。多块建筑是中心坐标，
        手写 bx <= x < bx+s 会整体偏 (size-1)/2 格 —— 实测这样算出来的「相邻」
        是错的，卸载器被放到了够不着工厂的地方，核心的硅永远送不过去。
        """
        core_tiles = self._footprint(core["x"], core["y"], core["block"])
        fac_tiles = self._footprint(fac["x"], fac["y"], fac["block"])

        def adjacent(tiles, x, y):
            return any(abs(tx - x) <= 1 and abs(ty - y) <= 1 for tx, ty in tiles)

        # 候选 = 核心 footprint 向外扩一圈的所有格子
        cands = set()
        for tx, ty in core_tiles:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    cands.add((tx + dx, ty + dy))
        cands -= core_tiles
        cands -= fac_tiles

        for x, y in sorted(cands):
            if adjacent(core_tiles, x, y) and adjacent(fac_tiles, x, y):
                if self._footprint_free(x, y, "unloader"):
                    return (x, y)
        return None

    def _live_factory(self, fac):
        """从 /factory 拿这座工厂的实时状态（权威数据）。"""
        try:
            fdata = self.a.get("factory")
            for f in fdata.get("factories") or []:
                if f.get("x") == fac["x"] and f.get("y") == fac["y"]:
                    return f
        except ArenaError:
            pass
        return None

    def _factory_powered(self, builds, fac):
        """工厂有没有电。

        ⚠ 必须读 /factory 的 powered 标志，不能靠「附近 6 格内有没有电力节点」猜。
        节点可能是个**孤岛** —— 实测 (53,104) 的节点离主电网的太阳能板 13 格，
        超出 laserRange=6，自己一点电都没有，但按距离判断会误判成已通电，
        于是 AI 推进到造兵期，工厂永远不产出。
        """
        live = self._live_factory(fac)
        if live is not None:
            return bool(live.get("powered"))
        return False

    def _power_the_factory(self, fac):
        fx, fy = int(fac["x"]), int(fac["y"])
        # 先节点，后太阳能板
        if not self._facnode_try:
            for ox, oy in ((4, 0), (-4, 0), (0, 4), (0, -4), (4, 4), (-4, -4), (4, -4), (-4, 4),
                           (5, 0), (-5, 0), (0, 5), (0, -5)):
                if (fx + ox, fy + oy) == self.factory_front:
                    continue
                if self._try_place(fx + ox, fy + oy, "power-node", "(工厂电力节点)"):
                    self._facnode_try = time.time()
                    self.log(f"工厂旁电力节点 -> ({fx+ox},{fy+oy})")
                    return
            self._facnode_try = time.time()   # 本轮没找到，过一会儿再试
            return

        # 板子要够。air-factory 吃 1.2 电，一块太阳能板满日照才给 1.0，
        # 所以一块远远不够 —— 实测只有 eff=0.1，一架 flare 要 150 秒。
        # 先把节点周围铺满再说。
        fac_panels = sum(1 for b in self._last_builds
                         if b["block"] == "solar-panel-large"
                         and math.hypot(b["x"] - fx, b["y"] - fy) <= 6)
        if fac_panels >= WANT_FACTORY_SOLAR:
            return
        # 节点还没放就先放节点
        for r in (2, 3, 4):
            for ox, oy in ((r, 0), (-r, 0), (0, r), (0, -r),
                           (r, r), (-r, -r), (r, -r), (-r, r)):
                # 别把工厂正前方的空地占了 —— 那里是成品单位唯一的出口
                if self.factory_front is not None and (fx + ox, fy + oy) in self._footprint(
                        self.factory_front[0], self.factory_front[1], "air-factory"):
                    continue
                if self._try_place(fx + ox, fy + oy, "solar-panel-large", "(工厂供电)"):
                    return

    def _lay_conveyor_to_factory(self):
        """从矿机铺一条 L 形传送带到工厂。

        朝向按走向算：Mindustry 的传送带 rotation 0=东 1=南 2=西 3=北
        （Point2 的 dir 顺序），铺错方向物品不会流动。
        """
        dx, dy = self.drill_spot
        fx, fy = self.factory_spot
        if dx == fx and dy == fy:
            return

        placed = 0
        # 先横后竖
        sx = 1 if fx >= dx else -1
        for x in range(dx, fx + sx, sx):
            rot = 0 if sx > 0 else 2
            if self._try_place(x, dy, "conveyor", "(传送带)", rot=rot):
                placed += 1
        sy = 1 if fy >= dy else -1
        for y in range(dy, fy + sy, sy):
            rot = 1 if sy > 0 else 3
            if self._try_place(fx, y, "conveyor", "(传送带)", rot=rot):
                placed += 1
        self.log(f"传送带铺了 {placed} 段")

    def _why(self, block, key, reason):
        """记录一次被挡下的建造请求（限流：同类原因 15 秒报一次）。"""
        tag = f"{block}:{reason.split()[0]}"
        now = time.time()
        if now - self._why_last.get(tag, 0) < 15.0:
            return
        self._why_last[tag] = now
        self.log(f"建造 {block} @ ({key[0]},{key[1]}) 跳过: {reason}")
    def _block_size(self, name):
        """方块尺寸，从 /content 缓存一次。"""
        if not self._sizes:
            try:
                c = self.a.get("content")
                for b in c.get("blocks", []):
                    self._sizes[b["name"]] = int(b.get("size", 1))
            except ArenaError:
                return 1
        return self._sizes.get(name, 1)

    def _footprint(self, x, y, block):
        """方块占的格子集合。

        ⚠ Mindustry v8 的多块建筑用**中心坐标**：
            Block.java:775  sizeOffset = -((size - 1) / 2)
        /place 收的是中心，/buildings 报的也是中心，footprint 是
        [x + sizeOffset, x + sizeOffset + size)。

        按左上角算会**每个多块建筑都偏 (size-1)/2 格** —— 5×5 的核心偏 2 格，
        于是「贴着核心」放工厂全部压在核心上，validPlace 永远不通过，
        /place 却照样返回 ok。实测卡死就是这么来的。
        """
        s = self._block_size(block)
        off = -((s - 1) // 2)
        x0, y0 = int(x) + off, int(y) + off
        return {(x0 + dx, y0 + dy) for dx in range(s) for dy in range(s)}

    def _refresh_occupied(self, builds):
        """把已有建筑覆盖的格子记下来，并清理已完成的 pending。"""
        occ = set()
        # ⚠ 场上**已存在的**传送带也要收进 conveyor_tiles。
        #
        # 原先只在 `_try_place` 成功时登记，于是只能穿过「本进程自己刚铺的」带子。
        # 上一局留下的传送带对 BFS 仍然是墙 —— 实测重启后 `_conveyor_to` 报
        # `no path [(60,108),(61,107)] -> [(63,104),(63,105)]`：冶炼厂东侧
        # 唯一可用的邻格全被旧带子占着，新带子永远铺不出去。
        for b in builds:
            if b["block"] == "conveyor":
                self.conveyor_tiles.add((b["x"], b["y"]))
        for b in builds:
            occ |= self._footprint(b["x"], b["y"], b["block"])
        self.occupied = occ

        # 建筑出现了 -> 这格不再 pending；超时 25 秒也放掉（多半是建不成）
        now = time.time()
        for k, (blk, ts) in list(self.pending_tiles.items()):
            if k in occ or now - ts > 25.0:
                del self.pending_tiles[k]

    def _pending_count(self, block):
        return sum(1 for blk, _ in self.pending_tiles.values() if blk == block)

    def _footprint_free(self, x, y, block):
        return not (self._footprint(x, y, block) & self.occupied)
    def _core_items(self, builds):
        for b in builds:
            if b["block"].startswith("core-"):
                return b.get("items") or {}
        return None

    # 各矿的硬度（从 /content 的 items 查得，Blocks/Items 定义）
    ORE_HARDNESS = {
        "ore-copper": 1, "ore-lead": 1, "ore-coal": 2,
        "ore-titanium": 3, "ore-thorium": 4, "ore-scrap": 0,
        "ore-sand": 0, "ore-beryllium": 3, "ore-tungsten": 5,
    }

    def _ore_item(self, ore_name):
        """矿脉名 -> 硬度。"""
        return self.ORE_HARDNESS.get(ore_name)
    def _find_ore(self, want=None, avoid=None, max_hardness=None):
        """在核心附近扫 /map，找一块**真的能放矿机**的矿脉。

        ⚠ 光看 overlay 是不够的。实测 veins 上核心脚下的 (60,105)/(61,105)
        就是 ore-coal，但 `block=core-nucleus` —— 矿脉被 5×5 的核心压住了。
        选到这种格子，/place 会正常返回 ok（计划排队成功），但 validPlace
        永远不通过，矿机永远建不出来；而 placed_tiles 已经记下那格，
        于是 AI 每拍静默重试，卡死在「建厂」阶段不动。

        所以要求：
          1. 该格是矿脉
          2. 该格没有建筑压着（block == air）
          3. 矿机 2×2 的 footprint 全是空的（否则 validPlace 也过不了）
          4. 没被自己下过单
        """
        cx, cy = self.own_core
        x0, y0 = int(cx) - 28, int(cy) - 28
        w = h = 56
        try:
            m = self.a.get("map", x=x0, y=y0, w=w, h=h)
        except ArenaError:
            return None

        # 建索引，方便查 footprint
        tiles = {}
        for t in m.get("tiles", []):
            tiles[(t["x"], t["y"])] = t

        def is_free(x, y):
            t = tiles.get((x, y))
            if t is None:
                return False
            if (t.get("block") or "air") != "air":
                return False
            return (x, y) not in self.placed_tiles

        best = None
        best_d = 1e9
        for (x, y), t in tiles.items():
            # ⚠ 用 /map 的 drop 字段，**不要**看 overlay。
            #
            # tile.drop() 的解析顺序是 block.itemDrop -> overlay.itemDrop -> floor.itemDrop。
            # 沙在地板层（darksand / sand-floor 的 itemDrop = sand），overlay 是空的 ——
            # 只筛 ore-* 前缀会把整片沙地全部漏掉，而沙正是硅冶炼厂的第一原料。
            # /map 的 drop 走的就是 tile.drop()，和 Drill.canMine 同一个来源。
            drop = t.get("drop") or ""
            if not drop:
                continue
            if want is not None and drop != want:
                continue                      # 只要指定矿种时，跳过其它矿
            # 硬度过滤。mechanical-drill 的 tier = 2，只能挖硬度 <= 2 的矿：
            #   sand 0 / copper 1 / lead 1 / coal 2  可挖
            #   titanium 3 / thorium 4               挖不动
            # 实测没过滤时 fallback 选到了 ore-thorium，矿机一颗料都不产。
            if max_hardness is not None:
                h = t.get("dropHardness")
                if h is None or h < 0 or h > max_hardness:
                    continue
            if (t.get("block") or "air") != "air":
                continue                      # 被核心/建筑压住的矿，放不下矿机
            if (x, y) in self.placed_tiles:
                continue
            # 矿机是 2×2：footprint 必须全空
            if not all(is_free(x + dx, y + dy) for dx in (0, 1) for dy in (0, 1)):
                continue
            # avoid: footprint 不得与给定格子相邻。
            #
            # ⚠ 这一步是冶炼链能不能成的关键。矿机贴着核心时，
            # Building.dump() 会从相邻方块里挑接收方 —— 核心和传送带都接受，
            # 结果料全进了核心、冶炼厂 items={} 空的，一颗硅都产不出来。
            # 让矿机离核心一格，dump 就只能走传送带。
            if avoid:
                touches = False
                for dx in (0, 1):
                    for dy in (0, 1):
                        for ax in (-1, 0, 1):
                            for ay in (-1, 0, 1):
                                if (x + dx + ax, y + dy + ay) in avoid:
                                    touches = True
                if touches:
                    continue

            d = math.hypot(x - cx, y - cy)
            if d < best_d:
                best_d = d
                best = (x, y, drop)

        if best is None:
            self.log(f"附近没有可放矿机的 {want or '任意'} 矿"
                     f"（硬度上限 {max_hardness}；可能被建筑压住或 footprint 不空）")
        return best

    def _send_unit_to(self, x, y):
        try:
            units = self.a.get("units")["units"]
            if not units:
                return
            self.mine_unit = units[0]["id"]
            self.a.post("command", action="move", units=str(self.mine_unit), x=int(x), y=int(y))
        except ArenaError as e:
            self.log(f"移动单位失败: {e.message}")

    # ------------------------------------------------------------ 工具

    def _find_core(self, builds):
        for b in builds:
            if b["block"].startswith("core-"):
                return b
        return None

    def _update_enemy_intel(self):
        """从 /intel 拿已确认的敌方核心数据（含历史快照）。"""
        try:
            intel = self.a.get("intel")
        except ArenaError:
            return
        for c in intel.get("cores", []):
            if c.get("state") == "confirmed":
                self.log(f"情报确认 {c['team']}：{len(c.get('snapshots', []))} 份快照")

    def _count(self, builds, name):
        return sum(1 for b in builds if b["block"] == name)

    def _try_place(self, x, y, block, note="", rot=None):
        """下单建造。视野外的失败是预期的（推进阶段会用到）。

        rot 只在传送带这类有朝向的方块上需要：方向错了物品不流动。

        ⚠ 必须记住「已经下过单的格子」。/place 是**排队**建造 —— POST 返回 ok
        时建筑还没出现在 /buildings 里。如果只看 _count() 判断还差几个，
        循环会每次都从候选表的第一个点重来、每次都成功、于是永远在同一格
        反复下单，而计数永远不涨。实测就是这样卡在 1 块太阳能板上不动的。
        """
        key = (int(x), int(y))
        if key in self.placed_tiles:
            self._why(block, key, "already-queued")
            return False
        # 这一格已经在等建造完成 -> 别再重复下单。
        #
        # ⚠ 这里按**格子**记，不能按方块类型限流。早期版本用了「同种方块 20 秒
        # 内只下一次单」，结果把 6 块太阳能板串行化成 120 秒，AI 永远走不出供电阶段。
        # 真正要防的是「同一格重复下单」，而不是「同一种方块放太快」。
        if key in self.pending_tiles:
            self._why(block, key, "pending build")
            return False
        # 目标 footprint 必须没有被已有建筑占住。
        #
        # ⚠ 这是最容易忽略的一条：3×3 的工厂压在自己刚放的太阳能板上时，
        # /place 照样返回 ok（计划排队成功），但 validPlace 永远不通过，
        # 建筑永远不出现。实测就是这样反复「落位」却建不出来的。
        if not self._footprint_free(key[0], key[1], block):
            self._why(block, key, "footprint occupied")
            return False
        try:
            kw = dict(x=int(x), y=int(y), block=block)
            if rot is not None:
                kw["rot"] = int(rot)
            self.a.post("place", **kw)
            self.placed_tiles.add(key)
            if block == "conveyor":
                self.conveyor_tiles.add(key)
            # 记下这次下单的时间。/place 是排队的，POST 返回 ok 时建筑还没出现，
            # 光靠 _count(builds, block) 判断会让 AI 在等待期间重复下单 ——
            # 实测放过两座 air-factory。这里给它一个冷静期。
            self.pending_tiles[key] = (block, time.time())
            self.log(f"建造 {block} @ ({int(x)},{int(y)}) {note}")
            return True
        except ArenaError as e:
            self.log(f"建造 {block} @ ({int(x)},{int(y)}) 失败: {e.message}")
            return False

    def _ring_spots(self, cx, cy, radius, count):
        """在核心周围生成一圈候选建造点。"""
        spots = []
        for i in range(count):
            ang = 2 * math.pi * i / max(1, count)
            spots.append((cx + math.cos(ang) * radius, cy + math.sin(ang) * radius))
        return spots

    # ------------------------------------------------------------ 阶段

    def _phase_build(self, builds):
        """造太阳能板供电，接上电力节点，再散布炮塔。

        电力网络需要三样东西，缺一不可：
            太阳能板    发电
            power-node  连线（太阳能板只发电，不连线就是孤岛）
            用电器      工厂 / 炮塔

        实测缺 power-node 时工厂一直是 powered=false / efficiency=0、产线停在 0%，
        看起来像「工厂不工作」，其实是没接上电。
        """
        cx, cy = self.own_core

        if self.solar_built < WANT_SOLAR:
            for x, y in self._ring_spots(cx, cy, 6, WANT_SOLAR * 4):
                if self._try_place(x, y, "solar-panel", "(供电)"):
                    self.solar_built += 1
                    if self.solar_built >= WANT_SOLAR:
                        break

        # 电力节点：把太阳能板连成网
        if self.solar_built >= WANT_SOLAR and not self.power_node_placed:
            for x, y in self._ring_spots(cx, cy, 6, 8):
                if self._try_place(x, y, "power-node", "(电力节点)"):
                    self.power_node_placed = True
                    self.power_node_spot = (int(x), int(y))
                    break

        if self.power_node_placed and self.turret_built < WANT_TURRET:
            for x, y in self._ring_spots(cx, cy, 11, WANT_TURRET * 2):
                if self._try_place(x, y, "duo", "(炮塔)"):
                    self.turret_built += 1
                    if self.turret_built >= WANT_TURRET:
                        break

        if self.turret_built >= WANT_TURRET:
            self.phase = "army"
            self.log("=== 进入造兵期 ===")

    def _phase_army(self, units):
        """靠工厂造兵。

        单位不能凭空召唤 —— /spawn 已经被服务端禁用。要出兵必须：

            1. 建一座工厂（air-factory 3×3，需要一块空地）
            2. 给它供电（工厂 hasPower，没电 efficiency=0，产线会停）
            3. 用 /config 选定产线（按单位名，服务端会解析成 UnitType）
            4. 等 plan.time 走完，单位从工厂弹出来

        工厂信息从 /content 里读（每个方块带 plans 字段），不硬编码 ——
        换地图或换版本时不会失效。
        """
        # 先找一座己方工厂
        fac = self._find_factory()

        if fac is None:
            self._build_factory()
            return

        # 工厂存在但没选产线 -> 配置
        if not fac.get("plan"):
            self._configure_factory(fac)
            return

        # 有产线但在等 —— 顺便记进度，方便观察是不是卡在没电
        if fac.get("progress") is not None:
            self.last_factory_progress = fac["progress"]
            if fac.get("efficiency", 0) <= 0.01:
                self.log(f"工厂没在产（efficiency=0，多半是缺电）plan={fac.get('plan')}")

        # 兵够了就转推进
        if len(units) >= WANT_ARMY:
            self.phase = "push"
            self.log(f"=== 进入推进期（部队 {len(units)}）===")

    def _find_factory(self):
        """查 /factory，返回第一座己方工厂的状态。"""
        try:
            data = self.a.get("factory")
        except ArenaError:
            return None
        facs = data.get("factories") or []
        return facs[0] if facs else None

    def _build_factory(self):
        """在核心周围找一块空地放工厂，再补太阳能板供电。"""
        cx, cy = self.own_core

        # 工厂必须落在电力节点的覆盖范围内，否则 powered 永远是 false。
        # power-node 的 laserRange 是 6 格，节点在半径 6 的环上，
        # 所以工厂放在半径 8~10 就能被覆盖到。
        for radius in (9, 8, 10, 11, 12):
            for x, y in self._ring_spots(cx, cy, radius, 12):
                if self._try_place(x, y, "air-factory", "(工厂)"):
                    self.factory_spot = (int(x), int(y))
                    self.log(f"=== 工厂落位 ({int(x)},{int(y)})，等供电 ===")
                    return

        self.log("找不到放工厂的空地")

    def _configure_factory(self, fac):
        """给工厂选产线。优先 flare（15 秒一个，最便宜）。"""
        try:
            self.a.post("config", x=fac["x"], y=fac["y"], value=WANT_UNIT)
            self.log(f"工厂产线 -> {WANT_UNIT}")
        except ArenaError as e:
            self.log(f"配置工厂失败: {e.message}")

    def _commandable(self, units):
        """挑出**可被指挥**的单位。

        ⚠ 原版语义（UnitComp.java:513）：
            public boolean isCommandable(){ return controller instanceof CommandAI; }
            public boolean isPlayer(){ return controller instanceof Player; }
        玩家控制的单位**不可被指挥**，NetServer.commandUnits 遇到它会静默跳过。

        更麻烦的是 Commander.command 会对每个单位做可见性检查，任何一个失败
        就整体返回错误 —— 所以把坐在核心上的 gamma 混进指令里，会让整条
        指令被驳回，工厂产的 flare 一个都动不了。
        """
        return [u for u in units if not u["type"].startswith("gamma") and not u["type"].startswith("alpha")]

    def _phase_push(self, units):
        """向敌方核心推进，最终摧毁它。

        视野半径只有 21.75 格，而 veins 上两核相距 228 格 —— 一次指挥打不到
        对方老家。所以推进必须是渐进的：

            把目标点定在「己方核心 + 方向 × 推进距离」，
            部队走过去之后视野跟着扩展，更远的目标点才变成可见。

        目标点每 5 秒往外推 10 格。超出视野的尝试会被服务端拒绝，
        这是对等约束在正常工作，不是错误 —— 部队到了自然就成功。
        """
        army = self._commandable(units)
        if not army:
            self.log("没有可指挥的部队，回退到造兵")
            self.phase = "army"
            return

        cx, cy = self.own_core

        # 先看看视野里有没有敌方核心 —— 部队推进时视野跟着扩，
        # 一旦看见就该锁定它，之后所有指令直指那里。
        self._scan_for_enemy_core()

        # 方向：一旦知道敌方核心就直指它，否则朝地图中心
        if self.known_enemy_core:
            ex, ey = self.known_enemy_core
            dx, dy = ex - cx, ey - cy
            max_push = math.hypot(dx, dy)
        else:
            dx, dy = self.world_center[0] - cx, self.world_center[1] - cy
            # ⚠ 上限不能是「到地图中心的距离」。实测这样部队会正好停在地图
            # 正中央不动（推进 114 格 -> (175,100) 然后一直重复），因为敌核
            # 在 289 还在 114 格之外。不知道敌核时就一路推下去。
            max_push = math.hypot(self.map_w, self.map_h)

        dist = math.hypot(dx, dy) or 1
        ux, uy = dx / dist, dy / dist

        now = time.time()

        # 每 5 秒把目标点往外推一截
        if now - self.last_extend >= 5.0:
            self.last_extend = now
            self.push_dist = min(self.push_dist + 10.0, max_push)

        if now - self.last_push < 1.5:
            return
        self.last_push = now

        ids = ",".join(str(u["id"]) for u in army[:12])

        # 已经看得见敌核 -> 直接打核心，这是结束对局的那一步
        if self.known_enemy_core and self._core_in_reach(army):
            try:
                self.a.post("command", action="attack",
                            target="building",
                            x=self.known_enemy_core[0], y=self.known_enemy_core[1],
                            units=ids)
                self.log(f"=== 围攻敌方核心 ({self.known_enemy_core[0]},{self.known_enemy_core[1]}) ===")
                return
            except ArenaError as e:
                self.log(f"攻击核心失败: {e.message}")

        tx = cx + ux * self.push_dist
        ty = cy + uy * self.push_dist

        # 地图边界内
        tx = max(2, min(self.map_w - 3, tx))
        ty = max(2, min(self.map_h - 3, ty))

        try:
            self.a.post("command", action="move", units=ids,
                        x=int(tx), y=int(ty))
            self.log(f"推进 {int(self.push_dist)} 格 -> ({int(tx)},{int(ty)})  部队 {len(army)}")
        except ArenaError as e:
            if "visible" in e.message:
                # 目标还在视野外 —— 部队继续走，视野会跟上
                self.log(f"目标 {int(self.push_dist)} 格尚不可见，等待部队")
            else:
                self.log(f"推进失败: {e.message}")

    def _scan_for_enemy_core(self):
        """从己方视野里找敌方核心。

        /buildings 是按视野过滤的，所以「列表里出现了一个不属于我的核心」
        就等于「我的部队真的看见了它」—— 这是对等约束下的合法情报，
        不是偷看。部队推进时视野跟着扩，迟早会撞见。
        """
        if self.known_enemy_core:
            return
        try:
            data = self.a.get("buildings")
        except ArenaError:
            return
        # /buildings 的响应自带 team 字段，就是当前视角的队伍 id
        my_team = data.get("team")
        for b in data.get("buildings") or []:
            if not b["block"].startswith("core-"):
                continue
            if b.get("team") == my_team:
                continue
            self.known_enemy_core = (b["x"], b["y"])
            self.log(f"=== 发现敌方核心 {b['block']} @ ({b['x']},{b['y']}) ===")
            return

    def _core_in_reach(self, army):
        """部队里有没有单位已经够得着敌核（用己方视野判断）。"""
        if not self.known_enemy_core:
            return False
        ex, ey = self.known_enemy_core
        try:
            bl = self.a.get("buildings")["buildings"]
        except ArenaError:
            return False
        for b in bl:
            if b["block"].startswith("core-") and abs(b["x"] - ex) <= 2 and abs(b["y"] - ey) <= 2:
                return True
        return False

    def _update_progress(self, units, builds):
        """记录推进进度：己方最远的单位离核心多远。"""
        if not self.own_core or not units:
            return
        cx, cy = self.own_core
        far = max(math.hypot(u["x"] / 8 - cx, u["y"] / 8 - cy) for u in units)
        self.max_reach = max(self.max_reach, far)

    # ------------------------------------------------------------ 报告

    def report(self):
        try:
            st = self.a.get("state")
            units = self.a.get("units")["units"]
            builds = self.a.get("buildings")["buildings"]
            enemy = f"({self.known_enemy_core[0]},{self.known_enemy_core[1]})" \
                    if self.known_enemy_core else "未发现"
            print(f"  阶段={self.phase}  tick={st['tick']}  "
                  f"单位={len(units)}  建筑={len(builds)}  "
                  f"太阳能={self._count(builds, 'solar-panel')}  "
                  f"炮塔={self._count(builds, 'duo')}  "
                  f"节点={self.power_node_spot or '未建'}  工厂={self.factory_spot or '未建'}  "
                  f"产线进度={self.last_factory_progress:.0%}  "
                  f"推进={self.push_dist:.0f}格/实际{self.max_reach:.0f}格  "
                  f"敌核={enemy}")
        except ArenaError as e:
            print(f"  报告失败: {e.message}")


def main():
    ap = argparse.ArgumentParser(description="AI 竞技场示例客户端")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7199)
    ap.add_argument("--agent", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--seconds", type=float, default=60.0, help="运行时长")
    ap.add_argument("--interval", type=float, default=0.5, help="决策周期（秒）")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--wait-server", type=float, default=120.0,
                    help="服务端不可用时最长等待秒数（0 = 不等待，立刻失败）")
    args = ap.parse_args()

    arena = Arena(args.host, args.port, args.agent, args.token, args.verbose)
    brain = Brain(arena, args.verbose)

    print(f"[{args.agent}] 启动，运行 {args.seconds:.0f} 秒")

    # 启动时等服务端就绪 —— 不再因为「服务器还没起来」直接退出
    if not arena.wait_online(timeout=args.wait_server):
        print(f"[{args.agent}] 等待服务端 {args.wait_server:.0f}s 超时")
        return 1

    try:
        ping = arena.get("state")
        print(f"[{args.agent}] 连接成功  tick={ping['tick']}  "
              f"队伍={ping.get('view', '?')}")
    except ArenaError as e:
        print(f"[{args.agent}] 连接失败: {e}")
        return 1

    deadline = time.time() + args.seconds
    cycles = 0
    last_report = 0.0
    offline_since = None

    while time.time() < deadline:
        try:
            brain.tick()
            cycles += 1
            if offline_since is not None:
                print(f"[{args.agent}] 已恢复，中断 {time.time() - offline_since:.1f}s")
                offline_since = None
        except ArenaError as e:
            # 传输层失败（服务端重启/抖动）不再直接吞掉：
            # 标记离线、等服务端回来、然后继续跑，而不是让整局 AI 报废
            if e.code == 0:
                if offline_since is None:
                    offline_since = time.time()
                    print(f"[{args.agent}] 掉线: {e}；等待服务端恢复…", file=sys.stderr)
                arena.wait_online(timeout=args.wait_server, interval=0.5)
            else:
                print(f"[{args.agent}] 决策异常: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[{args.agent}] 未预期异常: {type(e).__name__}: {e}", file=sys.stderr)

        now = time.time()
        if now - last_report >= 10.0:
            last_report = now
            brain.report()

        time.sleep(args.interval)

    print(f"[{args.agent}] 结束  决策轮次={cycles}  "
          f"GET={arena.stats['get']}  POST={arena.stats['post']}  "
          f"错误={arena.stats['errors']}  重试={arena.stats['retries']}  "
          f"重连={arena.reconnects}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
