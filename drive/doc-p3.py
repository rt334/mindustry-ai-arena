#!/usr/bin/env python3
"""补3 + B4 的文档收尾。

补3：/queue 的 stuckSeconds
B4：/events 的增量用法 —— 实测已能满足「只返回变化」，不需要新端点
"""
import pathlib
import sys

P = pathlib.Path(r"C:\dsh\ai-arena\docs\API.md")

QUEUE_OLD = """| `constructing` / `progress` | **只在该格已在施工时出现**：0 = 刚开工，长时间不涨就是卡住了 |"""

QUEUE_NEW = """| `constructing` / `progress` | **只在该格已在施工时出现**：施工进度 0~1 |
| `stuckSeconds` / `hint` | **只在真的卡住时出现**，见下 |

#### `stuckSeconds`：卡住的计划

```json
{"x":314,"y":79,"block":"conveyor","stuckSeconds":12,
 "hint":"move the builder to the site to break it loose: /control?op=order&unit=219&x=314&y=79"}
```

判据是**进度连续不变、且建造单位自己也不动**，持续超过 3 秒。

> **为什么还要看单位动没动**：`BuilderComp` 只在目标格变成施工中之后才把施工进度
> 写回计划 —— 单位还在赶路的这段时间里进度恒为 0，**不变，但不是卡住**。
> 只看进度会把「离得远、还在走过去」误报成停滞。真人判断卡住看的也正是这两件事：
> 方块不出现、单位也站着不动。

`hint` 直接给出验证过的解法：**队列卡死时用移动命令把它推开**
（`/control?op=order` 收格坐标），实测 `plans` 一次从 56 降到 1，沿线方块真的建成。
`/break` 对排队中的计划**无效**，反而会追加拆除计划。"""

EVENTS_OLD = """### `GET /events`

事件流。"""

EVENTS_NEW = """### `GET /events`

事件流，**游标增量**：`?since=<seq>` 只返回该游标之后的事件，响应里带 `nextSince`。

| 字段 | 含义 |
|---|---|
| `since` / `nextSince` | 本次起点 / 下次该传的值 |
| `count` / `buffered` | 本次条数 / 缓冲区里还有多少 |
| `events[]` | `{seq, tick, type, team, x, y, detail}` |

#### 用它替代全量拉 `/buildings`

**想知道「自上次以来产线变了什么」，不用重拉 250+ 条建筑再自己 diff。**
`/events` 的差分补齐覆盖了这几类：

| 事件 | 触发 |
|---|---|
| `buildAppear` / `buildGone` | 方块建好 / 被拆 |
| `unitAppear` / `unitGone` | 单位出现 / 消失 |
| `configure` | 方块配置改变 |
| `blockPlace` | 下单成功 |

实测建 5 个 conveyor，增量只拿到 5 条 `buildAppear`（各带 `detail.{x,y,block}`），
而不是全量那份建筑表：

```
{"seq":8,"tick":373,"type":"buildAppear","team":2,"x":2184.0,"y":632.0,
 "detail":{"x":273,"y":79,"block":"conveyor"}}
```

**推荐用法**：开局拉一次 `/buildings` 建基线，之后用 `/events?since=<nextSince>`
维护增量。方块只存增量这一条对客户端同样适用 —— 多数方块长期不变。"""

RULES = [
    (QUEUE_OLD, QUEUE_NEW, "/queue 的 stuckSeconds"),
    (EVENTS_OLD, EVENTS_NEW, "/events 的增量用法（B4）"),
]


def main():
    text = P.read_text(encoding="utf-8")
    bad = []
    for old, new, label in RULES:
        n = text.count(old)
        if n != 1:
            bad.append(f"{n} 次命中: {label}")
            print(f"  !! {n} 次  {label}")
            continue
        text = text.replace(old, new)
        print(f"  1 处  {label}")
    if bad:
        print("\n有问题，未写盘")
        return 1
    P.write_text(text, encoding="utf-8")
    print("\nAPI.md 已更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
