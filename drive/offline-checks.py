#!/usr/bin/env python3
"""离线断言套件 —— 不起游戏、不起服务器，2 秒内跑完。

    python drive/offline-checks.py            跑全部（Java 断言 + 源码/文档一致性）
    python drive/offline-checks.py --src      只跑源码/文档一致性（不需要 JVM）
    python drive/offline-checks.py --quiet    只打印结论

两类断言：
  1. **纯逻辑断言**（Java，见 drive/checks/OfflineChecks.java）——
     直接调 aiarena 的真代码：JSON 转义、响应信封、审计判定、token、状态码映射。
  2. **源码/文档一致性断言**（Python）——
     把此前靠人手核对的东西变成可回归的检查：端点数量、错误码集合、
     DESIGN 的端点清单、jar 条目数。

为什么要有它（docs/TODO.md §3.5）：这个项目此前所有验证都要起服务器或游戏，
成本高 → 于是"下次再验" → 验证债越滚越大。而这两类断言**一次都不用起游戏**。

退出码：0 全过 / 1 有 FAIL。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JAVAC = Path(r"C:\dsh\zulu17\zulu17.68.203-ca-jdk17.0.20.1-win_x64\bin\javac.exe")
JAVA = Path(r"C:\dsh\zulu17\zulu17.68.203-ca-jdk17.0.20.1-win_x64\bin\java.exe")
MIND_JAR = Path(r"C:\dsh\Mindustry-src\desktop\build\libs\Mindustry.jar")
MOD_CLASSES = ROOT / "mod" / "classes"
MOD_JAR = ROOT / "mod" / "ai-arena.jar"
CHECK_SRC = ROOT / "drive" / "checks" / "OfflineChecks.java"
BUILD_DIR = ROOT / "_work" / "offline-classes"

# ---- 这几个数字一变就要同步：文档（DESIGN §6.1 / README / SKILL）。
#      收成常量，免得每次加端点都要在好几处改同样的数。----
EXPECTED_ACTIONS = 35        # route() 里 case 的个数（= /v1/<agent>/<action> 端点数）
EXPECTED_JAR_ITEMS = 49      # 1 mod.hjson + 1 MANIFEST.MF + 2 目录项 + 45 class
EXPECTED_CLASSES = 45

results: list[tuple[str, str, str]] = []   # (name, status, detail)


def rec(name: str, status: str, detail: str = "") -> None:
    results.append((name, status, detail))


def eq(name: str, actual, expect) -> None:
    if actual == expect:
        rec(name, "PASS")
    else:
        rec(name, "FAIL", f"actual={actual!r} expect={expect!r}")


def ok(name: str, cond: bool, detail: str = "") -> None:
    rec(name, "PASS" if cond else "FAIL", "" if cond else detail)


# ----------------------------------------------------------------- java 断言

def java_checks() -> None:
    if not JAVAC.exists() or not JAVA.exists():
        rec("Java 断言", "SKIP", "找不到 JDK：改脚本顶部的 JAVAC / JAVA 路径")
        return
    if not MIND_JAR.exists() or not MOD_CLASSES.is_dir():
        rec("Java 断言", "SKIP", f"缺 {MIND_JAR} 或 {MOD_CLASSES}（先按 DEVELOPING §二 编译一次）")
        return

    cp = f"{MIND_JAR}{';'}{MOD_CLASSES}"
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    for old in BUILD_DIR.glob("*.class"):
        old.unlink()

    c = subprocess.run([str(JAVAC), "-encoding", "UTF-8", "-cp", cp,
                        "-d", str(BUILD_DIR), str(CHECK_SRC)],
                       capture_output=True, text=True, errors="replace")
    if c.returncode != 0:
        rec("Java 断言编译", "FAIL", (c.stderr or c.stdout).strip()[:300])
        return
    rec("Java 断言编译", "PASS")

    r = subprocess.run([str(JAVA), "-cp", f"{BUILD_DIR}{';'}{cp}", "OfflineChecks"],
                       capture_output=True, text=True, errors="replace")
    parsed = 0
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        rec(d.get("name", "?"), d.get("status", "?"), d.get("detail", ""))
        parsed += 1
    if parsed == 0:
        rec("Java 断言输出", "FAIL", (r.stderr or r.stdout).strip()[:300])


# --------------------------------------------------- 源码 / 文档一致性断言

def route_actions(src: str) -> list[str]:
    """只抓 route() 的 switch —— 那些 case 形如 `case "x" -> handleY(ex, agent);`。
    文件里还有别的 switch（handleCommand / handleControl），它们的 case 指向别处。"""
    return re.findall(r'case\s+"(\w+)"\s*->\s*handle\w+\(', src)


def source_checks() -> None:
    http = (ROOT / "mod" / "src" / "aiarena" / "HttpApi.java").read_text(encoding="utf-8")
    api_md = (ROOT / "docs" / "API.md").read_text(encoding="utf-8")
    design = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")

    # --- 端点数量与清单一致 ---
    actions = route_actions(http)
    eq(f"route 的 action 数量（应为 {EXPECTED_ACTIONS}）", len(actions), EXPECTED_ACTIONS)
    eq("action 无重复", len(set(actions)), len(actions))

    # 裁判段写的是 /v1/{referee}/…，不是 {agentId} —— 两种都要抓
    design_actions = set(re.findall(r"/v1/\{(?:agentId|referee)\}/(\w+)", design))
    got = set(actions)
    ok("DESIGN §6.1 的清单与源码一致",
       design_actions == got,
       f"只在源码: {sorted(got - design_actions)} / 只在文档: {sorted(design_actions - got)}")

    # --- 错误码集合 ---
    src_codes = set(int(m) for m in re.findall(r"Json\.error\((\d{4})", http))
    doc_codes = set(int(m) for m in re.findall(r"^\|\s*`(\d{4})`\s*\|", api_md, re.M))
    # 1008 / 1009 由 Actor 的 r.code 透传，不以字面量出现在 HttpApi 里 —— 这是预期差异
    expected_extra = {1008, 1009}
    ok("API.md 的错误码表覆盖源码用到的码",
       src_codes <= doc_codes,
       f"表里缺: {sorted(src_codes - doc_codes)}")
    ok("表比源码多出的码就是 1008/1009（透传码）",
       (doc_codes - src_codes) == expected_extra,
       f"意外差异: {sorted((doc_codes - src_codes) - expected_extra)}")

    # --- statusFor 未映射的码，靠调用点硬编码状态 ---
    ok("statusFor 不含 1401/1500（它们由调用点硬编码 401/500）",
       not re.search(r"case\s+1401|case\s+1500", http),
       "若哪天加进 statusFor，请同步这条断言与文档说明")

    # --- shape 取值 ---
    # 这条错误消息在源码里是跨行的，所以用 re.S 且限长，避免跨到别处
    m = re.search(r"unknown shape:.{0,200}?\(([a-z|]+)\)", http, re.S)
    if m:
        shapes = set(m.group(1).split("|"))
        eq("shape 取值个数", len(shapes), 7)
        rec("shape 取值清单", "PASS" if shapes == {
            "point", "line", "rect", "area", "outline", "circle", "path"} else "FAIL",
            f"实际: {sorted(shapes)}")
    else:
        rec("shape 取值", "SKIP", "没在源码里找到那条错误消息")

    # --- jar 条目数 ---
    if MOD_JAR.exists():
        jar_exe = JAVAC.parent / "jar.exe"
        if jar_exe.exists():
            t = subprocess.run([str(jar_exe), "tf", str(MOD_JAR)],
                               capture_output=True, text=True, errors="replace")
            items = [x for x in t.stdout.splitlines() if x.strip()]
            eq(f"jar 条目数（应为 {EXPECTED_JAR_ITEMS}）", len(items), EXPECTED_JAR_ITEMS)
            eq(f"jar 里的 class 数（应为 {EXPECTED_CLASSES}）",
               len([x for x in items if x.endswith(".class")]), EXPECTED_CLASSES)
        else:
            rec("jar 条目数", "SKIP", "找不到 jar.exe")
    else:
        rec("jar 条目数", "SKIP", "mod/ai-arena.jar 不存在（尚未打包）")


def main() -> int:
    ap = argparse.ArgumentParser(description="离线断言套件")
    ap.add_argument("--src", action="store_true", help="只跑源码/文档一致性断言")
    ap.add_argument("--quiet", action="store_true", help="只打印结论")
    args = ap.parse_args()

    if not args.src:
        java_checks()
    source_checks()

    npass = sum(1 for _, s, _ in results if s == "PASS")
    nfail = sum(1 for _, s, _ in results if s == "FAIL")
    nskip = sum(1 for _, s, _ in results if s == "SKIP")

    if not args.quiet:
        for name, status, detail in results:
            if status == "PASS":
                print(f"  ✓ {name}")
            elif status == "SKIP":
                print(f"  – {name}  [{detail}]")
            else:
                print(f"  ✗ {name}  {detail}")
        print()

    print(f"离线断言：{len(results)} 项 —— PASS {npass} / FAIL {nfail} / SKIP {nskip}")
    if nfail:
        print("（全部都不需要起游戏；FAIL 请看上面的明细）")
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
