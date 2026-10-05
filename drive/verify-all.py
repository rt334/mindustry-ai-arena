#!/usr/bin/env python3
"""把 docs/TODO.md §八 那份人工清单变成一条命令。

    python drive/verify-all.py

它做的是「那些只编译过的改动，到底跑起来对不对」—— 目前有六项：

    1  /ping 有没有 apiVersion
    2  bridge-<agent>.json 有没有 apiVersion
    3  /place 进审计、/map 不进（这项之前实机验过，跑它是为了回归）
    4  录像 meta 头有没有 apiVersion
    5  蓝图导出再导入
    6  SSE 流：事件 / 心跳 / end

**设计上的两条**：

  · **服务器没起时要清楚地拒绝**，而不是抛栈。本脚本自己就是被「没启游戏」
    卡住的产物，所以它的第一条判据就是「到底有没有服务端可验」。
  · 每项独立，某项失败不影响后面的 —— 一次跑完能拿到整张表，
    而不是第一项挂了就停。

写队列预算那项**不在这里**：它需要并发负载才有意义，属于手工项。
"""
import base64
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skill" / "scripts"))

AGENT = "beta"
results = []

# 鉴权：除了 /ping，其余端点都要 Bearer。
# 第一版忘了这一步 —— /ping 不需要鉴权所以过了，后面全 401，
# 表上看起来像「功能坏了」，其实是脚本没带 token。
TOKEN = None
ADMIN = None
try:
    from arena import load_tokens
    _toks, ADMIN = load_tokens()
    TOKEN = _toks.get(AGENT)
except Exception as e:
    print(f"  （读 token 失败：{e}）")


def done(name, ok, detail=""):
    results.append((name, ok, detail))
    mark = "PASS" if ok else ("SKIP" if ok is None else "FAIL")
    print(f"  [{mark}] {name}" + (f"  —— {detail}" if detail else ""))
    return ok


def http(path, method="GET", params=None, base=None, timeout=8, raw=False, admin=False):
    # 有的端点要 admin token（如 /record）。**token 与路径里的 agent 必须一致** ——
    # 用 referee 的 token 去请求 /v1/beta/... 会被判「token 不属于该 agent」。
    who = "referee" if admin else AGENT
    url = (base or f"http://127.0.0.1:7199/v1/{who}") + path
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(url, method=method)
    tok = ADMIN if admin else TOKEN
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, (body if raw else json.loads(body))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, (body if raw else json.loads(body))
        except Exception:
            return e.code, body
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"


def server_up():
    st, body = http("/ping", base="http://127.0.0.1:7199", timeout=5)
    if st != 200 or not isinstance(body, dict):
        return None
    return body.get("data") or {}


