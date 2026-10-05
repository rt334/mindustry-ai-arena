#!/usr/bin/env python3
"""ai-arena 上手入口。不需要记 `start-arena.ps1 -Agents 2 -Map veins -KeepRunning`。

    python start.py            菜单
    python start.py check      只做前置检查
    python start.py play       起局（服务端 + AI）
    python start.py watch      起局 + 观战端
    python start.py replay     看回放（打开 replay/index.html）
    python start.py status     查当前局面
    python start.py stop       停掉所有 java

设计取向：**报告事实，不猜。** 每一项都说清「它检查了什么、结果是什么」，
而不是笼统一句「环境正常」。缺什么就直说缺什么、去哪装。
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JDK = Path(r"C:\dsh\zulu17\zulu17.68.203-ca-jdk17.0.20.1-win_x64")
JAR = Path(r"C:\dsh\Mindustry-src\desktop\build\libs\Mindustry.jar")
MOD_DST = ROOT / "server-run" / "config" / "mods" / "ai-arena.jar"
CONFIG = ROOT / "server-run" / "config" / "ai-arena.json"
REPLAY = ROOT / "replay" / "index.html"
TOKENS = Path.home() / ".ai-arena" / "tokens.json"


def ok(s):
    return f"  [OK]   {s}"


def bad(s):
    return f"  [缺]   {s}"


def info(s):
    return f"  --     {s}"


def check(verbose=True):
    """返回 (是否具备起局条件, 报告行列表)。"""
    lines, ready = [], True

    jc = JDK / "bin" / "java.exe"
    if jc.exists():
        try:
            v = subprocess.run([str(jc), "-version"], capture_output=True,
                               text=True, timeout=20).stderr.splitlines()[0]
        except Exception as e:
            v = f"运行失败: {e}"
        lines.append(ok(f"JDK  {jc}  ({v.strip()[:48]})"))
    else:
        lines.append(bad(f"JDK  {jc}"))
        ready = False

    if JAR.exists():
        lines.append(ok(f"客户端 jar  {JAR}  ({JAR.stat().st_size // 1024 // 1024} MB)"))
    else:
        lines.append(bad(f"客户端 jar  {JAR}"))
        ready = False

    if MOD_DST.exists():
        lines.append(ok(f"mod  {MOD_DST}  ({MOD_DST.stat().st_size // 1024} KB)"))
    else:
        lines.append(bad(f"mod  {MOD_DST}  —— 需先编译（见 docs/DEVELOPING.md）"))
        ready = False

    if CONFIG.exists():
        try:
            cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
            ags = cfg.get("agents") or []
            lines.append(ok(f"agent 配置  {len(ags)} 个: "
                            + ", ".join(a.get("id", "?") for a in ags)))
        except Exception as e:
            lines.append(bad(f"agent 配置解析失败: {e}"))
            ready = False
    else:
        lines.append(bad(f"agent 配置  {CONFIG}"))
        ready = False

    if REPLAY.exists():
        lines.append(ok(f"回放页  {REPLAY}  （单文件，双击即用，不需要任何服务端）"))
    else:
        lines.append(bad(f"回放页  {REPLAY}"))

    if TOKENS.exists():
        lines.append(ok(f"agent token  {TOKENS}"))
    else:
        lines.append(info(f"agent token  {TOKENS} 不存在 —— 起局后第一次连会自动写"))

    return ready, lines


def running():
    """返回正在监听的 7199/7200 占用者（没有就是空表）。"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |"
             " Where-Object { $_.LocalPort -in 7199,7200 } |"
             " Select-Object -ExpandProperty LocalPort"],
            capture_output=True, text=True, timeout=30).stdout
        return sorted({int(x) for x in out.split() if x.strip().isdigit()})
    except Exception:
        return []


def java_count():
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "(Get-Process -Name java -ErrorAction SilentlyContinue |"
                              " Measure-Object).Count"],
                             capture_output=True, text=True, timeout=30).stdout
        return int(out.strip() or 0)
    except Exception:
        return -1


def cmd_check(_):
    ready, lines = check()
    print("\n".join(lines))
    ports = running()
    print(info(f"端口 7199/7200: " + ("空闲" if not ports else f"被占 {ports}")))
    print(info(f"java 进程: {java_count()}"))
    print()
    print("  可以起局" if ready else "  **还差东西**，先补上面标 [缺] 的")
    return 0 if ready else 1


