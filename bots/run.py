#!/usr/bin/env python3
"""bot 运行时：感知 → 决策 → 执行 → 反馈，一局从头跑到尾不停。

    python -m bots.run --agent beta                      # 用默认策略
    python -m bots.run --agent beta --strategy demo
    python -m bots.run --agent beta --decide-hz 10       # 每秒决策 10 次
    python -m bots.run --agent beta --dry-run            # 只决策不发命令
    python -m bots.run --agent beta --seconds 60         # 跑一分钟后自己停

### 为什么是这个形状

YG 要的三层是「LLM 写 bot / bot 毫秒级执行 / 引擎跑规则」。落到代码：

| 层 | 在哪 | 节奏 |
|---|---|---|
| LLM | 编辑 `bots/strategy/*.py` | 秒级到分钟级 |
| **bot（本文件）** | 常驻进程 | 决策 5 Hz，感知 20 Hz |
| 引擎 | 服务端 | 60 tick/s |

**LLM 不在决策回路里** —— 它只改文件，本进程热加载后立刻生效，`mem` 不丢。
这是与「LLM 每步都问一次」的本质区别：那个是秒级反应，这个是毫秒级。

### 为什么决策 5 Hz 而不是 60 Hz

决策频率和感知频率是两件事：
- 感知（WS 推送）20 Hz —— 世界变了能马上知道；
- 决策 5 Hz —— 每 200 ms 重新规划一次，对人手操作已经是上限量级。

把决策提到 60 Hz 只会产生大量重复意图（每拍都「要建同一格」），
而引擎那边 `/place` 是排队的，重复下单只会把队列塞满。
**真正需要高频的是「反应」不是「规划」** —— 反应靠 `mem` 里记的状态迁移，
不是靠在 `decide` 里空转。
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "bots"

from bots import actions
from bots.transport import ArenaLink, WsError
from bots.world import World


class Poller(threading.Thread):
    """`/rates` 与 `/stalls` 的**兜底**轮询。

    2026-10-20 起这两个数据有 WS 通道（`rates` / `stalls`），正常情况不再需要
    轮询 —— 默认 `--poll-hz 0` 关闭。留着是因为：推送断线重连的那几秒里，
    轮询能把产率与告警接上，而策略不该在断线窗口看到空数据。

    单独一条线程的理由仍然成立：`/stalls` 一次请求在服务端要等一个 tick
    （实测 P50 13.64 ms），放在决策循环里会吃掉一大截决策预算。
    """

    def __init__(self, world, token, agent, host, port, interval=1.0, window=10):
        super().__init__(name="bot-poll", daemon=True)
        self.world = world
        self.token = token
        self.agent = agent
        self.host = host
        self.port = port
        self.interval = interval
        self.window = window
        self.stop_evt = threading.Event()
        self.errors = 0
        self.ok = 0

    def _get(self, path):
        url = f"http://{self.host}:{self.port}/v1/{self.agent}/{path}"
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))

    def run(self):
        while not self.stop_evt.is_set():
            try:
                r = self._get(f"rates?window={self.window}")
                if r.get("ok"):
                    self.world.set_rates(r.get("data"))
                s = self._get("stalls")
                if s.get("ok"):
                    self.world.set_stalls(s.get("data"))
                self.ok += 1
            except Exception:
                self.errors += 1
            self.stop_evt.wait(self.interval)

    def stop(self):
        self.stop_evt.set()


class Loader:
    """策略热加载：改文件就生效，实例重建，`mem` 保留。"""

    def __init__(self, name):
        self.name = name
        self.module = None
        self.obj = None
        self.generation = 0
        self._mtime = None
        self.load()

    def _stamps(self):
        pkg = Path(__file__).resolve().parent / "strategy"
        return tuple(sorted(
            (p.name, p.stat().st_mtime_ns)
            for p in pkg.glob("*.py")))

    def load(self):
        modname = f"bots.strategy.{self.name}"
        if self.module is None:
            self.module = importlib.import_module(modname)
        else:
            self.module = importlib.reload(self.module)
        cls = getattr(self.module, "Strategy", None)
        if cls is None:
            raise WsError(f"{modname} 里没有 Strategy 类")
        self.obj = cls()
        self.generation += 1
        self._mtime = self._stamps()
        return self.obj

    def poll(self):
        """文件变了就重载，返回 True。"""
        cur = self._stamps()
        if cur == self._mtime:
            return False
        self._mtime = cur
        try:
            self.load()
            return True
        except Exception:
            trace = traceback.format_exc(limit=4)
            print(f"[bot] 策略重载失败（继续用上一版）:\n{trace}")
            return False


class Recorder:
    """轨迹：每拍一行 JSONL。给 LLM 复盘用，也给 `drive/agent-trail.py` 看。"""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = self.path.open("a", encoding="utf-8")

    def write(self, rec):
        self.fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.fh.flush()

    def close(self):
        try:
            self.fh.close()
        except Exception:
            pass


def http_get(host, port, agent, token, path, timeout=20):
    url = f"http://{host}:{port}/v1/{agent}/{path}"
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def load_map_around(world, host, port, agent, token, cx, cy, size=64):
    """拉核心周围一片地形，最多 4096 格（`/map` 的单次上限）。

    地形是静态的，拉一次就够；但**必须有** —— 没有地块信息时选址只能靠
    `/place` 失败来试，那正是 `skill/SKILL.md` 禁止的用法（实测踩到过一次 409）。
    """
    x0 = max(0, cx - size // 2)
    y0 = max(0, cy - size // 2)
    w = max(1, min(size, world.world_w - x0))
    h = max(1, min(size, world.world_h - y0))
    r = http_get(host, port, agent, token, f"map?x={x0}&y={y0}&w={w}&h={h}")
    data = r.get("data") or {}
    tiles = data.get("tiles") or []
    world.set_tiles(tiles)
    return len(tiles)


def main() -> int:
    ap = argparse.ArgumentParser(description="ai-arena bot 运行时")
    ap.add_argument("--agent", default="beta")
    ap.add_argument("--strategy", default="demo")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--ws-port", type=int, default=7200)
    ap.add_argument("--http-port", type=int, default=7199)
    ap.add_argument("--decide-hz", type=float, default=5.0)
    ap.add_argument("--sense-hz", type=int, default=20)
    ap.add_argument("--poll-hz", type=float, default=0.0,
                    help="轮询 /rates 与 /stalls 的兜底频率；0 = 关（它们现在有 WS 通道）")
    ap.add_argument("--max-cmds", type=int, default=20,
                    help="每秒最多发多少条命令（服务端每条命令新建一个线程）")
    ap.add_argument("--seconds", type=float, default=0.0, help="0 = 一直跑")
    ap.add_argument("--dry-run", action="store_true", help="只决策，不发命令")
    ap.add_argument("--trace", default=None,
                    help="轨迹文件；默认 _work/bot-trace-<agent>.jsonl")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    world = World()
    loader = Loader(args.strategy)
    print(f"[bot] 策略 {args.strategy} 已加载（第 {loader.generation} 代）")

    link = ArenaLink(args.agent, args.host, args.ws_port, args.http_port,
                     hz=args.sense_hz)
    link.on_frame = world.on_frame
    link.on_hello = lambda info: print(
        f"[bot] 连上：agent={info.get('agent')} team={info.get('team')} "
        f"api={info.get('apiPort')} ws={info.get('wsPort')}")
    link.on_error = lambda m: print(f"[bot] {m}")

    trace_path = args.trace or (
        Path(__file__).resolve().parent.parent / "_work" / f"bot-trace-{args.agent}.jsonl")
    rec = Recorder(trace_path)

    poller = Poller(world, link.token, args.agent, args.host, args.http_port,
                    interval=1.0 / max(0.1, args.poll_hz))
    if args.poll_hz > 0:
        poller.start()
    link.start()

    # 等世界就绪（采样，不是干等）
    while not world.ready():
        if link.last_frame_at == 0 and link.reconnects > 0 and link.frames == 0:
            pass
        time.sleep(0.1)

    print(f"[bot] 世界就绪 tick={world.tick} team={world.team} "
          f"{world.world_w}x{world.world_h}")

    mem = {}                      # 跨决策、跨热加载都保留
    sent: dict[int, dict] = {}    # 命令 id → 动作，等 ack 回来对账
    send_times: list[float] = []  # 最近一秒的发令时间戳，做限流
    started = time.monotonic()
    deadline = started + args.seconds if args.seconds > 0 else None
    period = 1.0 / max(0.1, args.decide_hz)
    next_tick_at = time.monotonic()
    nb_decisions = nb_actions = nb_errors = nb_reloads = 0
    last_note = None

    try:
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                break

            # ⓪ 地形缓存：核心一出现就拉一次（拉一次够，地形是静态的）
            if not world.tiles_loaded:
                cores = world.cores()
                if cores:
                    try:
                        n = load_map_around(world, args.host, args.http_port,
                                            args.agent, link.token,
                                            cores[0]["x"], cores[0]["y"])
                        print(f"[bot] 地形已缓存 {n} 格（核心周围 64×64）")
                    except Exception as e:
                        print(f"[bot] 地形拉取失败（下拍再试）: {e}")

            # ① 热加载
            if loader.poll():
                nb_reloads += 1
                print(f"[bot] 策略已热加载（第 {loader.generation} 代），mem 保留 {len(mem)} 项")

            # ② 决策
            acts = []
            try:
                acts = loader.obj.decide(world, mem) or []
            except Exception:
                nb_errors += 1
                err = traceback.format_exc(limit=3)
                print(f"[bot] 决策异常:\n{err}")
                rec.write({"t": time.time(), "tick": world.tick,
                           "error": err.splitlines()[-1]})
                acts = []
            nb_decisions += 1

            # ③ 执行
            now = time.monotonic()
            send_times = [t for t in send_times if now - t < 1.0]
            for a in acts:
                a = actions.expand_units(a, world)
                if a is None:
                    continue
                endpoint, params = actions.encode(a)
                if endpoint is None:
                    print(f"[bot] 动作无法识别: {params}")
                    continue
                if args.dry_run:
                    print(f"[bot][dry] {endpoint} {params}")
                    continue
                if len(send_times) >= args.max_cmds:
                    rec.write({"t": time.time(), "tick": world.tick,
                               "dropped": a, "why": "rate-limit"})
                    continue
                try:
                    cid = link.send_cmd(endpoint, params)
                    sent[cid] = {"endpoint": endpoint, "params": params,
                                 "tick": world.tick, "t": time.time()}
                    send_times.append(now)
                    nb_actions += 1
                except Exception as e:
                    print(f"[bot] 发令失败: {e}")

            # ④ 收 ack（不阻塞）
            for ack in link.drain_acks():
                cid = ack.get("id")
                orig = sent.pop(cid, None)
                body = ack.get("body")
                ok = bool(isinstance(body, dict) and body.get("ok"))
                rec.write({"t": time.time(), "tick": world.tick,
                           "ack": {"id": cid, "status": ack.get("status"),
                                   "ok": ok,
                                   "action": orig,
                                   "body": body}})
                if not ok and not args.quiet:
                    print(f"[bot] 命令失败 id={cid} {ack.get('status')} "
                          f"{(orig or {}).get('endpoint')} → "
                          f"{json.dumps(body, ensure_ascii=False)[:200]}")

            # ⑤ 决策轨迹（只在 note 变化时写，避免刷屏）
            note = mem.get("note")
            if note != last_note or acts:
                rec.write({"t": time.time(), "tick": world.tick,
                           "decisions": nb_decisions, "note": note,
                           "acts": acts, "gen": loader.generation,
                           "mem": {k: v for k, v in mem.items()
                                   if k not in ("note",)}})
                last_note = note
                if note and not acts and not args.quiet:
                    print(f"[bot] note: {note}")

            # ⑥ 节流（采样间隔，不是判据）
            next_tick_at += period
            sleep_for = next_tick_at - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                next_tick_at = time.monotonic()

    except KeyboardInterrupt:
        print("\n[bot] Ctrl-C")
    finally:
        try:
            loader.obj.teardown(world)
        except Exception:
            pass
        poller.stop()
        link.stop()
        rec.write({"t": time.time(), "tick": world.tick, "stop": True,
                   "decisions": nb_decisions, "actions": nb_actions,
                   "errors": nb_errors, "reloads": nb_reloads,
                   "frames": link.frames, "reconnects": link.reconnects,
                   "poll_ok": poller.ok, "poll_err": poller.errors})
        rec.close()
        print(f"[bot] 结束：决策 {nb_decisions} 次、动作 {nb_actions} 条、"
              f"热加载 {nb_reloads} 次、异常 {nb_errors} 次")
        print(f"[bot] 收帧 {link.frames}、重连 {link.reconnects} 次、"
              f"轮询 {poller.ok}/{poller.ok + poller.errors}")
        print(f"[bot] 轨迹 → {trace_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
