#!/usr/bin/env python3
"""把 A1/A2/A3/A4 写进文档。

API.md          /buildings 的物流字段、/queue 的 planList、错误码表
DESIGN.md       §6.1 错误码表加 1008/1009 与 409 映射
ENGINE-NOTES.md 新增一节：acceptItem 是瞬时判定，不能当结构事实用
"""
import pathlib
import sys

D = pathlib.Path(r"C:\dsh\ai-arena\docs")

API_BUILD_OLD = """| `rotation` | 朝向 0~3 |
| `items` | 该建筑库存 `{"物品名":数量}` |
| `liquids` | 液体库存 |
| `powered` | 是否有电（有电力接口的方块才有） |"""

API_BUILD_NEW = """| `rotation` | 朝向 0~3 |
| `items` | 该建筑库存 `{"物品名":数量}` |
| `liquids` | 液体库存 |
| `powered` | 是否有电（有电力接口的方块才有） |
| `acceptsFrom` | **能从哪几个邻格收货**（传送带专用），`[[x,y],...]` |
| `sendsTo` | **把货推到哪几格**，`[[x,y],...]` |

#### `acceptsFrom` / `sendsTo` —— 物流接口

这两个字段回答的是**接口在哪**，不是**这条链会不会堵**。

**`sendsTo`（所有建筑可能都有）**

- 传送带：正面那一格。**即使那是空地也会给** —— 那是它的朝向。
- 钻机：**挨着的所有建筑**。注意钻机输出**不受 `rotation` 控制**，
  它向所有相邻接收方推货，所以这个列表通常有多个。

**`acceptsFrom`（只有传送带有）**

按引擎的接货规则列出**背面 + 两侧**，正面（下游）是拒收的所以不列。
只列**该方位上真有建筑**的格，空地不列。

```
conveyor (282,109) rot=0   acceptsFrom=[[281,109]]         sendsTo=[[283,109]]
conveyor (283,109) rot=0   acceptsFrom=[[282,109]]         sendsTo=[[284,109]]
```

`rot=0` 面朝东，所以接货口在西侧（背面）—— 和读数一致。

> **为什么只列有建筑的那侧**：`acceptsFrom` 是**结构事实**，不随时间变。
> 别指望它告诉你「现在能不能收」—— 那取决于带子上挤不挤，
> 会来回抖，不适合放进快照。

**传送带的收货门槛不对称**（`Conveyor.java:358`）：背面宽松（`minitem >= 0.4`）、
两侧严格（`minitem > 0.7`）。**拐弯时货只能从侧面进，所以拐弯处特别容易堵** ——
这就是「图纸上对、实际堵死」的常见根因。

### `GET /units`"""

API_QUEUE_OLD = """### `GET /queue`

建造队列：每个建造单位正在排队的计划数
`{"builders":[{"unit":N,"plans":N}]}`。"""

API_QUEUE_NEW = """### `GET /queue`

建造队列：每个建造单位在排队的计划，**逐条带坐标**。

```json
{"builders":[{"unit":219,"type":"gamma","plans":49,"planList":[
  {"x":241,"y":66,"breaking":false,"block":"conveyor"},
  {"x":251,"y":152,"breaking":false,"block":"conveyor"}
]}]}
```

| `planList[]` 字段 | 含义 |
|---|---|
| `x` `y` | 目标格（锚点） |
| `block` | 目标方块 |
| `breaking` | `true` = 这是拆除计划 |
| `constructing` / `progress` | **只在该格已在施工时出现**：0 = 刚开工，长时间不涨就是卡住了 |

早期只给一个 `plans` 计数，AI 拿不到坐标 —— 想加速建造就得自己维护一份 pending
清单，而丢单会让清单和服务端实际状态对不上。有了 `planList` 才能精确定位卡住的计划。

`POST /queue?clear=true` 清空全队待办计划，返回清掉了几条。"""

API_ERR_OLD = """**失败响应的 body 与成功一样是这个 JSON**，HTTP 状态码只是给代理和日志看的粗分类
（`400` 参数、`403` 权限、`404` 找不到、`429` 限流、`504` 主线程超时）。
判失败要看 body 里的 `code`。用 `arena.py` 时 `ArenaError.code` 就是它，
`ArenaError.status` 才是 HTTP 状态码；两者都在，别只看后者。"""

