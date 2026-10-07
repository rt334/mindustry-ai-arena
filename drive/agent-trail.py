#!/usr/bin/env python3
"""子代理动作审计 —— 把参赛 AI 的「想了什么 / 调了什么 / 拿到什么」摊开成一条时间线。

## 为什么需要它（docs/TODO.md §14.5#1）

服务端那两个数据源**都答不了**「它读完告警之后紧接着做了什么」：

  - `Audit`（服务端审计）只记**写**操作 —— `/stalls` `/map` `/buildings` 是读，不留痕。
    实测：人机对局那一局 AI 调了 25 次 `/stalls`，审计里 **0 条**。
  - `/diag` 的 `endpointCalls`（`CALLS`）只有**累计计数**，没有时间戳、没有参数、没有顺序。

而参赛 AI 是 DSH 子代理，**它自己的会话记录里有全部三样东西**：

    assistant/message → content[] 里的 {"type":"reasoning"}  → 在想什么
    tool/call         → name + arguments（完整命令行）        → 调了什么
    tool/result       → content[]                            → 拿到什么

所以「审计子代理动作」**不需要往 mod 里加任何东西** —— 会话记录本身已经是完整的，
缺的只是把它读出来的工具。这也是它比服务端记录强的地方：服务端永远看不到 reasoning。

## 覆盖范围的两个边界（别误用）

  1. 它**只覆盖 DSH 子代理执行的 AI**。如果参赛方是别的 harness（或人类），本工具为空。
  2. 会话文件在**参赛进程自己的机器上**（同机就是 `%USERPROFILE%\\.dsh`）。
     被审计方有能力删改它 —— 所以它适合**复盘与自查**，不适合当**仲裁的唯一凭据**。
     仲裁要凭服务端那份（`server-run/ai-arena-audit.jsonl` + `/events` + 录像）。

## 用法

    python drive/agent-trail.py --list                      列出子代理会话（label / id / 时间 / 步数）
    python drive/agent-trail.py --label distribution        按 label 模糊匹配（大小写不敏感）
    python drive/agent-trail.py --id 9bb3f4ea               按 id 前缀
    python drive/agent-trail.py --id 9bb3f4ea --http        只看 HTTP 调用 —— 它在调哪些接口
    python drive/agent-trail.py --id 9bb3f4ea --files       只看文件访问 + 越界标记
    python drive/agent-trail.py --id 9bb3f4ea --thinking    只看 reasoning —— 它在想什么
    python drive/agent-trail.py --id 9bb3f4ea --json        机器可读（完整，不截断）

    python drive/agent-trail.py --id 9bb3f4ea --align       与服务端审计对齐（见下）

    --full    不截断长字段（reasoning / 命令 / 结果默认各截到 400 字符）
    --limit N --align 模式下最多显示多少条（默认 200）

## `--align`：把两侧并成一条时间线

会话侧有**它调了什么、在想什么**，服务端侧有**世界真的变了什么**（`server-run/ai-arena-audit.jsonl`，
只记写操作）。两侧单独看都答不了「它在 T 读了告警，之后做了什么」—— 合起来才看得出时间差：

    [19:52:30.376] 会话     step  19 src   a.batch() ×1        ← 写了要下 batch
    [19:52:31.436] 会话     step  20 pwsh                      ← 跑了脚本
    [19:52:32.333] 服务端    写 batch ops=p,292,111,mechanical-drill,0;…   ← 世界真变了，差 2 秒

口径与两个必须知道的限制：

  - **时间可直接比**：审计的 `t` 是 UTC ISO，会话的 `time` 是 epoch 毫秒 —— 都是绝对时间，
    不必管本机时区。窗口按会话全程自动裁（审计是跨局累积的，不限窗会被几天前的记录淹掉）。
  - **agent 名自动推断**（取会话里出现最多的 `/v1/<agent>/`），推断结果会打印出来，
    用 `--agent` 可覆盖 —— **猜错比不猜更坏**，所以只认最高频那一个。
  - **会话侧的读事件是下界**：参赛 AI 常把调用写进自建脚本，脚本**内部**的调用在会话侧
    只有 `src` 层（「写了要调什么」）而看不到实际执行。服务端侧的写操作才是全量。

退出码：0 正常；2 找不到会话；3 环境缺依赖（缺 `zstandard`）。
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import urllib.parse
from pathlib import Path

# Windows 中文控制台是 GBK，本脚本会打印 reasoning 原文（常含中文）——
# 不钉 UTF-8 的话 print 会抛 UnicodeEncodeError，看起来像脚本坏了。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SESSIONS_ROOT = Path.home() / ".dsh" / "sessions"
SESSION_FILE = "session.v4.jsonl.zstd"

ROOT = Path(__file__).resolve().parent.parent
AUDIT_PATH = ROOT / "server-run" / "ai-arena-audit.jsonl"

# 那几轮对战的任务书里写死的硬性禁止：「不要读 docs/、drive/、mod/、_work/ 下的任何文件」。
# 这几个目录装的是**实测出来的游戏内情**，读了等于开局前就拿答案。
FORBIDDEN_DIRS = ("docs", "drive", "mod", "_work")
# 允许区：参赛者自己的技能包与自建工作目录。
ALLOWED_HINTS = ("skill", "work")

HTTP_RE = re.compile(r"https?://127\.0\.0\.1:7199/v1/([A-Za-z0-9_\-]+)/([A-Za-z0-9_\-]+)(\?[^\"'\s|;)$\\]*)?")
# `curl.exe -X POST` / `-sS -XPOST` 都算；没显式给 -X 时 curl 默认 GET
CURL_X_RE = re.compile(r"-X\s*([A-Z]+)")
WINPATH_RE = re.compile(r"[A-Za-z]:\\\\?[\w.\\\-]+")
WINDOWS_ABS_RE = re.compile(r"([A-Za-z]):\\([^\"'|;)\s]*)")


def load_zstd():
    try:
        import zstandard  # noqa: F401
        return zstandard
    except ImportError:
        print("缺依赖：pip install zstandard", file=sys.stderr)
        raise SystemExit(3)


def read_session(path: Path, head_only: int | None = None):
    """解压并解析会话。head_only 给字节数时只读解压流的前若干字节（用于 --list 快速扫）。

    ⚠ `stream_reader.read(n)` **不保证返回 n 字节** —— 它撞上 zstd 帧边界就返回。
    实测请求 8192 只拿回 262（正好第一条 `session` 记录），于是第二条
    `subagent/descriptor` 永远读不到，`--list` 的 label 列全是空的。
    所以这里循环读到够为止。
    """
    import zstandard
    dctx = zstandard.ZstdDecompressor()
    with open(path, "rb") as f:
        reader = dctx.stream_reader(f)
        if head_only is None:
            raw = reader.read()
        else:
            chunks, total = [], 0
            while total < head_only:
                b = reader.read(head_only - total)
                if not b:
                    break
                chunks.append(b)
                total += len(b)
            raw = b"".join(chunks)
    text = raw.decode("utf-8", errors="replace")
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def clip(s: str, n: int) -> str:
    if s is None:
        return ""
    s = str(s)
    return s if len(s) <= n else s[:n] + f"  …(+{len(s) - n})"


def all_sessions() -> list[Path]:
    if not SESSIONS_ROOT.is_dir():
        return []
    return sorted(SESSIONS_ROOT.rglob(SESSION_FILE))


def describe(path: Path) -> dict:
    """只读每个会话的前几 KB —— 拿 label / id / 时间就够了，不必解压整份。"""
    info = {"path": path, "id": path.parent.name, "label": "", "created": None,
            "model": "", "depth": None, "origin": ""}
    try:
        recs = read_session(path, head_only=8192)
    except Exception as e:
        info["label"] = f"<读失败: {type(e).__name__}>"
        return info
    for r in recs[:4]:
        t = r.get("type")
        d = r.get("data") or {}
        if t == "session":
            info["id"] = r.get("id", info["id"])
            info["created"] = r.get("createdAt")
            info["origin"] = r.get("origin", "")
            info["depth"] = r.get("delegationDepth")
        elif t == "subagent/descriptor":
            info["label"] = d.get("label", "")
            info["model"] = d.get("agentModel", "")
    return info


# ------------------------------------------------------------------ 提取

_ARENA_METHODS: set | None = None


def arena_methods() -> set:
    """从参赛者那侧的客户端库 `skill/scripts/arena.py` 取出方法名。

    为什么从这里取而不是硬编码一份：那个库就是参赛 AI 实际用来调接口的东西，
    方法名基本与端点同名（`a.stalls()` -> `/v1/<agent>/stalls`）。它改了，
    这个审计跟着改；硬编码一份迟早漂移。

    实测依据（那轮布局测试，92 步）：40 次 `write` 写的脚本**全都是**
    `from arena import Arena` 然后 `a.state()` / `a.buildings()` / `a.rates()` ——
    **接口调用几乎全在这条路上**，直连 curl 只有 6 次。第一版没扫这里，
    于是「它调了什么接口」几乎是空的。
    """
    global _ARENA_METHODS
    if _ARENA_METHODS is not None:
        return _ARENA_METHODS
    p = Path(__file__).resolve().parent.parent / "skill" / "scripts" / "arena.py"
    methods = set()
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*def ([a-z]\w*)\(", line)
            if m and not m.group(1).startswith("_"):
                methods.add(m.group(1))
    except OSError:
        pass
    _ARENA_METHODS = methods
    return methods


def extract_http(call: dict) -> list[dict]:
    """从一次工具调用里挖出 HTTP 请求，并按**证据强度分层**标注。

    参赛 AI 有三种调用形态，可靠性依次递减 —— 混在一起会把「打算调」和「调了」
    算成一样，所以分开标：

      1. `pwsh` 里直接 `curl.exe ...`      -> `exec`  **实际执行**，最可靠
      2. `pwsh` 里调 `skill/scripts/arena.py` -> `wrap`  经客户端封装
      3. `write`/`edit` 往自建脚本里写 URL  -> `src`   **脚本内置，未必被执行过**

    第 3 条是实测补上的：那轮布局测试跑了 92 步，直连 curl 只抓到 6 次，
    因为它把调用写进了自建脚本（`build2..7.py` / `diag*.py`）—— 不扫脚本内容
    会把「它调了多少次接口」估低一个量级。
    """
    name = call.get("name") or ""
    try:
        args = json.loads(call.get("arguments") or "{}")
    except json.JSONDecodeError:
        args = {}
    blob = json.dumps(args, ensure_ascii=False)

    found = []
    if name == "pwsh":
        m = CURL_X_RE.search(blob)
        for agent, action, query in HTTP_RE.findall(blob):
            found.append({"via": "exec", "method": m.group(1) if m else "GET",
                          "agent": agent, "action": action, "query": query.lstrip("?")})
        # 经封装也要记，而且不能只在「没抓到 curl」时才记 —— 实测那轮 92 步里
        # 只有 6 次直连，其余全走客户端封装。**不猜方法名**：命令行里的写法太多样
        # （`python -c`、脚本内调用、变量拼接），猜错比不猜更坏。
        # 具体调了什么看紧邻的 tool/result；要看命令行原文用 `--commands`。
        if "arena.py" in blob or "arena_ops" in blob:
            found.append({"via": "wrap", "method": "-", "agent": "-",
                          "action": "arena.py", "query": ""})
    elif name in ("write", "edit"):
        content = str(args.get("content") or args.get("new_string") or "")
        known = arena_methods()
        counts: dict = {}
        for m in re.finditer(r"\.([a-z]\w*)\(", content):
            meth = m.group(1)
            if meth in known:
                counts[meth] = counts.get(meth, 0) + 1
        for meth, cnt in sorted(counts.items(), key=lambda kv: -kv[1]):
            found.append({"via": "src", "method": "-", "agent": "-",
                          "action": f"a.{meth}()", "query": f"×{cnt}"})
    return found


def extract_files(call: dict) -> list[str]:
    """这次调用碰了哪些文件路径。空列表 = 没碰文件。"""
    name = call.get("name") or ""
    try:
        args = json.loads(call.get("arguments") or "{}")
    except json.JSONDecodeError:
        return []
    paths = []
    if isinstance(args.get("file_path"), str):
        paths.append(args["file_path"])
    cmd = args.get("command")
    if isinstance(cmd, str):
        for m in WINPATH_RE.finditer(cmd):
            paths.append(m.group(0))
    # 去重保序
    seen, out = set(), []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def is_forbidden(path: str) -> bool:
    """路径是否落在那四个禁令目录里。按路径分段判，避免 'modules' 被 'mod' 误伤。"""
    low = path.replace("\\", "/").lower()
    if "ai-arena" not in low:
        return False
    parts = [p for p in low.split("/") if p]
    for i, seg in enumerate(parts):
        if seg == "ai-arena" and i + 1 < len(parts):
            return parts[i + 1] in FORBIDDEN_DIRS
    return False


def walk(recs: list[dict]):
    """把记录流折成 `[(key, {time, reasoning[], text[], calls[], results{}})]`。

    每个 step 会散成好几条记录（想的、调的、拿到的）—— `time` 取这批里**最早**那条，
    即「它开始想这一步」的时刻。与服务端审计对齐时以它为锚点。
    """
    steps: dict[tuple, dict] = {}
    order: list[tuple] = []

    def bucket(key, r):
        st = steps.setdefault(key, {"time": None, "reasoning": [], "text": [],
                                    "calls": [], "results": {}})
        if key not in order:
            order.append(key)
        if st["time"] is None and r.get("time"):
            st["time"] = r["time"]
        return st

    for r in recs:
        t = r.get("type")
        d = r.get("data") or {}
        if t == "assistant/message":
            st = bucket((d.get("turn"), d.get("step")), r)
            msg = (d.get("message") or {})
            for b in msg.get("content") or []:
                bt = b.get("type")
                if bt == "reasoning" and (b.get("text") or "").strip():
                    st["reasoning"].append(b["text"])
                elif bt == "text" and (b.get("text") or "").strip():
                    st["text"].append(b["text"])
                elif bt == "tool-call":
                    st["calls"].append({"name": b.get("name"), "arguments": b.get("arguments"),
                                        "callId": b.get("id")})
        elif t == "tool/call":
            st = bucket((d.get("turn"), d.get("step")), r)
            st["calls"].append({"name": d.get("name"), "arguments": d.get("arguments"),
                                "callId": d.get("callId")})
        elif t == "tool/result":
            st = bucket((d.get("turn"), d.get("step")), r)
            msg = d.get("message") or {}
            txt = "\n".join(b.get("text", "") for b in (msg.get("content") or [])
                            if b.get("type") == "text")
            st["results"][d.get("toolCallId") or msg.get("toolCallId")] = txt
    # 同一 step 里 tool/call 与 assistant 里的 tool-call 会重复 —— 按 callId 去重
    for key in order:
        st = steps[key]
        seen, uniq = set(), []
        for c in st["calls"]:
            cid = c.get("callId")
            if cid and cid in seen:
                continue
            if cid:
                seen.add(cid)
            uniq.append(c)
        st["calls"] = uniq
    return [(k, steps[k]) for k in order]


# ------------------------------------------------------------------ 两侧对齐

def load_server_audit(agent: str, t0: float, t1: float) -> list[dict]:
    """读服务端审计，只留**该 agent** 的、落在 `[t0, t1]` 窗口内的行。

    为什么必须按窗口过滤：审计是**跨所有局累积**的（实测 1.6 万行、跨两天），
    不过滤的话一个 92 步的会话会被几天前的写操作淹掉。

    时间口径：审计的 `t` 是 UTC ISO（`...Z`），会话的 `time` 是 epoch 毫秒 ——
    两者都是**绝对时间**，直接比即可，不必管本机时区。

    只收**写操作**：那个文件里只有两类东西 —— 改状态的动作，以及带 `privileged`
    标记的特权读。后者用它自己的字段排掉。
    """
    rows: list[dict] = []
    if not AUDIT_PATH.is_file():
        return rows
    with AUDIT_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("agent") != agent or o.get("privileged"):
                continue
            try:
                ts = datetime.datetime.fromisoformat(
                    o["t"].replace("Z", "+00:00")).timestamp() * 1000.0
            except (KeyError, ValueError, AttributeError):
                continue
            if t0 <= ts <= t1:
                rows.append({"ms": ts, "action": o.get("action", "?"),
                             "query": o.get("query", "") or "", "tick": o.get("tick")})
    rows.sort(key=lambda r: r["ms"])
    return rows


def guess_agent(steps) -> str | None:
    """从会话的工具调用里猜它是哪个参赛 agent（`/v1/<agent>/...` 里的那个）。

    依据是**实际操作**而不是任何文档：会话里出现最多的 agent 名就是它。
    只认最高频的那一个，而且调用方会把它打印出来让人能一眼否掉 ——
    **猜错比不猜更坏**，所以这里不猜第二可能的、也不做模糊匹配。
    """
    counts: dict = {}
    for _key, st in steps:
        for call in st["calls"]:
            for h in extract_http(call):
                if h["agent"] not in ("-", ""):
                    counts[h["agent"]] = counts.get(h["agent"], 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _hhmmss(ms: float, full: bool = False) -> str:
    """毫秒 → 本地时间串。`full=True` 时带日期（对齐的标题用它，跨天不会混）。"""
    fmt = "%Y-%m-%d %H:%M:%S" if full else "%H:%M:%S"
    return datetime.datetime.fromtimestamp(ms / 1000).strftime(fmt + ".%f")[:-3]


def align(steps, rows, args) -> None:
    """把会话事件与服务端的写操作合成一条时间线。

    **它回答单独任何一侧都答不了的问题**：「它在 T 读了告警，之后做了什么？」
    会话侧有全部工具调用（含读接口），服务端侧有世界**真的变了**的那些动作。
    两边一合，时间差就摆在那里了。

    **一个必须明说的下界**：参赛 AI 常把接口调用写进自建脚本（实测那轮 40 次
    `write` 全是 `from arena import Arena`），脚本内部的调用在会话侧只有 `src` 层
    （「它写了要调什么」）而**看不到实际执行**。所以会话侧的读事件是**下界**；
    服务端侧的写操作才是全量 —— 那正是它不可替代的地方。
    """
    events: list[tuple] = []
    for (turn, step), st in steps:
        t = st.get("time")
        if not t:
            continue
        for c in st["calls"]:
            https = extract_http(c)
            for h in https:
                # 与 render() 同一套拼法：`agent == "-"` 的是封装/脚本内置，
                # 不是一条能点的 URL，别给它套 `/v1/` 前缀
                if h["agent"] == "-":
                    desc = f"{h['action']} {h['query']}".rstrip()
                else:
                    q = f"?{h['query']}" if h["query"] else ""
                    desc = f"{h['agent']}/{h['action']}{q}"
                events.append((t, "会话", f"step {step:>3} {h['via']:5s} {desc}"))
            if not https:
                events.append((t, "会话", f"step {step:>3} {c['name']}"))
    for r in rows:
        # 审计存的是原样 query（设计如此：按动作解析容易漏字段），
        # 但 `batch` 的 ops 是整串 URL 编码的 —— 不解码根本读不了
        q = urllib.parse.unquote(r["query"]) if r["query"] else ""
        q = clip(q.replace("&", " "), 110)
        events.append((r["ms"], "服务端", f"写 {r['action']} {q}".rstrip()))
    events.sort(key=lambda e: e[0])

    shown = events if args.full else events[:args.limit]
    for ms, side, text in shown:
        print(f"[{_hhmmss(ms)}] {side:6s} {text}")
    if len(events) > len(shown):
        print(f"  …（另有 {len(events) - len(shown)} 条未显示；--full 全看，"
              f"--limit N 调条数）")


# ------------------------------------------------------------------ 渲染

def render(steps, args) -> None:
    only_http, only_files, only_think = args.http, args.files, args.thinking
    n = 400 if not args.full else 10 ** 9
    for (turn, step), st in steps:
        lines = []
        for rs in st["reasoning"]:
            lines.append(("think", clip(rs, n)))
        for c in st["calls"]:
            https = extract_http(c)
            files = extract_files(c)
            if only_http and not https:
                continue
            if only_files and not files:
                continue
            if only_think:
                continue
            if args.commands:
                # 命令行原文 —— 正则只能抓到能识别的部分，原文给人看最准
                try:
                    a = json.loads(c.get("arguments") or "{}")
                except json.JSONDecodeError:
                    a = {}
                raw = a.get("command") or a.get("file_path") or json.dumps(a, ensure_ascii=False)
                lines.append(("tool", clip(str(raw).replace("\n", " ⏎ "), n)))
                continue
            for h in https:
                if h["agent"] == "-":
                    # 经封装 / 脚本内置 —— 不是一条能点的 URL，别伪装成 URL
                    lines.append(("http", f"{h['via']:5s} {h['action']} "
                                          f"{h['query']}".rstrip()))
                else:
                    q = f"?{h['query']}" if h["query"] else ""
                    lines.append(("http", f"{h['via']:5s} {h['method']:4s} "
                                          f"/v1/{h['agent']}/{h['action']}{q}"))
            for f in files:
                flag = "  ⚠越界" if is_forbidden(f) else ""
                lines.append(("file", f + flag))
            if not https and not files and not only_http and not only_files:
                lines.append(("tool", clip(f"{c['name']}  {c.get('arguments','')}", n)))
            res = st["results"].get(c.get("callId"))
            if res and not only_http and not only_files and not only_think:
                lines.append(("result", clip(res.replace("\n", " ⏎ "), n)))
        if only_think:
            lines = [l for l in lines if l[0] == "think"]
        if args.commands:
            lines = [l for l in lines if l[0] == "tool"]
        if not lines:
            continue
        print(f"[turn {turn} step {step}]")
        for kind, text in lines:
            prefix = {"think": "  想 ", "http": "  调 ", "file": "  碰 ",
                      "tool": "  做 ", "result": "  得 "}[kind]
            print(prefix + text.replace("\n", "\n      "))
        print()


def main() -> int:
    ap = argparse.ArgumentParser(description="子代理动作审计：想什么 / 调什么 / 拿到什么")
    ap.add_argument("--list", action="store_true", help="列出所有子代理会话")
    ap.add_argument("--id", help="按 session id 前缀匹配")
    ap.add_argument("--label", help="按 label 模糊匹配（大小写不敏感）")
    ap.add_argument("--http", action="store_true", help="只看 HTTP 调用")
    ap.add_argument("--files", action="store_true", help="只看文件访问（含越界标记）")
    ap.add_argument("--thinking", action="store_true", help="只看 reasoning")
    ap.add_argument("--commands", action="store_true",
                    help="只列命令行原文 —— 正则抓不全所有调用形态时的兜底")
    ap.add_argument("--json", action="store_true", help="JSON 输出（完整，不截断）")
    ap.add_argument("--full", action="store_true", help="不截断长字段")
    ap.add_argument("--align", action="store_true",
                    help="与服务端审计对齐：把会话事件和服务端的**写操作**并成一条时间线")
    ap.add_argument("--agent", help="服务端审计里的 agent 名（默认从会话里自动推断）")
    ap.add_argument("--limit", type=int, default=200,
                    help="--align 模式下最多显示多少条（默认 200；--full 取消限制）")
    args = ap.parse_args()

    load_zstd()
    paths = all_sessions()
    if not paths:
        print(f"没找到会话文件（{SESSIONS_ROOT}）—— 参赛 AI 可能不是 DSH 子代理，"
              f"或者会话已被清理。", file=sys.stderr)
        return 2

    infos = [describe(p) for p in paths]

    if args.list:
        infos.sort(key=lambda i: (i["created"] or 0))
        print(f"{'created':20s} {'id':10s} {'depth':5s} {'label':32s} model")
        for i in infos:
            ts = ""
            if i["created"]:
                import datetime
                ts = datetime.datetime.fromtimestamp(i["created"] / 1000).strftime("%Y-%m-%d %H:%M:%S")
            print(f"{ts:20s} {i['id'][:8]:10s} {str(i['depth']):5s} "
                  f"{(i['label'] or '-')[:32]:32s} {i['model']}")
        print(f"\n共 {len(infos)} 个会话（{SESSIONS_ROOT}）")
        return 0

    # 选会话
    cands = infos
    if args.id:
        cands = [i for i in cands if i["id"].startswith(args.id)]
    if args.label:
        want = args.label.lower()
        cands = [i for i in cands if want in (i["label"] or "").lower()]
    if not cands:
        print("没匹配到会话。用 --list 看有哪些。", file=sys.stderr)
        return 2
    if len(cands) > 1 and not args.json:
        print(f"匹配到 {len(cands)} 个会话，取最近的一个（其余用 --id 精确指定）：")
        for i in cands:
            print(f"  {i['id'][:8]}  {i['label']}")
        print()

    target = max(cands, key=lambda i: i["created"] or 0)
    recs = read_session(target["path"])
    steps = walk(recs)

    if args.json:
        payload = {
            "session": {"id": target["id"], "label": target["label"],
                        "model": target["model"], "depth": target["depth"],
                        "path": str(target["path"])},
            "steps": [{"turn": k[0], "step": k[1],
                       "reasoning": st["reasoning"], "text": st["text"],
                       "calls": [{"name": c["name"],
                                  "http": extract_http(c),
                                  "files": extract_files(c),
                                  "forbidden": [f for f in extract_files(c) if is_forbidden(f)],
                                  "arguments": c.get("arguments")}
                                 for c in st["calls"]],
                       "results": st["results"]}
                      for k, st in steps],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.align:
        times = [st["time"] for _k, st in steps if st.get("time")]
        if not times:
            print("这个会话里没有带时刻的记录，无法对齐。", file=sys.stderr)
            return 2
        t0, t1 = min(times), max(times)
        agent = args.agent or guess_agent(steps)
        if not agent:
            print("推断不出这是哪个 agent —— 用 --agent <名字> 指定。", file=sys.stderr)
            return 2
        rows = load_server_audit(agent, t0, t1)
        print(f"# 会话 {target['id']}  「{target['label']}」")
        print(f"# 服务端审计 {AUDIT_PATH}")
        print(f"# agent = {agent}"
              + ("" if args.agent else "（从会话里自动推断；用 --agent 可覆盖）"))
        print(f"# 窗口 {_hhmmss(t0, full=True)} → {_hhmmss(t1, full=True)}（会话全程）")
        if not AUDIT_PATH.is_file():
            print("# ⚠ 审计文件不存在 —— 服务端那一侧会是空的")
        print(f"# 窗口内服务端写操作 {len(rows)} 条\n")
        align(steps, rows, args)
        return 0

    print(f"# 会话 {target['id']}  「{target['label']}」  {target['model']}"
          f"  depth={target['depth']}")
    print(f"# {target['path']}\n")
    render(steps, args)

    # 审计小结 —— 越界是这套东西最该一眼看出的结论
    bad = []
    via = {"exec": 0, "wrap": 0, "src": 0}
    think_n = 0
    for k, st in steps:
        think_n += len(st["reasoning"])
        for c in st["calls"]:
            for h in extract_http(c):
                via[h["via"]] = via.get(h["via"], 0) + 1
            for f in extract_files(c):
                if is_forbidden(f):
                    bad.append((k, f))
    print("─" * 72)
    print(f"reasoning 块 {think_n}")
    print(f"接口调用   exec={via['exec']}  wrap={via['wrap']}  src={via['src']}")
    print("  exec = 命令行里**实际执行**的 curl（最可靠）")
    print("  wrap = 走 skill/scripts/arena.py 客户端库（能看到「经封装」，看不到具体端点）")
    print("  src  = 写在自建脚本里的 `a.xxx()` —— **未必执行过**，但能看出它打算调什么")
    print(f"越界文件访问 {len(bad)}")
    if bad:
        print("\n⚠ 越界访问（任务书里是硬性禁止）：")
        for (t, s), f in bad:
            print(f"  [turn {t} step {s}] {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
