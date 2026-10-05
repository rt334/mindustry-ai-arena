#!/usr/bin/env python3
"""接口版本号约定 —— §四 第三条。

TODO 说「跨版本的对局成绩不可比，但没有版本号可标」。核实过：**代码里
一个版本字符串都没有**（grep VERSION/version 在 aiarena 包下只命中
jsonl 的 format 字段），所以这条是真缺口。

做法尽量轻：
  · 在 AIArena 放一个常量
  · 挂在 `/ping` 上 —— 它无鉴权、最容易被探测到，是「这个服务端是哪个版本」
    的自然落点；端口发现文件里也带一份
  · 约定写进 API.md：什么算破坏性、成绩该怎么标

不引入 /version 这种新端点 —— 多一个端点就多一处要维护的契约，
而 /ping 本来就回答「你连的是什么」。
"""
import pathlib
import sys

MOD = pathlib.Path(r"C:\dsh\ai-arena\mod\src\aiarena")
ARENA = MOD / "AIArena.java"
API = MOD / "HttpApi.java"

RULES = [
    (ARENA,
     "    public static int port = 7199;",
     """    public static int port = 7199;

    /**
     * 接口版本号。**跨版本的对局成绩不可比** —— 成绩记录必须带上它。
     *
     * 约定（详见 docs/API.md）：
     *   major  +1  破坏性：删字段、改字段语义、改默认行为
     *   minor  +1  增量：只加字段 / 只加端点，老客户端仍然能用
     *
     * 之所以要它：这个接口改过不少次（`stuckReason`、批量的 requested/accepted、
     * `/queue` 的 cleared、`/drill` 的 itemsPerSecond、SSE、蓝图……），
     * 而 `reviews/` 里几批数据是不同时期跑的。没有版本号，
     * 「这局 AI 是 3.2/s 那局 AI 是 2.1/s」根本说不清是不是同一个接口。
     */
    public static final String API_VERSION = "1.4";"""),

    (API,
     '            .put("headless", Vars.headless)',
     '            .put("headless", Vars.headless)\n'
     '            .put("apiVersion", AIArena.API_VERSION)'),

    (ARENA,
     '                    .put("agent", ag.id)\n'
     '                    .put("httpPort", port)',
     '                    .put("agent", ag.id)\n'
     '                    .put("apiVersion", API_VERSION)\n'
     '                    .put("httpPort", port)'),
]


def main():
    texts = {p: p.read_text(encoding="utf-8") for p in (ARENA, API)}
    ok = True
    for path, old, new in RULES:
        t = texts[path]
        n = t.count(old)
        if n != 1:
            print(f"  !! {path.name}: {n} 次  «{old.strip()[:44]}»")
            ok = False
            continue
        texts[path] = t.replace(old, new, 1)
        print(f"  ✓ {path.name}: «{old.strip()[:44]}»")
    if not ok:
        print("未写盘")
        return 1
    for p, t in texts.items():
        p.write_text(t, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