def cmd_status(_):
    ports = running()
    print(info(f"端口: " + ("空闲" if not ports else f"被占 {ports}")))
    print(info(f"java 进程: {java_count()}"))
    if 7199 not in ports:
        print(info("服务端没在跑 —— 用 `python start.py play`"))
        return 0
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:7199/ping", timeout=5) as r:
            d = json.loads(r.read().decode("utf-8")).get("data") or {}
        print(ok(f"服务端在线  tick={d.get('tick')}  agents={d.get('agents')}"
                 f"  apiVersion={d.get('apiVersion')}"))
    except Exception as e:
        print(bad(f"7199 被占但 /ping 不通: {e}"))
    return 0


def cmd_play(args):
    ready, lines = check()
    print("\n".join(lines))
    if not ready:
        print("\n  **还差东西**，先补上面标 [缺] 的")
        return 1
    if 7199 in running():
        print(bad("7199 已被占 —— 先 `python start.py stop`"))
        return 1
    script = ROOT / "start-arena.ps1"
    cmd = ["powershell", "-NoProfile", "-File", str(script),
           "-Agents", str(args.agents), "-Map", args.map, "-KeepRunning"]
    print(info("起局: " + " ".join(cmd[3:])))
    subprocess.Popen(cmd, cwd=str(ROOT))
    print(info("已在后台启动。等约 30 秒后 `python start.py status` 查"))
    return 0


def cmd_watch(args):
    r = cmd_play(args)
    if r != 0:
        return r
    jc = JDK / "bin" / "java.exe"
    print(info("起观战端（必须用自建 jar，并且两个 -D 参数都不是可选项）"))
    subprocess.Popen([str(jc), "-Xmx2G",
                      "-Djava.net.preferIPv4Stack=true",
                      "-Dmindustry.autoreconnect=true",
                      "-jar", str(JAR)], cwd=str(ROOT))
    return 0


def cmd_replay(_):
    if not REPLAY.exists():
        print(bad(f"找不到 {REPLAY}"))
        return 1
    print(info(f"回放页是单文件、零依赖 —— 只是拖个 .jsonl 进去，不需要服务端"))
    webbrowser.open(REPLAY.as_uri())
    print(ok(f"已在浏览器打开 {REPLAY}"))
    return 0


def cmd_stop(_):
    n = java_count()
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-Process -Name java -ErrorAction SilentlyContinue |"
                    " ForEach-Object { Stop-Process -Id $_.Id -Force }"],
                   capture_output=True, text=True, timeout=60)
    ports = running()
    print(info(f"停掉 {n} 个 java；端口 " + ("已释放" if not ports else f"仍占 {ports}")))
    return 0


MENU = """
ai-arena

  1  起局（服务端 + AI）
  2  起局 + 观战端
  3  看回放（拖个 .jsonl 进去）
  4  查当前局面
  5  停掉所有 java
  6  只做前置检查
  q  退出
"""


def menu():
    while True:
        print(MENU)
        try:
            c = input("选: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if c == "q":
            return 0
        if c == "1":
            cmd_play(argparse.Namespace(agents=2, map="veins"))
        elif c == "2":
            cmd_watch(argparse.Namespace(agents=2, map="veins"))
        elif c == "3":
            cmd_replay(None)
        elif c == "4":
            cmd_status(None)
        elif c == "5":
            cmd_stop(None)
        elif c == "6":
            cmd_check(None)
        else:
            print(info("没这个选项"))


def main():
    ap = argparse.ArgumentParser(description="ai-arena 上手入口")
    sub = ap.add_subparsers(dest="cmd")
    for name, fn, helptext in (
        ("check", cmd_check, "只做前置检查"),
        ("status", cmd_status, "查当前局面"),
        ("replay", cmd_replay, "打开回放页"),
        ("stop", cmd_stop, "停掉所有 java"),
    ):
        p = sub.add_parser(name, help=helptext)
        p.set_defaults(fn=fn)
    for name, fn, helptext in (
        ("play", cmd_play, "起局"),
        ("watch", cmd_watch, "起局 + 观战端"),
    ):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("-Agents", "--agents", type=int, default=2)
        p.add_argument("-Map", "--map", default="veins")
        p.set_defaults(fn=fn)
    args = ap.parse_args()
    if args.cmd:
        return args.fn(args)
    return menu()


if __name__ == "__main__":
    sys.exit(main())
