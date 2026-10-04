#!/usr/bin/env python3
"""ai-arena 接口客户端库。

只提供最需要的那几件事：连接与重试、轮询确认、产率/警报读取。

设计取舍
--------
**不做任何固定等待。** 所有「等它建好」类操作一律走 `poll_until`：传入判据函数，
命中就立刻返回，超时才返回 None。裸 `time.sleep(N)` 一律不允许 —— 那是把「多久」
当判据，而不是把「状态是否达成」当判据。

用法
----
    from arena import Arena

    a = Arena("alpha", token)
    a.place(61, 108, "mechanical-drill")
    a.poll_until(lambda: a.building_at(61, 108), timeout=60)

命令行自检：
    python arena.py --token T --agent alpha
"""
import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request


class ArenaError(Exception):
    def __init__(self, code, message):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


class Arena:
    def __init__(self, agent, token, host="127.0.0.1", port=7199,
                 timeout=15.0, max_retries=4, base_delay=0.3, max_delay=4.0):
        self.agent = agent
        self.token = token
        self.base = f"http://{host}:{port}/v1/{agent}"
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.reconnects = 0

    # ---------------------------------------------------------------- 传输

    def _call(self, path, params=None, method="GET", retry=True):
        url = f"{self.base}/{path}"
        if params:
            url += "?" + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None})
        delay = self.base_delay
        last = None
        for attempt in range(self.max_retries if retry else 1):
            try:
                req = urllib.request.Request(url, method=method)
                req.add_header("Authorization", f"Bearer {self.token}")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                # 4xx 是调用方的错，重试没意义 —— 立刻抛
                if not body.get("ok", False):
                    raise ArenaError(body.get("code", -1), body.get("error", "?"))
                return body.get("data")
            except ArenaError:
                raise
            except urllib.error.HTTPError as e:
                last = e
                if 400 <= e.code < 500:
                    raise ArenaError(e.code, f"HTTP {e.code}")
            except Exception as e:                      # 传输层
                last = e
            if attempt < self.max_retries - 1:
                time.sleep(delay)                        # 重连退避，不是「等建造」
                delay = min(delay * 2, self.max_delay)
                self.reconnects += 1
        raise ArenaError(-1, f"unreachable after retries: {last}")

    def get(self, path, **params):
        return self._call(path, params or None, "GET")

    def post(self, path, **params):
        return self._call(path, params or None, "POST")

    # ---------------------------------------------------------------- 只读

    def ping(self):
        """无鉴权健康检查；服务端没起来时返回 False 而不是抛异常。"""
        url = self.base.rsplit("/v1/", 1)[0] + "/ping"
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                return json.loads(r.read().decode()).get("ok", False)
        except Exception:
            return False

    def wait_online(self, timeout=120.0, interval=0.2):
        """轮询等在线（提前退出，不睡固定时长）。"""
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.ping():
                return True
            time.sleep(interval)
        return False

    def state(self):
        return self.get("state")

    def buildings(self):
        return self.get("buildings").get("buildings", [])

    def building_at(self, x, y):
        for b in self.buildings():
            if b["x"] == x and b["y"] == y:
                return b
        return None

    def units(self):
        return self.get("units").get("units", [])

    def map(self, x, y, w, h):
        return self.get("map", x=x, y=y, w=w, h=h).get("tiles", [])

    def rates(self, window=15):
        return self.get("rates", window=window).get("rates", {})

    def stalls(self):
        return self.get("stalls").get("stalls", [])

    def queue(self):
        return self.get("queue")

    def diag(self):
        return self.get("diag")

    # ---------------------------------------------------------------- 写

    def place(self, x, y, block, rot=None):
        return self.post("place", x=int(x), y=int(y), block=block, rot=rot)

    def break_block(self, x, y):
        return self.post("break", x=int(x), y=int(y))

    def control(self, op, **kw):
        return self.post("control", op=op, **kw)

    # ---------------------------------------------------------------- 轮询

    @staticmethod
    def poll_until(pred, timeout=60.0, interval=0.15):
        """轮询直到 pred() 为真。

        命中立刻返回其返回值；超时返回 None。

        **这是本库唯一允许的「等待」方式** —— 判据是状态，不是时长。
        """
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                v = pred()
            except ArenaError:
                v = None
            if v:
                return v
            time.sleep(interval)
        return None

    def place_and_confirm(self, x, y, block, rot=None, timeout=90.0):
        """下单并轮询确认建成。返回建筑 dict 或 None（超时）。"""
        self.place(x, y, block, rot)
        return self.poll_until(lambda: self.building_at(x, y), timeout=timeout)


def load_tokens(cfg_path=r"C:\dsh\ai-arena\server-run\config\ai-arena.json"):
    """读 ai-arena.json，返回 {agent_id: token} 以及 admin token。"""
    with open(cfg_path, encoding="utf-8-sig") as f:
        cfg = json.load(f)
    toks = {a["id"]: a["token"] for a in cfg["agents"]}
    admin = next((a for a in cfg["agents"] if a.get("admin")), None)
    return toks, (admin["token"] if admin else None)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="alpha")
    ap.add_argument("--token", required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7199)
    args = ap.parse_args()

    a = Arena(args.agent, args.token, args.host, args.port)
    print(f"ping      : {a.ping()}")
    st = a.state()
    print(f"state     : playing={st.get('playing')} tick={st.get('tick')}")
    print(f"buildings : {len(a.buildings())}")
    print(f"units     : {len(a.units())}")
    r = a.rates(window=10)
    for k, v in (r.get("core") or {}).items():
        print(f"rate core : {k:<10} {v['perSecond']:7.2f}/s")
    stl = a.stalls()
    print(f"stalls    : {len(stl)}")
    for s in stl[:8]:
        print(f"   {s.get('kind'):<14} ({s.get('x')},{s.get('y')})")