API_ERR_NEW = """**失败响应的 body 与成功一样是这个 JSON**，HTTP 状态码只是给代理和日志看的粗分类。
判失败要看 body 里的 `code`。用 `arena.py` 时 `ArenaError.code` 就是它，
`ArenaError.status` 才是 HTTP 状态码；两者都在，别只看后者。

| `code` | HTTP | 含义 |
|---|---|---|
| `1001` | 400 | 参数错 |
| `1002` | 404 | 找不到（方块 / 建筑 / 端点是哪个就写哪个） |
| `1003` | 400 | 坐标越界 |
| `1004` | 429 | 队列满或批量超限 |
| `1005` | 403 | 只读 / 该队没有建造单位 / 单位生成被禁用 |
| `1006` | 410 | 事件游标过期 |
| `1007` | 504 | 主线程超时 |
| `1008` | **409** | **`/place` 的 footprint 被别的建筑或固体地形占住**（挪一格就行） |
| `1009` | 400 | `/place` 被引擎拒绝，非占用所致（地形 / 规则 / 权限） |
| `1401` | 401 | 鉴权失败 |
| `1403` | 403 | 权限不足（admin 专属端点、token 与 agent 不符） |
| `1500` | 500 | 服务端异常 |

**`1008` 与 `1009` 是分开的，别混**：前者挪一格或先 `/break` 就能成，
后者重试多少次都没用。响应里带 `conflictAt` 指向具体是哪一格挡着。"""

DESIGN_CODES_OLD = """1001 bad_request      1002 not_found         1003 out_of_bounds
1004 queue_full       1005 read_only         1006 cursor_expired
1007 op_expired       1401 unauthorized      1403 forbidden
1500 internal_error"""

DESIGN_CODES_NEW = """1001 bad_request      1002 not_found         1003 out_of_bounds
1004 queue_full       1005 read_only         1006 cursor_expired
1007 op_expired       1008 place_blocked     1009 place_invalid
1401 unauthorized     1403 forbidden         1500 internal_error

1008 -> HTTP 409（footprint 被占，挪一格即可）
1009 -> HTTP 400（引擎拒绝，重试无意义）"""

NOTES_APPEND = """

---

## 二十七、`acceptItem` 是**瞬时判定**，不能当结构事实用

`Building.acceptItem(source, item)`（`Building.java:577`，传送带覆写在
`Conveyor.java:352-358`）问的是「**此刻**这一格收不收下这个货」，判据是当前库存
与入口间距：

```java
// Conveyor.java:354, 358
if(len >= capacity) return false;                       // 自己身上满了
return (direction == 0    && minitem >= itemSpace)      // 背面：宽松
    || (direction % 2 == 1 && minitem >  0.7f);         // 两侧：严格
```

**踩到的坑**：给 `/buildings` 加「这台钻机往哪推货」时，我拿 `acceptItem` 逐个
邻格判定，结果读数来回抖：

```
钻机 (275,88) 旁边的带子 (275,90) 上堆着 2 个铜（货明明在流）
/buildings 却报钻机 sendsTo = null
```

那一刻带子入口被自己身上的货占住，`minitem <= 0.7`，侧面判定返回 false；
下一帧可能又变 true。**同一个事实，两次查询给出不同答案。**

**规矩**：

- 要「挨着谁」这类**结构事实**，直接看 `Vars.world.build(x, y) != null`；
- `acceptItem` 只适合回答「**现在**能不能塞进去」，而且答案会抖；
- 任何依赖 `len` / `minitem` / `items` / `efficiency` 的判定都不要放进快照字段 ——
  快照是给 AI 读的结构信息，抖动会让它据此做出错误决策。

**这是接口设计问题，不是引擎缺陷** —— `acceptItem` 本来就是为「这一刻要不要
把货递过去」设计的，用错了地方而已。
"""

JOBS = [
    (D / "API.md", [
        (API_BUILD_OLD, API_BUILD_NEW, "/buildings 的物流字段"),
        (API_QUEUE_OLD, API_QUEUE_NEW, "/queue 的 planList"),
        (API_ERR_OLD, API_ERR_NEW, "错误码表"),
    ]),
    (D / "DESIGN.md", [
        (DESIGN_CODES_OLD, DESIGN_CODES_NEW, "错误码表加 1008/1009"),
    ]),
]


def main():
    bad = []
    for path, rules in JOBS:
        text = path.read_text(encoding="utf-8")
        print(f"  {path.name}")
        for old, new, label in rules:
            n = text.count(old)
            if n != 1:
                bad.append(f"{path.name}: {n} 次命中 -> {label}")
                print(f"      !! {n} 次  {label}")
                continue
            text = text.replace(old, new)
            print(f"      1 处  {label}")
        path.write_text(text, encoding="utf-8")

    # ENGINE-NOTES 追加新节
    notes = D / "ENGINE-NOTES.md"
    t = notes.read_text(encoding="utf-8")
    if "二十七、" in t:
        print("  ENGINE-NOTES.md  已存在第二十七节，跳过")
    else:
        notes.write_text(t.rstrip() + NOTES_APPEND, encoding="utf-8")
        print("  ENGINE-NOTES.md  追加第二十七节")

    print()
    if bad:
        print("有问题：")
        for b in bad:
            print("  " + b)
        return 1
    print("文档已更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
