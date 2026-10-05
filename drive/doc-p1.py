#!/usr/bin/env python3
"""P1 批次的文档与客户端库收尾。

- API.md：/place 的 shape=path、/place 的 config 回显、/units 的 buildingAt、
           /stalls 的 cause
- arena.py：place_path() 封装 —— post(path, **params) 的首参名就叫 path，
            直接 post("place", path=...) 会撞车
"""
import pathlib
import sys

D = pathlib.Path(r"C:\dsh\ai-arena\docs")
ARENA = pathlib.Path(r"C:\dsh\ai-arena\skill\scripts\arena.py")

API_UNIT_OLD = """默认由**当前接管的单位**执行（`/control?op=enter&unit=<id>` 之后就是它），没有则任选一个可建造单位。
传 `unit=<id>` 可显式指定。响应里的 `builder` 字段回显实际用了谁。"""

API_UNIT_NEW = """默认由**当前接管的单位**执行（`/control?op=enter&unit=<id>` 之后就是它），没有则任选一个可建造单位。
传 `unit=<id>` 可显式指定。响应里的 `builder` 字段回显实际用了谁。

### `/place` 的 `config`：随建造一起设

**`config` 会跟着建造计划走**，方块一建好就是配好的，不用再发一次 `/config`。

```json
{"config":"item=coal","message":"queued sorter at (281,78) by gamma; pending plans=1"}
```

`config` 的值按**方块声明的配置类型**解析：物品名 → `Item`、单位名 → `UnitType`、
方块名 → `Block`、纯数字 → `Integer`。

> **传字符串不会自动生效，必须能被解析出来。** 引擎按值的 `getClass()` 查方块的
> `configurations` 表，匹配不上就**静默失效** —— 方块建出来了，但配置是空的。
> 所以响应里会回显解析结果（`item=coal` 这种）。**解析不出来时会额外给
> `configWarning`**，明确告诉你这个配置不会生效，而不是等建完了才发现。

### `/place` 的 `shape=path`：折线布线

真实布线必然拐弯，而拐弯处每格朝向不同 —— 其它形状「所有格同一 `rot`」的设计
正好卡在最需要的地方。`shape=path` 收折线点列，**每一格的朝向由服务端按走向算**：

```
POST /place?shape=path&path=273,78;278,78;278,82&block=conveyor
```

```json
{"shape":"path","tiles":10,
 "rotations":[[273,78,0],[274,78,0],...,[278,78,1],[278,79,1],...]}
```

`rotations` 是 `[x, y, rot]` 三元组，逐格给出算好的朝向。上面的路径：
横段一路朝东（`rot=0`），**到拐点 `(278,78)` 自己转成朝南（`rot=1`）**，竖段继续朝南。

两个保证：

- **四邻连续** —— 斜线不会产生对角相接的两格（那在物理上接不上，传送带只认四邻）。
  45° 斜线会自动补成正交阶梯，宁可多几格也不断链。
- **拐点即转向** —— 拐点属于两段共用的那一格，它的朝向指向下一段。

**`path` 这个参数名和客户端库的 `post(path, ...)` 首参重名**，用 `arena.py` 时
走封装好的 `place_path()`，别直接 `post("place", path=...)`。"""

API_UNITS_OLD = """返回 `data.units` 数组：`id` `type` `team` `x` `y` `health`。"""

API_UNITS_NEW = """返回 `data.units` 数组。

| 字段 | 含义 |
|---|---|
| `id` `type` `team` `x` `y` `health` `maxHealth` | 基本属性 |
| `rotation` `canBuild` | 朝向 / 能否建造 |
| `stack` | 携带的物品 |
| `shooting` `targetX` `targetY` `targetId` `targetType` `targetTeam` | 开火与交战目标 |
| `buildingAt` | **这个建造单位当前在建哪一格**，见下 |

#### `buildingAt`

```json
{"x":311,"y":130,"progress":0.0,"block":"conveyor"}
```

建造队列的**队首**就是它下一步要建的格子。`progress` 是施工进度 0~1：

- **轮询它就等于知道「还要多久」** —— 不必按自维护的清单盲撞（那份清单会因为
  丢单和服务端状态对不上）；
- **长时间不涨就是卡住了**，可以据此决定要不要用移动命令把它送走；
- 队列空时该字段**不出现**。"""

API_STALLS_OLD = """| `kind` | `beltStall` / `drillBlocked` / `factoryBlocked` / `missingInput` |
| `x` `y` | 出问题的位置 |
| `item` | 相关物品（有则给出） |"""

API_STALLS_NEW = """| `kind` | `beltStall` / `drillBlocked` / `factoryBlocked` / `missingInput` |
| `x` `y` | 出问题的位置 |
| `item` | 相关物品（有则给出） |
| `cause` | **一句话说清该往上游查还是往下游查**，见下 |

#### `cause`：两种停机的区分

| 取值 | 含义 | 往哪查 |
|---|---|---|
| `starved` | 上游没把料送来（缺输入） | **上游** |
| `outputBlocked` | 自己有料且已满仓，出料侧不收 | **下游** |
| `outputRefused` | 出料侧不收，但自己还没满仓（刚堵上） | 下游 |
| `unknown` | 其它情况（电力、配方等），看 `missing` | 两者都不是 |

判据：**`efficiency == 0` 且满仓 ⇒ 输出路径不通；缺料 ⇒ 输入路径不通。**

> 这两者以前要靠 `outputAccepts` 和 `missing` 自己拼。典型误判是「核心满了 →
> 整条上游线回堵 → 上游钻机全部 `eff=0.0` 且满仓」，看着像产线坏了，
> 其实是**下游吃饱了**。"""

ARENA_OLD = """    def control(self, op, **kw):
        return self.post("control", op=op, **kw)"""

ARENA_NEW = """    def control(self, op, **kw):
        return self.post("control", op=op, **kw)

    def place_path(self, points, block, config=None, rot=None):
        \"\"\"折线布线：传点列，**服务端逐格算朝向**。

        points 形如 [(x1, y1), (x2, y2), ...]，至少两个点。
        返回里带 rotations —— `[x, y, rot]` 三元组，就是服务端算好的朝向。

        为什么要封装：本方法内部调用的 post(path, **params) 首参名就叫 path，
        而接口的参数也叫 path，直接 post("place", path=...) 会撞成 TypeError。
        \"\"\"
        spec = ";".join(f"{int(x)},{int(y)}" for (x, y) in points)
        return self._call("place", {"shape": "path", "path": spec,
                                    "block": block, "config": config,
                                    "rot": rot}, "POST")"""

JOBS = [
    (D / "API.md", [
        (API_UNIT_OLD, API_UNIT_NEW, "/place 的 config 与 shape=path"),
        (API_UNITS_OLD, API_UNITS_NEW, "/units 的 buildingAt"),
        (API_STALLS_OLD, API_STALLS_NEW, "/stalls 的 cause"),
    ]),
    (ARENA, [(ARENA_OLD, ARENA_NEW, "place_path() 封装")]),
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
    print()
    if bad:
        print("有问题：")
        for b in bad:
            print("  " + b)
        return 1
    print("文档与客户端库已更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
