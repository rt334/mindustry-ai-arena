#!/usr/bin/env python3
"""死参数扫描 —— 找出「读进来但从未使用」的请求参数。

    python drive/check-dead-params.py             扫描 HttpApi.java
    python drive/check-dead-params.py --verbose   连「用了几次」也打出来
    python drive/check-dead-params.py --selftest  自证规则有效（拿内嵌样本验）

为什么要有它（`docs/TODO.md` §十一）：`/database` 曾经有 `block=` 与 `type=` 两个参数，
在方法开头读入后**从未使用** —— 传了会静默落到别的分支，而它的 `usage` 文案
还宣称支持 `block=`。这类参数**不报错、不告警、返回值也正常**，只在**语义上骗人**，
所以只能靠扫。而 AI 会把 `usage` 文案当真，错文案比没文案更糟。

判定：某个 `handleXxx` 方法里 `T name = p.get*("key", ...)` 绑定的变量，
在整个方法体内**只出现过一次**（就是声明那一次）⇒ 它是死参数。

局限（说清楚免得被当成万能的）：
  · 大括号配对不跳过字符串与注释里的花括号 —— 若方法体里有含 `{`/`}` 的字面量，
    切分可能不准。本文件当前没有这种情况。
  · 变量名若恰好出现在字符串里，也会被算作「用了」——保守方向，只可能漏报不会误报。

退出码：0 无死参数 / 1 有。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "mod" / "src" / "aiarena" / "HttpApi.java"

# 方法头：private static void handleXxx(...) {
METHOD = re.compile(r"\bprivate\s+static\s+void\s+(handle\w+)\s*\([^)]*\)\s*\{")

# 参数绑定：String x = p.get("key", ...) / int n = p.getInt("limit", 60) ...
BIND = re.compile(
    r"\b(?:String|int|long|float|double|boolean)\s+(\w+)\s*=\s*"
    r"p\.get(?:Int|Float|Long|Bool|Str)?\s*\(\s*\"(\w+)\""
)

SELFTEST = '''
private static void handleFake(HttpExchange ex, AIArena.Agent agent) {
    Params p = Params.of(ex);
    String usedVar = p.get("used", null);
    String deadVar = p.get("dead", null);
    int limVar = p.getInt("limit", 60);
    if (usedVar != null) respond(ex, 200, Json.ok(usedVar));
    respond(ex, 200, Json.ok(new Json.Obj().put("n", limVar).toString()));
}
'''


def method_body(text: str, brace: int) -> tuple[int, int]:
    """brace 指向方法体的 '{'；返回 (体起点, 体终点)。"""
    depth = 0
    i = brace
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return brace + 1, i
        i += 1
    return brace + 1, len(text)


def scan(text: str) -> list[tuple[str, str, str, int, int]]:
    """返回 [(方法名, 参数名, 变量名, 行号, 出现次数)]。"""
    out = []
    for m in METHOD.finditer(text):
        mname = m.group(1)
        a, b = method_body(text, m.end() - 1)
        body = text[a:b]
        for bm in BIND.finditer(body):
            var, key = bm.group(1), bm.group(2)
            uses = len(re.findall(r"\b" + re.escape(var) + r"\b", body))
            if uses <= 1:
                line = text.count("\n", 0, a + bm.start()) + 1
                out.append((mname, key, var, line, uses))
    return out


def selftest() -> int:
    """拿内嵌样本验规则：`usedVar` 与 `limVar` 该放过，`deadVar` 该抓到。

    样本里**变量名刻意与参数 key 不同** —— 第一版两者都叫 `dead`，
    结果 key 字符串里的 `dead` 被算成「用过一次」，自测红了一次。
    这正是本文件顶上标注的那条局限，所以样本得避开它。
    """
    hits = {h[2] for h in scan(SELFTEST)}
    cases = [("deadVar", True), ("usedVar", False), ("limVar", False)]
    bad = 0
    print("自测：逐条验样本里哪个该抓、哪些该放过\n")
    for var, should_hit in cases:
        got = var in hits
        ok = got == should_hit
        print(f"  {'✓' if ok else '✗'} {var:<6} 期望命中={should_hit}  实际={got}")
        if not ok:
            bad += 1
    print()
    if bad:
        print("自测失败 —— 规则有问题")
        return 1
    print("自测通过 ✓")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="死参数扫描")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if not SRC.exists():
        print(f"找不到 {SRC}", file=sys.stderr)
        return 1

    text = SRC.read_text(encoding="utf-8")
    dead = scan(text)
    nmethods = len(METHOD.findall(text))

    print(f"扫描 {SRC.relative_to(ROOT).as_posix()}：{nmethods} 个 handle* 方法")
    if args.verbose:
        for m in METHOD.finditer(text):
            a, b = method_body(text, m.end() - 1)
            binds = [x.group(1) for x in BIND.finditer(text[a:b])]
            print(f"  {m.group(1):<26} 参数 {len(binds)} 个")
        print()

    if not dead:
        print("死参数：0 —— 每个读入的参数都在方法体里被用到了 ✓")
        return 0

    print(f"死参数 {len(dead)} 个：")
    for mname, key, var, line, uses in dead:
        print(f"  ✗ {mname}  \"{key}\" -> 变量 {var}"
              f"（L{line}，方法体内只出现 {uses} 次 = 只有声明那次）")
    print("\n（要么删掉它，要么真的实现它；别留着 —— 它会让 AI 以为这个参数有用）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
