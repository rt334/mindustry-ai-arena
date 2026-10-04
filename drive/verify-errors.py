#!/usr/bin/env python3
"""验证错误路径：HTTP 状态码与 body 里的 code 都要能拿到。

修复前 `HTTPError` 的 body 被丢掉，非 admin 调 /diag 只会看到
`[403] HTTP 403`，真正的原因 "diag requires an admin token" 消失。
"""
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()


def probe(agent, path, **params):
    a = Arena(agent, toks[agent])
    try:
        return f"OK   {path:<10} -> {str(a.get(path, **params))[:80]}"
    except ArenaError as e:
        return (f"ERR  {path:<10} code={e.code:<6} status={e.status!s:<5} "
                f"msg={e.message!r}")


print("== 非 admin 调 admin 端点 ==")
for p in ("diag", "record", "fog", "admin", "host"):
    print("  " + probe("beta", p))

print("== admin 调同样端点 ==")
for p in ("diag", "record", "fog"):
    print("  " + probe("referee", p))

print("== 正常路径不受影响 ==")
for p in ("state", "buildings", "units", "content"):
    print("  " + probe("beta", p))

print("== 原始 body 是否保留 ==")
try:
    Arena("beta", toks["beta"]).get("diag")
except ArenaError as e:
    print(f"  body = {e.body!r}")
