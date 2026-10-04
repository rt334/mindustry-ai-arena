#!/usr/bin/env python3
"""ai-arena 操作库：批量下单/拆除 + 轮询确认 + 限速。

纪律：
  * 任何「等建造完成」都用轮询判据（buildings 里是否出现目标），不用固定时长。
  * /place 只代表入队，必须回查 /buildings 才算数。
"""
import json, threading, time, urllib.error, urllib.parse, urllib.request

ALPHA = "72d17a532ac7296c7f9eaddb2718c133a3d7e724862f006f"
REF = "0dfdae3b5fbdbbc13976591ec467c9d44e957c6e6bd676da"


class Arena:
    def __init__(self, agent="alpha", token=ALPHA, host="127.0.0.1", port=7199, rate=45.0):
        self.base = f"http://{host}:{port}/v1/{agent}"
        self.tok = token
        self._lock = threading.Lock()
        self._min_gap = 1.0 / rate
        self._next = 0.0

    def _gate(self):
        with self._lock:
            now = time.time()
            wait = self._next - now
            if wait > 0:
                time.sleep(wait)
            self._next = max(now, self._next) + self._min_gap

    def call(self, path, method="GET", **params):
        url = f"{self.base}/{path}"
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        for attempt in range(5):
            self._gate()
            try:
                req = urllib.request.Request(url, method=method)
                req.add_header("Authorization", f"Bearer {self.tok}")
                with urllib.request.urlopen(req, timeout=20) as r:
                    b = json.loads(r.read().decode())
                if not b.get("ok"):
                    raise RuntimeError(f"{b.get('code')} {b.get('error')}")
                return b.get("data")
            except Exception as e:
                if attempt == 4:
                    raise
                time.sleep(0.25 * (attempt + 1))
        return None

    # ---- 只读 ----
    def buildings(self):
        return {b["x"]: b for b in []} or {(b["x"], b["y"]): b for b in self.call("buildings")["buildings"]}

    def building_at(self, x, y):
        return self.buildings().get((x, y))

    def rates(self, window=15):
        return self.call("rates", window=window)["rates"]

    def stalls(self):
        return self.call("stalls")["stalls"]

    def queue(self):
        return self.call("queue")

    def drill(self):
        return self.call("drill")

    def factory(self):
        return self.call("factory")

    def state(self):
        return self.call("state")

    def map(self, x, y, w, h, view=None):
        return self.call("map", x=x, y=y, w=w, h=h, view=view)["tiles"]

    # ---- 写 ----
    def place(self, x, y, block, rot=None):
        return self.call("place", method="POST", x=int(x), y=int(y), block=block, rot=rot)

    def break_block(self, x, y):
        return self.call("break", method="POST", x=int(x), y=int(y))

    # ---- 批量 ----
    def place_many(self, specs, workers=6):
        """specs: [(x,y,block,rot), ...]  —— 并发下单，返回失败列表。"""
        errs = []
        lock = threading.Lock()

        def one(s):
            x, y, blk = s[0], s[1], s[2]
            rot = s[3] if len(s) > 3 else None
            try:
                self.place(x, y, blk, rot)
            except Exception as e:
                with lock:
                    errs.append((x, y, blk, str(e)))

        ths = [threading.Thread(target=one, args=(s,)) for s in specs for _ in range(1)]
        # 简单分片并发（避免一次开太多线程）
        chunks = [specs[i::workers] for i in range(workers)]
        ths = [threading.Thread(target=lambda c=c: [one(s) for s in c]) for c in chunks]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        return errs

    def break_many(self, cells, workers=6):
        errs = []
        lock = threading.Lock()

        def one(c):
            try:
                self.break_block(c[0], c[1])
            except Exception as e:
                with lock:
                    errs.append((c[0], c[1], str(e)))

        chunks = [cells[i::workers] for i in range(workers)]
        ths = [threading.Thread(target=lambda c=c: [one(s) for s in c]) for c in chunks]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        return errs

    # ---- 轮询确认 ----
    @staticmethod
    def poll_until(pred, timeout=120.0, interval=0.12):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                v = pred()
            except Exception:
                v = None
            if v:
                return v
            time.sleep(interval)
        return None

    def confirm_placed(self, specs, timeout=180.0, require_all=True):
        """轮询直到 specs 里的方块全部出现在 /buildings。返回 (ok_list, missing_list)。"""
        want = {(s[0], s[1]): s[2] for s in specs}

        def check():
            bs = self.buildings()
            got = [k for k, v in want.items() if bs.get(k, {}).get("block") == v]
            if require_all and len(got) == len(want):
                return got
            if not require_all and got:
                return got
            return None

        r = self.poll_until(check, timeout=timeout)
        bs = self.buildings()
        missing = [(k[0], k[1], v) for k, v in want.items() if bs.get(k, {}).get("block") != v]
        return (r or []), missing

    def confirm_broken(self, cells, timeout=120.0):
        want = set(cells)
        r = self.poll_until(lambda: not (want & set(self.buildings().keys())), timeout=timeout)
        left = sorted(want & set(self.buildings().keys()))
        return (r is not None), left
