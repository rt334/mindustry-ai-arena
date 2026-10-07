#!/usr/bin/env python3
"""验证 `/diag` 的 `endpointLastCall`（TODO §14.5#1 的服务端侧）。

## 它在验什么

`/diag` 原本只有 `endpointCalls`（次数），答得了「它读了多少次 `/stalls`」，
**答不了「它读完告警之后紧接着做了什么」** —— 而分清「没读」和「读了没照做」
正需要后者。审计日志补不了这一半：它只记**写**操作，读接口一条不留。

`endpointLastCall` 补的就是这一半。这个脚本验四件事：

  1. 它存在，而且是被测 agent 自己那几条（可见性口径与 `endpointCalls` 一致）
  2. 刚调过的端点，`agoSec` 确实很小 —— 即它记的是**真时刻**，不是常量
  3. `endpointCalls` 的既有形状**没变**（那是已公开的契约，不能被这次改动破坏）
  4. 两个表的 key 互相对得上（同一份事实的两个出口，口径不许有第二套）

## 用法

先起服务器（`python start.py play`），再跑：

    python drive/verify-lastcall.py
    python drive/verify-lastcall.py --base http://127.0.0.1:7199

退出码：0 全过 / 1 有 FAIL / 2 环境缺东西（服务器没起、拿不到 token）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "server-run" / "config" / "ai-arena.json"
ADMIN_TOKEN_FILE = ROOT / "server-run" / "admin-token.txt"

PASS, FAIL = [], []


def rec(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'✓' if ok else '✗'} {name}" + (f"   {detail}" if detail and not ok else ""))


def call(base: str, agent: str, token: str, action: str, params: str = "",
         method: str = "GET", timeout: float = 10.0):
    url = f"{base}/v1/{agent}/{action}" + (f"?{params}" if params else "")
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"_raw": body[:200]}
    except Exception as e:
        return -1, {"_err": str(e)}


def load_tokens():
    """admin 走环境变量优先、再兜底文件（与四个 .ps1 同一口径）。

    参赛 token 从 config 读 —— **只为本地验证**，别把这一套抄进参赛端。
    """
    import os
    admin = os.environ.get("ARENA_ADMIN_TOKEN", "").strip()
    if not admin and ADMIN_TOKEN_FILE.exists():
        admin = ADMIN_TOKEN_FILE.read_text(encoding="utf-8-sig").strip()
    beta = None
    if CONFIG.exists():
        cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
        for a in cfg.get("agents") or []:
            if a.get("id") == "beta":
                beta = a.get("token")
    return admin, beta


def main() -> int:
    ap = argparse.ArgumentParser(description="验证 /diag 的 endpointLastCall")
    ap.add_argument("--base", default="http://127.0.0.1:7199")
    args = ap.parse_args()
    base = args.base

    print(f"base = {base}\n")

    # ---- 0. 环境 ----
    try:
        with urllib.request.urlopen(f"{base}/ping", timeout=5) as r:
            ping = json.loads(r.read().decode("utf-8"))
        rec("服务器在线（/ping）", True)
    except Exception as e:
        rec("服务器在线（/ping）", False, str(e))
        print("\n先 `python start.py play` 起服务器。")
        return 2
    print(f"      tick={ping.get('data', {}).get('tick')} "
          f"apiVersion={ping.get('data', {}).get('apiVersion')}")

    admin, beta = load_tokens()
    if not admin or not beta:
        print(f"\n拿不到 token（admin={bool(admin)} beta={bool(beta)}）—— "
              f"检查 {ADMIN_TOKEN_FILE} 与 {CONFIG}", file=sys.stderr)
        return 2

    # ---- 1. 让 beta 调几次「读」端点 ----
    # 故意调读接口：审计日志**不记**它们 —— 这正是这一项遥测要补的那个洞。
    touched = ["stalls", "state", "buildings"]
    for act in touched:
        st, body = call(base, "beta", beta, act)
        rec(f"beta 调 /{act} 成功", st == 200, f"HTTP {st} {str(body)[:120]}")
    mark = time.time()

    # 等一小会儿，让 agoSec 明显不是 0，但仍远小于「没调过」的量级
    time.sleep(1.5)

    # ---- 2. 读 /diag ----
    st, diag = call(base, "referee", admin, "diag")
    rec("/diag 成功（referee = admin）", st == 200, f"HTTP {st} {str(diag)[:160]}")
    if st != 200:
        return 1
    data = diag.get("data") or {}

    rec("有 endpointCalls", isinstance(data.get("endpointCalls"), dict))
    rec("有 endpointLastCall（本次新增）", isinstance(data.get("endpointLastCall"), dict))
    last = data.get("endpointLastCall") or {}
    calls = data.get("endpointCalls") or {}
    if not last:
        print("\n  endpointLastCall 是空的 —— 改动可能没生效（**重启服务器了吗？**）")
        return 1

    # ---- 3. 形状 ----
    for act in touched:
        key = f"beta:{act}"
        rec(f"endpointLastCall 含 {key}", key in last)
        if key in last:
            v = last[key]
            rec(f"{key} 有 lastMs/agoSec",
                isinstance(v, dict) and "lastMs" in v and "agoSec" in v, str(v))
            ago = v.get("agoSec")
            # 1.5 秒前调的 → 允许 0~20 秒的宽松窗口（起进程、调度都会吃掉一点）
            rec(f"{key} 的 agoSec 落在刚调过的量级",
                isinstance(ago, (int, float)) and 0 <= ago <= 20, f"agoSec={ago}")
            rec(f"{key} 的 lastMs 是真时刻（不是 0）",
                isinstance(v.get("lastMs"), (int, float)) and v["lastMs"] > 1_500_000_000_000,
                f"lastMs={v.get('lastMs')}")

    # ---- 3b. 反向验证：「最后一次」到底是最**后**，还是最**先** ----
    # 上面只说明「刚调过 → agoSec 小」。可一个「记第一次」的实现同样会小 ——
    # 所以再走两遍：重调同一个端点，看它是否**变小**；不重调，看它是否**变大**。
    # 只验「小」不验「变化方向」，等于没验到「最后」这两个字。
    #
    # 这里的 sleep 是**被测对象的一部分**（`agoSec` 就是时间的函数），
    # 与「禁止干等」那条纪律不冲突：那条管的是「用等待替代判据」，
    # 而这里等出来的时间差正是要断言的东西。
    key = "beta:stalls"
    first_ago = (last.get(key) or {}).get("agoSec")
    time.sleep(2.5)
    call(base, "beta", beta, "stalls")
    _, diag2 = call(base, "referee", admin, "diag")
    third = (diag2.get("data") or {}).get("endpointLastCall") or {}
    second_ago = (third.get(key) or {}).get("agoSec")
    rec("重调之后 agoSec 变小（记的是「最后一次」，不是「第一次」）",
        isinstance(first_ago, (int, float)) and isinstance(second_ago, (int, float))
        and second_ago < first_ago,
        f"重调前={first_ago} 重调后={second_ago}")

    _, diag3 = call(base, "referee", admin, "diag")
    fourth = (diag3.get("data") or {}).get("endpointLastCall") or {}
    third_ago = (fourth.get(key) or {}).get("agoSec")
    rec("不重调时 agoSec 会变大（不是常量）",
        isinstance(second_ago, (int, float)) and isinstance(third_ago, (int, float))
        and third_ago >= second_ago,
        f"前={second_ago} 后={third_ago}")

    # ---- 4. 兼容性：endpointCalls 的既有形状不许变 ----
    bad = {k: v for k, v in calls.items() if not isinstance(v, int)}
    rec("endpointCalls 的值仍全是整数（旧契约未破）", not bad, str(bad)[:160])

    # ---- 5. 两个表口径一致 ----
    # 同一次调用同时进两个表 → 有「最后一次」的 key 必然也有计数
    orphan = [k for k in last if k not in calls]
    rec("endpointLastCall 的 key ⊆ endpointCalls 的 key", not orphan, str(orphan)[:160])
    rec("端点数一致（同一份事实的两个出口）",
        len(last) <= len(calls), f"last={len(last)} calls={len(calls)}")

    print(f"\n{'─' * 64}")
    print(f"PASS {len(PASS)} / FAIL {len(FAIL)}")
    if FAIL:
        print("\n失败项：")
        for f in FAIL:
            print(f"  ✗ {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