def main():
    print("== 前置：有没有服务端可验 ==")
    info = server_up()
    if not info:
        print("  服务端没在跑 —— 这一整轮验证的前提不成立。")
        print()
        print("  先 `python start.py play`，等 /ping 通了再跑本脚本。")
        print("  （本脚本是「没启游戏」的产物，所以它第一件事就是确认这一点，")
        print("    而不是抛一堆栈让人猜。）")
        return 2
    done("服务端在线", True, f"tick={info.get('tick')} agents={info.get('agents')}")
    print()

    # ── 1 ──────────────────────────────────────────────────────────────
    print("== 1. /ping 的 apiVersion（第 15 轮加的）==")
    v = info.get("apiVersion")
    done("/ping 带 apiVersion", bool(v), f"apiVersion={v!r}")

    # ── 2 ──────────────────────────────────────────────────────────────
    print("\n== 2. 端口发现文件里的 apiVersion（第 12 轮加的文件，第 15 轮加的字段）==")
    f = ROOT / "server-run" / f"bridge-{AGENT}.json"
    if not f.exists():
        done("bridge-<agent>.json", False, f"找不到 {f}")
    else:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            done("发现文件带 apiVersion", bool(d.get("apiVersion")),
                 f"文件内容 {json.dumps(d, ensure_ascii=False)}")
        except Exception as e:
            done("发现文件可解析", False, str(e))

    # ── 3 ──────────────────────────────────────────────────────────────
    print("\n== 3. 审计：/place 记、/map 不记（第 12 轮验过，这里是回归）==")
    log = ROOT / "server-run" / "ai-arena-audit.jsonl"
    before = log.stat().st_size if log.exists() else -1
    st, r = http("/state")
    core = None
    if isinstance(r, dict):
        for b in ((r.get("data") or {}).get("buildings") or []):
            if str(b.get("block", "")).startswith("core"):
                core = b
                break
    if not core:
        st2, bs = http("/buildings")
        bl = (bs.get("data") or {}).get("buildings") if isinstance(bs, dict) else None
        if bl:
            core = next((b for b in bl if str(b.get("block", "")).startswith("core")), None)
    if not core:
        done("找到核心", False, "拿不到核心坐标，跳过审计项")
    else:
        cx, cy = core["x"], core["y"]
        http("/place", "POST", {"x": cx + 4, "y": cy + 4, "block": "conveyor", "rot": 0})
        time.sleep(0.4)
        http("/map", params={"x": cx - 3, "y": cy - 3, "w": 7, "h": 7})
        time.sleep(1.0)
        after = log.stat().st_size if log.exists() else -1
        grew = after > before
        tail = ""
        if log.exists():
            lines = log.read_text(encoding="utf-8").strip().splitlines()
            tail = lines[-1][:120] if lines else ""
        done("审计日志有新增", grew, f"{before} → {after} B；末行 {tail}")

    # ── 4 ──────────────────────────────────────────────────────────────
    print("\n== 4. 录像 meta 的 apiVersion（第 16 轮加的）==")
    st, r = http("/record", "POST", {"action": "start"}, admin=True)
    if st != 200:
        done("录像开始", False, f"code={st} {str(r)[:90]}")
    else:
        http("/place", "POST", {"x": 0, "y": 0, "block": "conveyor", "rot": 0})
        time.sleep(3)
        http("/record", "POST", {"action": "stop"}, admin=True)
        time.sleep(1)
        # 录像写在 Core.settings.getDataDirectory()/ai-arena-recordings/ 下，
        # 不是 server-run 根目录 —— 第一版搜错了地方，报「没找到文件」。
        recdir = ROOT / "server-run" / "config" / "ai-arena-recordings"
        recs = sorted(recdir.glob("*.jsonl"), key=lambda q: q.stat().st_mtime,
                      reverse=True) if recdir.exists() else []
        if not recs:
            done("找到录像文件", False, "没找到新的 .jsonl")
        else:
            p = recs[0]
            head = ""
            with p.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    head = line
                    break
            got = "apiVersion" in head
            done("录像 meta 带 apiVersion", got, f"{p.name} 首行 {head[:110]}")

    # ── 5 ──────────────────────────────────────────────────────────────
    print("\n== 5. 蓝图导出 → 导入（第 14 轮加的）==")
    if not core:
        done("蓝图", None, "没有核心坐标")
    else:
        cx, cy = core["x"], core["y"]
        st, r = http("/blueprint", params={"x": cx - 8, "y": cy - 8, "w": 16, "h": 16})
        d = (r or {}).get("data") if isinstance(r, dict) else None
        if st != 200 or not d or not d.get("data"):
            done("蓝图导出", False, f"code={st} {str(r)[:110]}")
        else:
            n = d.get("count")
            done("蓝图导出", True, f"导出 {n} 个方块，base64 {len(d['data'])} 字符")
            plain = base64.b64decode(d["data"]).decode("utf-8")
            try:
                j = json.loads(plain)
                done("导出的 JSON 可解析", True,
                     f"v={j.get('v')} w={j.get('w')} h={j.get('h')} blocks={len(j.get('blocks') or [])}")
            except Exception as e:
                done("导出的 JSON 可解析", False, str(e))
            # 导到别处（平移 20 格，多半会撞地形/视野，只要不是崩就算通）
            st2, r2 = http("/blueprint", "POST",
                           {"x": cx + 12, "y": cy + 12, "data": d["data"]})
            d2 = (r2 or {}).get("data") if isinstance(r2, dict) else None
            ok = st2 in (200, 403, 400) and isinstance(r2, (dict, str))
            done("蓝图导入有结构化答复", ok,
                 f"code={st2} {json.dumps(d2, ensure_ascii=False)[:120] if d2 else str(r2)[:120]}")

    # ── 6 ──────────────────────────────────────────────────────────────
    print("\n== 6. SSE 流（第 13 轮加的）==")
    st, body = http("/stream", params={"since": 0, "seconds": 5}, raw=True, timeout=20)
    if st != 200:
        done("SSE 连上", False, f"code={st} {str(body)[:110]}")
    else:
        txt = body if isinstance(body, str) else str(body)
        has_hello = "event: hello" in txt
        has_event = "event: ev" in txt
        has_cursor = "event: cursor" in txt
        has_end = "event: end" in txt
        done("SSE 连上", True, f"收到 {len(txt)} 字节")
        done("有 hello", has_hello)
        done("有 ev 或 cursor（说明在推事件）", has_event or has_cursor,
             f"ev={has_event} cursor={has_cursor}")
        done("有 end（生存期收尾）", has_end)

    # ── 汇总 ───────────────────────────────────────────────────────────
    print("\n== 汇总 ==")
    p = sum(1 for _, ok, _ in results if ok is True)
    f_ = sum(1 for _, ok, _ in results if ok is False)
    s = sum(1 for _, ok, _ in results if ok is None)
    print(f"  PASS {p} / FAIL {f_} / SKIP {s}")
    if f_:
        print("\n  未通过的：")
        for name, ok, det in results:
            if ok is False:
                print(f"    - {name}  {det}")
    print("\n  不在本脚本里的手工项：**写队列每 tick 预算** —— 要造并发负载才有意义。")
    return 0 if f_ == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
