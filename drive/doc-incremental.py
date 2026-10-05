#!/usr/bin/env python3
"""条目 5「没有增量查询接口」——先想清楚要的能力是不是已经有了。

结论：**已经有了，只是没有专门的端点。** EventLog 里有
blockPlace / blockBreak / blockDestroy，而 `/events?since=` 已经能增量拉、
按视野过滤。所以「我上次看过之后建筑变了什么」用它就能答。

再加一个 `/buildings?since=` 只会多一个要维护的契约，而且它和事件流
说的必须是同一件事（否则两边会漂移）—— 这正是我做 SSE 时刻意复用
Ev.toJson() 的同一个理由。

所以本项的正确动作是**补文档**，不是加端点。
"""
import pathlib
import sys

A = pathlib.Path(r"C:\dsh\ai-arena\docs\API.md")
T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")

API_SECTION = """

---

## 增量查询：不要重拉全量建筑

**`/buildings` 没有 `since=` 参数，也不需要。** 要「我上次看过之后变了什么」，
用事件流：

```
GET /v1/{agent}/events?since=<上次的 nextSince>&limit=256
```

只看建筑相关的事件类型：

| `type` | 含义 |
|---|---|
| `blockPlace` | 有方块建成 |
| `blockBreak` | 有方块开始被拆 |
| `blockDestroy` | 有方块真的没了 |
| `buildingSpotted` / `buildingLost` | 视野进入 / 离开（**那不是建筑变了，是你看见了**） |

`nextSince` 拿回来存着，下次接着用。这就是增量 —— 不需要为它单开一个端点。

**为什么刻意不另开 `/buildings?since=`**：那会多出一个要维护的契约，
而且它和事件流回答的必须是同一件事。两份「谁变了」的表达迟早会漂移
（同一理由见「SSE 事件推送」那节：直接复用 `Ev.toJson()`，不另写序列化）。

**注意区分两类事件**：`blockPlace` 是**世界变了**，
`buildingSpotted` 是**你看得见了**（比如你推进视野、或对方在雾里建的东西
终于进视野）。只有前者能用来重建自己的建筑台账。

> 首次调用传 `since=0`；游标过期会回 `1006`，此时重置 `since=0` 重新同步。
"""

TODO_OLD = "| 5 | 没有增量查询接口 | **确实没做**（`grep` 增量/since 类端点，0 命中）。每步改动都要重拉全量 `/buildings`（后期 250+ 条）对比。 |"
TODO_NEW = ("| 5 | 没有增量查询接口 | **能力已有，只是没有专门端点**。`/events?since=` 增量拉、按视野过滤，"
            "过滤出 `blockPlace` / `blockBreak` / `blockDestroy` 就是建筑增量的全部。"
            "**刻意不另开 `/buildings?since=`**：多一个契约，而且它和事件流回答的必须是同一件事，"
            "两份表达迟早漂移。已写进 `API.md`「增量查询」一节，并点明"
            "`blockPlace`（世界变了）与 `buildingSpotted`（你看得见了）是两类事。 |")


def main():
    a = A.read_text(encoding="utf-8")
    if "## 增量查询" in a:
        print("  · API.md 已有该节")
    else:
        A.write_text(a.rstrip() + API_SECTION, encoding="utf-8")
        print("  ✓ API.md 追加「增量查询」")

    t = T.read_text(encoding="utf-8")
    if t.count(TODO_OLD) == 1:
        T.write_text(t.replace(TODO_OLD, TODO_NEW, 1), encoding="utf-8")
        print("  ✓ §7.8 条目 5 已更新")
    else:
        print(f"  !! 条目5 锚点 {t.count(TODO_OLD)} 次")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
