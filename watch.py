#!/usr/bin/env python3
"""
AI 竞技场 · 观战服务器

用裁判 token 抓取全图数据，渲染成一个实时网页。
在浏览器打开 http://127.0.0.1:8080 就能看这局对抗。

为什么不走 Mindustry 客户端：
    headless 服务器在这个项目里只开了 HTTP 端口（7199），游戏端口
    （6567）没有起 —— 因为 setup 直接把 state 推进到 playing，
    跳过了 NetServer 的监听流程。所以客户端连不进去。
    观战走 HTTP 反而更稳，也能看到 AI 眼里的东西。

数据来源（全部用 referee token + view=all）：
    /state       tick / 队伍
    /units       所有单位
    /buildings   所有建筑（含库存）
    /map         地形（分块抓一次后缓存）

用法：
    python watch.py --token <referee_token>
    python watch.py --token <tok> --http-port 8080
"""

import argparse
import json
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# /map 区域模式的上限是 4096 格（64x64）
MAP_CHUNK = 64


class Referee:
    """裁判视角的 HTTP 客户端。"""

    def __init__(self, host, port, agent, token):
        self.base = f"http://{host}:{port}/v1/{agent}/"
        self.token = token

    def get(self, path, **params):
        url = self.base + path.lstrip("/")
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, method="GET")
        req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            raise RuntimeError(f"HTTP {e.code}: {body[:160]}")
        if not data.get("ok"):
            raise RuntimeError(f"[{data.get('code')}] {data.get('error')}")
        return data.get("data", {})


class World:
    """缓存地形，定期刷新实体。"""

    def __init__(self, ref):
        self.ref = ref
        self.lock = threading.Lock()
        self.terrain = {}          # "x,y" -> floor name
        self.blocks = {}           # "x,y" -> 静态方块名（墙/树/矿，不含 air）
        self.width = 0
        self.height = 0
        self.terrain_ready = False
        self.state = {}
        self.units = []
        self.buildings = []
        self.last_error = ""
        self.last_update = 0.0
        self.frames = 0

    def load_terrain(self):
        """分块抓全图地形。只做一次。

        每格有两层信息，都要存：
            floor  地板（shale / darksand / moss / core-zone …）—— 决定底色
            block  静态方块（dune-wall / shale-wall / spore-pine / 矿石 …）
                   —— 这是「墙面」，玩家建筑也在这层，但那种由实时数据画

        只存非 air 的 block，能把传输和内存压下来（veins 上 64% 是墙）。
        """
        probe = self.ref.get("map", x=0, y=0, w=1, h=1, view="all")
        w = probe.get("worldW", 350)
        h = probe.get("worldH", 200)

        floors = {}
        blocks = {}
        chunks_x = math.ceil(w / MAP_CHUNK)
        chunks_y = math.ceil(h / MAP_CHUNK)

        for cy in range(chunks_y):
            for cx in range(chunks_x):
                x0 = cx * MAP_CHUNK
                y0 = cy * MAP_CHUNK
                cw = min(MAP_CHUNK, w - x0)
                ch = min(MAP_CHUNK, h - y0)
                try:
                    m = self.ref.get("map", x=x0, y=y0, w=cw, h=ch, view="all")
                except RuntimeError as e:
                    self.last_error = f"地形块 ({x0},{y0}) 失败: {e}"
                    continue
                for t in m.get("tiles", []):
                    key = f"{t['x']},{t['y']}"
                    floors[key] = t.get("floor", "?")
                    b = t.get("block", "air")
                    if b and b != "air":
                        blocks[key] = b

        with self.lock:
            self.terrain = floors
            self.blocks = blocks
            self.width = w
            self.height = h
            self.terrain_ready = True
        print(f"[watch] 地形已缓存 {w}x{h} = {len(floors)} 格，"
              f"其中 {len(blocks)} 格有方块（墙/树/矿），"
              f"{chunks_x}x{chunks_y} 块")

    def refresh(self):
        """抓一次实体状态。"""
        try:
            st = self.ref.get("state", view="all")
            un = self.ref.get("units", view="all")
            bl = self.ref.get("buildings", view="all")
        except RuntimeError as e:
            self.last_error = str(e)
            return

        with self.lock:
            self.state = st
            self.units = un.get("units", [])
            self.buildings = bl.get("buildings", [])
            self.last_error = ""
            self.last_update = time.time()
            self.frames += 1

    def snapshot(self):
        with self.lock:
            return {
                "width": self.width,
                "height": self.height,
                "terrainReady": self.terrain_ready,
                "terrain": self.terrain if self.terrain_ready else {},
                "blocks": self.blocks if self.terrain_ready else {},
                "blocksCount": len(self.blocks) if self.terrain_ready else 0,
                "state": self.state,
                "units": self.units,
                "buildings": self.buildings,
                "error": self.last_error,
                "age": round(time.time() - self.last_update, 2) if self.last_update else None,
                "frames": self.frames,
            }


PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>AI 竞技场 · 观战</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: #0b0e13; color: #c8d0dc;
    font: 13px/1.5 ui-monospace, "Cascadia Mono", Consolas, monospace;
    display: flex; flex-direction: column; height: 100vh;
  }
  header {
    padding: 10px 16px; border-bottom: 1px solid #1e2633;
    display: flex; align-items: center; gap: 20px; flex-wrap: wrap;
  }
  h1 { font-size: 15px; margin: 0; font-weight: 600; letter-spacing: .5px; }
  .stat { color: #6b7a8f; }
  .stat b { color: #e8eef7; font-weight: 600; }
  .ok { color: #4ade80; }
  .bad { color: #f87171; }
  main { flex: 1; display: flex; overflow: hidden; }
  #view { flex: 1; overflow: auto; padding: 12px; background: #070a0e; }
  canvas { display: block; image-rendering: pixelated; }
  aside {
    width: 300px; border-left: 1px solid #1e2633; overflow-y: auto; padding: 12px;
  }
  .team { margin-bottom: 14px; padding: 8px 10px; border-radius: 6px; background: #11161e; }
  .team h3 { margin: 0 0 6px; font-size: 13px; }
  .row { display: flex; justify-content: space-between; color: #6b7a8f; }
  .row span:last-child { color: #c8d0dc; }
  .bar { height: 6px; border-radius: 3px; background: #1e2633; margin-top: 5px; overflow: hidden; }
  .bar > i { display: block; height: 100%; }
  #err { padding: 6px 16px; color: #f87171; font-size: 12px; min-height: 22px; }
</style>
</head>
<body>
<header>
  <h1>AI 竞技场 · 观战</h1>
  <div class="stat">tick <b id="tick">-</b></div>
  <div class="stat">单位 <b id="uc">-</b></div>
  <div class="stat">建筑 <b id="bc">-</b></div>
  <div class="stat">帧 <b id="fc">-</b></div>
  <div class="stat" id="conn">连接中…</div>
  <label class="stat"><input type="checkbox" id="terrain" checked> 地形</label>
  <label class="stat"><input type="checkbox" id="fog" checked> 视野外淡化</label>
</header>
<div id="err"></div>
<main>
  <div id="view"><canvas id="cv" width="10" height="10"></canvas></div>
  <aside id="side"></aside>
</main>
<script>
const CV = document.getElementById('cv');
const CTX = CV.getContext('2d');
const SCALE = 4;
const T = 8;                     // Vars.tilesize
let world = null;
let terrainCache = {};

const TEAM_COLORS = {
  0: '#666', 1: '#4ade80', 2: '#f87171',
  100: '#4ade80', 101: '#f87171', 102: '#60a5fa', 103: '#fbbf24',
};
function teamColor(t) { return TEAM_COLORS[t] || '#a78bfa'; }

const FLOOR_COLORS = {
  'shale': '#2b2f36', 'stone': '#33373e', 'sand': '#4a4433',
  'dirt': '#3a3129', 'grass': '#243020', 'moss': '#22301f',
  'spore-moss': '#2a3a26',
  'ice': '#33414d', 'snow': '#3d444c', 'salt': '#3a3a44',
  'basalt': '#26282e', 'mud': '#2e2a24', 'deep-water': '#12202e',
  'water': '#16293b', 'tainted-water': '#1d2a22', 'deep-tainted-water': '#152018',
  'metal-floor': '#3a3f47', 'metal-floor-damaged': '#33373d',
  'core-zone': '#4a3f6b', 'darksand': '#3d3728', 'darksand-tainted-water': '#1a2318',
  'ferric-stone': '#3a3230', 'crater-stone': '#302c2a', 'red-stone': '#3d2a28',
  'arctic-stone': '#31373f', 'magmatic-rock': '#3a2620', 'yellow-stone': '#403a2a',
  'crystalline-stone': '#2e3a3a', 'space': '#0a0a10',
  'dacite': '#33302c', 'rhyolite': '#37332e', 'rhyolite-crater': '#3b342c',
  'carbon-stone': '#2a2a2e', 'beryllic-stone': '#2f3a3a',
  'yellow-stone-plates': '#3f3a2c', 'red-stone-plates': '#3c2b28',
  'dark-panel-1': '#282c33', 'dark-panel-2': '#2c3037',
  'basalt-forest': '#2a3028', 'snow-forest': '#333b42',
};
function floorColor(f) { return FLOOR_COLORS[f] || '#2a2e35'; }

// 静态方块（墙面 / 树 / 矿石）。这是「墙面」层，与地板分开画。
const BLOCK_COLORS = {
  'dune-wall': '#6b5f42', 'shale-wall': '#4a4e55', 'sand-wall': '#6a5c3c',
  'dirt-wall': '#4c4034', 'stone-wall': '#565b63', 'ice-wall': '#5c6f7d',
  'snow-wall': '#5a636c', 'salt-wall': '#5c5c68', 'basalt-wall': '#45474e',
  'ferric-stone-wall': '#54483f', 'crater-stone-wall': '#4a423f',
  'red-stone-wall': '#5a3c38', 'arctic-stone-wall': '#4b525c',
  'magmatic-rock-wall': '#553a30', 'yellow-stone-wall': '#5c5236',
  'crystalline-stone-wall': '#46585a', 'carbon-wall': '#3f3f46',
  'beryllic-stone-wall': '#4a5c5c', 'dacite-wall': '#4c4842',
  'rhyolite-wall': '#524c44', 'rhyolite-crater-wall': '#564c40',
  'spore-wall': '#4a3a4a', 'spore-pine': '#2f4a2c', 'spore-moss-wall': '#3a4a34',
  'boulder': '#5a5f66', 'snow-boulder': '#6a737c', 'shale-boulder': '#5a5f66',
  'sand-boulder': '#6b5f42', 'dacite-boulder': '#585450',
  'ore-copper': '#c07a3a', 'ore-lead': '#7a6a8a', 'ore-coal': '#2a2a2e',
  'ore-titanium': '#5a8fa8', 'ore-thorium': '#a86ac0', 'ore-scrap': '#8a8a8a',
  'ore-beryllium': '#4a9a8a', 'ore-tungsten': '#6a6a8a',
  'ore-crystal-thorium': '#c07ad0', 'ore-wall-thorium': '#7a5a8a',
  'wall-copper': '#a86a34', 'wall-lead': '#6a5a7a',
};
function blockColor(b) {
  if (BLOCK_COLORS[b]) return BLOCK_COLORS[b];
  if (b.startsWith('ore-')) return '#9a7a4a';
  if (b.endsWith('-wall')) return '#4a4e55';
  if (b.includes('boulder')) return '#5a5f66';
  return '#494e56';
}

async function fetchJSON(path) {
  const r = await fetch(path, { cache: 'no-store' });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

function draw(w) {
  if (!w.width) return;
  if (CV.width !== w.width * SCALE) {
    CV.width = w.width * SCALE;
    CV.height = w.height * SCALE;
    terrainCache = {};
  }

  // 地形：先铺地板，再叠静态方块（墙 / 树 / 矿石）。
  // 这两层必须分开画 —— 之前只画了 floor，整张图看起来像一块平地，
  // 完全看不出 veins 其实有 64% 的格子被墙占据。
  if (document.getElementById('terrain').checked && w.terrainReady) {
    if (!terrainCache.img || terrainCache.w !== w.width || terrainCache.blocks !== w.blocksCount) {
      const off = document.createElement('canvas');
      off.width = w.width * SCALE; off.height = w.height * SCALE;
      const octx = off.getContext('2d');

      // 第一层：地板
      for (const [key, floor] of Object.entries(w.terrain)) {
        const [x, y] = key.split(',').map(Number);
        octx.fillStyle = floorColor(floor);
        octx.fillRect(x * SCALE, y * SCALE, SCALE, SCALE);
      }

      // 第二层：静态方块
      for (const [key, block] of Object.entries(w.blocks || {})) {
        const [x, y] = key.split(',').map(Number);
        octx.fillStyle = blockColor(block);
        octx.fillRect(x * SCALE, y * SCALE, SCALE, SCALE);
      }

      terrainCache = { img: off, w: w.width, blocks: w.blocksCount };
    }
    CTX.drawImage(terrainCache.img, 0, 0);
  } else {
    CTX.fillStyle = '#12161c';
    CTX.fillRect(0, 0, CV.width, CV.height);
  }

  const dim = document.getElementById('fog').checked;

  // 建筑
  for (const b of w.buildings) {
    if (b.block === 'air') continue;
    const x = b.x * SCALE, y = b.y * SCALE;
    CTX.globalAlpha = dim && b.visible === false ? 0.25 : 1;
    CTX.fillStyle = teamColor(b.team);
    if (b.block.startsWith('core-')) {
      // 核心画大一点，加白边
      const sz = (b.block === 'core-nucleus' ? 5 : 3) * SCALE;
      CTX.fillRect(x - (sz - SCALE) / 2, y - (sz - SCALE) / 2, sz, sz);
      CTX.strokeStyle = '#fff'; CTX.lineWidth = 1.5;
      CTX.strokeRect(x - (sz - SCALE) / 2, y - (sz - SCALE) / 2, sz, sz);
      // 血量条
      const hp = b.health / (b.maxHealth || 1);
      CTX.fillStyle = '#000'; CTX.fillRect(x - (sz-SCALE)/2, y - (sz-SCALE)/2 - 4, sz, 3);
      CTX.fillStyle = hp > 0.5 ? '#4ade80' : (hp > 0.2 ? '#fbbf24' : '#f87171');
      CTX.fillRect(x - (sz-SCALE)/2, y - (sz-SCALE)/2 - 4, sz * hp, 3);
    } else {
      CTX.fillRect(x, y, SCALE, SCALE);
    }
  }
  CTX.globalAlpha = 1;

  // 单位（画成小三角，飞行单位加圈）
  for (const u of w.units) {
    const x = u.x / T * SCALE, y = u.y / T * SCALE;
    CTX.globalAlpha = dim && u.visible === false ? 0.25 : 1;
    CTX.fillStyle = teamColor(u.team);
    CTX.beginPath();
    CTX.arc(x, y, SCALE * 0.9, 0, Math.PI * 2);
    CTX.fill();
    if (u.flying) {
      CTX.strokeStyle = '#fff'; CTX.lineWidth = 1;
      CTX.beginPath(); CTX.arc(x, y, SCALE * 1.6, 0, Math.PI * 2); CTX.stroke();
    }
    CTX.globalAlpha = 1;
  }
}

function renderSide(w) {
  const byTeam = {};
  for (const u of w.units) (byTeam[u.team] ??= { units: 0, builds: 0, core: null, coreHp: 0, coreMax: 1 });
  for (const b of w.buildings) {
    const t = (byTeam[b.team] ??= { units: 0, builds: 0, core: null, coreHp: 0, coreMax: 1 });
    t.builds++;
    if (b.block.startsWith('core-')) {
      t.core = b.block; t.coreHp = b.health; t.coreMax = b.maxHealth || 1;
      t.items = b.items || {};
    }
  }
  for (const u of w.units) byTeam[u.team].units++;

  const names = {};
  for (const t of (w.state.teams || [])) names[t.id] = t.name;

  let html = '';
  const ids = Object.keys(byTeam).map(Number).sort((a, b) => a - b);
  for (const id of ids) {
    const t = byTeam[id];
    const hp = t.coreMax ? t.coreHp / t.coreMax : 0;
    const col = teamColor(id);
    html += `<div class="team" style="border-left:3px solid ${col}">
      <h3 style="color:${col}">${names[id] || ('team#' + id)} <span style="color:#6b7a8f;font-weight:400">(id ${id})</span></h3>
      <div class="row"><span>单位</span><span>${t.units}</span></div>
      <div class="row"><span>建筑</span><span>${t.builds}</span></div>`;
    if (t.core) {
      html += `<div class="row"><span>${t.core}</span><span>${Math.round(t.coreHp)} / ${Math.round(t.coreMax)}</span></div>
        <div class="bar"><i style="width:${(hp * 100).toFixed(1)}%;background:${hp > .5 ? '#4ade80' : hp > .2 ? '#fbbf24' : '#f87171'}"></i></div>`;
      const items = Object.entries(t.items || {}).filter(([, v]) => v > 0);
      if (items.length) {
        html += `<div style="margin-top:6px;color:#6b7a8f;font-size:11px">`
             + items.map(([k, v]) => `${k}:${Math.round(v)}`).join('  ') + `</div>`;
      }
    } else {
      html += `<div class="row"><span>核心</span><span class="bad">已摧毁</span></div>`;
    }
    html += `</div>`;
  }
  document.getElementById('side').innerHTML = html || '<div class="stat">等待数据…</div>';
}

async function loop() {
  try {
    const w = await fetchJSON('/data');
    world = w;
    document.getElementById('tick').textContent = w.state.tick ?? '-';
    document.getElementById('uc').textContent = w.units.length;
    document.getElementById('bc').textContent = w.buildings.length;
    document.getElementById('fc').textContent = w.frames;
    const conn = document.getElementById('conn');
    if (w.error) {
      conn.textContent = '错误'; conn.className = 'stat bad';
      document.getElementById('err').textContent = w.error;
    } else {
      conn.textContent = `延迟 ${w.age}s`; conn.className = 'stat ok';
      document.getElementById('err').textContent = '';
    }
    draw(w);
    renderSide(w);
  } catch (e) {
    document.getElementById('conn').textContent = '断开';
    document.getElementById('conn').className = 'stat bad';
    document.getElementById('err').textContent = String(e);
  }
  setTimeout(loop, 500);
}

loop();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    world = None

    def log_message(self, *a):
        pass    # 静音

    def _send(self, code, body, ctype):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif path == "/data":
            self._send(200, json.dumps(self.world.snapshot()),
                       "application/json; charset=utf-8")
        else:
            self._send(404, "not found", "text/plain")


def main():
    ap = argparse.ArgumentParser(description="AI 竞技场观战服务器")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7199, help="竞技场 HTTP 端口")
    ap.add_argument("--agent", default="referee")
    ap.add_argument("--token", required=True)
    ap.add_argument("--http-port", type=int, default=8080)
    ap.add_argument("--refresh", type=float, default=0.4, help="实体刷新周期（秒）")
    args = ap.parse_args()

    ref = Referee(args.host, args.port, args.agent, args.token)
    world = World(ref)

    print(f"[watch] 连接 {args.host}:{args.port} agent={args.agent}")
    world.load_terrain()
    world.refresh()

    def poller():
        while True:
            world.refresh()
            time.sleep(args.refresh)

    threading.Thread(target=poller, daemon=True).start()

    Handler.world = world
    srv = ThreadingHTTPServer(("127.0.0.1", args.http_port), Handler)
    print(f"[watch] 观战页面 http://127.0.0.1:{args.http_port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[watch] 退出")


if __name__ == "__main__":
    main()
