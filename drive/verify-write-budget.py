#!/usr/bin/env python3
"""写队列每 tick 预算 —— 用并发负载验它会不会触发。

这项一直没验，因为它**没有负载时永远不触发**。放进 verify-all.py 只会造出
一张「没测到东西」的假绿表，所以一直留着手工。

预算逻辑（HttpApi.postToGame）：在主线程里计量任务真正执行的时间、按 tick 累计，
tick 一变清零；预算（默认 1ms/tick）用完后返回 1007，
消息形如 "write queue budget exhausted for tick N (1.0 ms/tick); retry next tick"。

验法：并发打写请求，看有没有 1007。
**注意限流**（60/s，burst 200）—— 打太猛会先撞 1429，那是另一回事，
所以要把两种码分开统计。
"""
import collections
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, load_tokens

AGENT = "beta"
N_THREADS = 24
SECONDS = 8


def main():
    toks, _ = load_tokens()
    tok = toks[AGENT]
    base = f"http://127.0.0.1:7199/v1/{AGENT}"
    a = Arena(AGENT, tok)

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

    codes = collections.Counter()
    msgs = {}
    lock = threading.Lock()
    stop = threading.Event()
    sent = [0]

    def worker(tid):
        n = 0
        while not stop.is_set():
            # 每线程打不同的格/方块组合，避免全撞同一个 footprint
            x = cx + (tid % 8) + 1
            y = cy + 8 + (tid // 8) + n % 3
            url = f"{base}/place?x={x}&y={y}&block=conveyor&rot=0"
            req = urllib.request.Request(url, method="POST")
            req.add_header("Authorization", f"Bearer {tok}")
            try:
                with urllib.request.urlopen(req, timeout=6) as r:
                    r.read()
                    code = r.status
                    body = ""
            except urllib.error.HTTPError as e:
                code = e.code
                body = e.read().decode("utf-8", "replace")
            except Exception:
                code = -1
                body = ""
            key = code
            try:
                j = json.loads(body)
                key = (code, j.get("code"))
                with lock:
                    if key not in msgs:
                        msgs[key] = (j.get("error") or "")[:150]
            except Exception:
                pass
            with lock:
                codes[key] += 1
                sent[0] += 1
            n += 1

    print(f"\n== {N_THREADS} 线程 × {SECONDS} 秒并发写 ==")
    ths = [threading.Thread(target=worker, args=(i,), daemon=True)
           for i in range(N_THREADS)]
    t0 = time.monotonic()
    for t in ths:
        t.start()
    time.sleep(SECONDS)
    stop.set()
    for t in ths:
        t.join(timeout=8)
    dt = time.monotonic() - t0

    print(f"  共发出 {sent[0]} 次，耗时 {dt:.1f}s（≈{sent[0]/dt:.0f}/s）\n")
    print("  结果分布：")
    for k, n in codes.most_common():
        note = msgs.get(k, "")
        print(f"    {str(k):<14} {n:>6}   {note}")

    budget = [k for k in codes if isinstance(k, tuple) and k[1] == 1007]
    limited = [k for k in codes if isinstance(k, tuple) and k[1] == 1429]
    print()
    if budget:
        print("  **写队列预算：触发过** —— 1007 出现了，说明按 tick 的计量在起作用。")
        print(f"     样本消息：{msgs[budget[0]]}")
        return 0
    if limited:
        print("  **没触发 1007，但撞到了 1429（限流）** —— 瓶颈在令牌桶，不在写队列。")
        print("     这说明当前负载还没到写队列的水位；要压得更狠得先放宽限流")
        print("     （-Darena.ratePerSecond= / -Darena.rateBurst=）。")
        print("     **结论：这项仍未验证**，不能记成通过。")
        return 2
    print("  **没触发 1007，也没撞限流** —— 负载不够，这项仍未验证。")
    return 2


if __name__ == "__main__":
    sys.exit(main())
