#!/usr/bin/env python3
"""把 SSE 记进 TODO 与 API.md。

**关键：标成「已实现（未运行时验证）」，不是「已完成」。**
本轮按要求没启游戏，所以只验证到编译通过；接口的实际行为没跑过。
把没跑过的说成完成，正是这个项目一直想避免的事。
"""
import pathlib
import sys

T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")
A = pathlib.Path(r"C:\dsh\ai-arena\docs\API.md")

TODO_OLD = "| SSE 推送 | DESIGN.md 41/731/853 三处写「SSE 推给观察者」 | 只交付了游标轮询（`?since=&limit=`），**SSE 没有任何实现** |"
TODO_NEW = ("| SSE 推送 | DESIGN.md 41/731/853 三处写「SSE 推给观察者」 | **已实现（未运行时验证）**："
            "`GET /v1/{agent}/stream?since=&limit=&seconds=`，与轮询共用同一套游标语义、"
            "复用 `Ev.toJson()`，带心跳与并发上限。**只验到编译通过** —— 本轮未启游戏，"
            "实际行为没跑过。 |")

API_SECTION = """

---

## SSE 事件推送

`GET /v1/{agent}/stream?since=<seq>&limit=<n>&seconds=<s>` → `text/event-stream`

DESIGN.md 三处承诺的东西。**与 `/events` 轮询共用同一套游标语义** ——
`since` / `nextSince` / `cursor_expired`（1006）完全一致，所以客户端从轮询
切过来不必改状态机。

为什么值得用：轮询要你自己定频率 —— 定高了烧限流配额（实测 700 次裸请求就
触发 1429，而且与写请求抢同一个令牌桶），定低了漏事件。SSE 让服务端按事件
发生推送。

事件类型：

| `event:` | 何时来 | `data:` |
|---|---|---|
| `hello` | 连上立刻 | `{"since":N,"agent":"beta"}` |
| `ev` | 每个新事件一条 | 与 `/events` 里 `events[]` 的元素**逐字节相同**（同一个 `toJson()`） |
| `cursor` | 每批之后 | `{"nextSince":N,"buffered":N}` |
| `error` | 游标过期 | `{"code":1006,"error":"cursor expired…resync with since=0"}` |
| `end` | 生存期到 | `{"reason":"lifetime reached","nextSince":N}` |
| `:hb` | 10 秒无事件 | ——（SSE 注释行，保活，不占序号） |

**约束**：

- `seconds` 有上限（600）且**到点主动收尾**——否则客户端不辞而别时线程会被永久占住
- 同时在流的连接数上限 **8**，超了回 `503 / 1007`。每个 SSE handler 占一个
  HTTP 线程，不设限等于给自己开了个拒绝服务的口子
- 游标过期时**不中断流**，只发一条 `error` 事件并把 `since` 重置为 0 继续

> **验证状态**：实现已编译进 mod，但**尚未在实机上跑过**。
> 按当前轮次的要求没有启动游戏，所以表格里的行为是按代码写的，
> 不是实测的。第一次实机验证前请把它当「待验」看。
"""


def main():
    ok = True

    t = T.read_text(encoding="utf-8")
    if t.count(TODO_OLD) == 1:
        T.write_text(t.replace(TODO_OLD, TODO_NEW, 1), encoding="utf-8")
        print("  ✓ TODO §2.2 SSE 行已更新")
    else:
        print(f"  !! TODO 锚点 {t.count(TODO_OLD)} 次")
        ok = False

    a = A.read_text(encoding="utf-8")
    if "## SSE 事件推送" in a:
        print("  · API.md 已有该节，跳过")
    else:
        A.write_text(a.rstrip() + API_SECTION, encoding="utf-8")
        print("  ✓ API.md 追加 SSE 一节")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
