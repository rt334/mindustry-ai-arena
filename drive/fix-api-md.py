#!/usr/bin/env python3
"""第 0 档：给 API.md 补上缺失的端点文档。

代码路由里有 33 个端点，API.md 只写了 27 个。缺的 6 个：
/block、/maps、/observe、/command、/spawn、/fog

其中 /spawn 默认被服务端拒绝（AIArena.ALLOW_DIRECT_SPAWN = false），
这条必须写在手册里，否则使用者只会看到 403 + code 1005 而不知为何。
"""
import pathlib
import sys

P = pathlib.Path(r"C:\dsh\ai-arena\docs\API.md")

OLD_GET_TAIL = """### `GET /intel`

情报汇总。

---

## 四、可执行的操作"""

NEW_GET_TAIL = """### `GET /intel`

情报汇总。

### `GET /block`

方块详情。传 `name=<方块名>` 取单个方块的完整定义（含 `details` 说明文案）；
不传 `name` 则列出**全部可放置且未隐藏**的方块。

### `GET /maps`

列出引擎里所有地图的**真实属性**，含 `teams` 数量与 PvP 可用性。选图前用它核对，别猜。

> PvP 的判定标准是 `map.teams.size > 1`（`Gamemode.pvp` 的地图判定条件）
> 与 `Maps.pvp()` 的 tag；**`spawns` 是「玩家出生点」，与核心无关** ——
> 早期按 `spawns` 判断走过弯路。

### `GET /observe`

当前视角状态：`currentView`、`canSeeAll`，以及**本 agent 能观察哪些队**（每队带 `viewable`）。
非 admin 只有自己队 `viewable=true`；请求别人的视角会被**静默降级**为自己的，不报错。

---

## 四、可执行的操作"""

OLD_OP_TABLE = """| `POST /control` | `op=` … | 单位操控。`op` 取值：`pos` `order` `warp` `enter` `release` `fire` `stopmove` `orders` |
| `POST /mine` | `x` `y` [`unit`] | 让单位挖指定格 |
| `POST /record` | `action=start\\|stop` | 录像开关 |
| `POST /chat` | `text` | 发言 |
| `POST /admin` | `action=` … | 管理操作（仅 admin） |"""

NEW_OP_TABLE = """| `POST /command` | `action=` `units=` … | 指挥单位（8 种 action，见下） |
| `POST /control` | `op=` … | 单位操控。`op` 取值：`pos` `order` `warp` `enter` `release` `fire` `stopmove` `orders` |
| `POST /spawn` | `type` `x` `y` [`team`] | **默认禁用**，见下 |
| `POST /mine` | `x` `y` [`unit`] | 让单位挖指定格 |
| `POST /record` | `action=start\\|stop` | 录像开关 |
| `POST /chat` | `text` | 发言 |
| `POST /admin` | `action=` … | 管理操作（仅 admin） |"""

OLD_UNIT_PARA = """默认由**当前接管的单位**执行（`/control?op=enter&unit=<id>` 之后就是它），没有则任选一个可建造单位。
传 `unit=<id>` 可显式指定。响应里的 `builder` 字段回显实际用了谁。"""

NEW_UNIT_PARA = """默认由**当前接管的单位**执行（`/control?op=enter&unit=<id>` 之后就是它），没有则任选一个可建造单位。
传 `unit=<id>` 可显式指定。响应里的 `builder` 字段回显实际用了谁。

### `/command` 的 8 种 action

| action | 参数 | 作用 |
|---|---|---|
| `move` | `units` `x` `y` [`queue`] | 移动到格坐标 |
| `attackUnit` | `units` `target` | 攻击指定单位 id |
| `assistBuilding` | `units` `x` `y` | 协助建造该格 |
| `setCommand` | `units` `cmd=` | 设置逻辑指令 |
| `setStance` | `units` `stance=` [`enable`] | 设置姿态 |
| `commandBuilding` | `buildings` `x` `y` | 指挥建筑（如给工厂设集结点） |
| `requestItem` | `x` `y` `item=` [`amount`] | 从该格取物品 |
| `transferInventory` | `x` `y` | 向该格交付库存 |

`units` / `buildings` 是 **id 数组**（逗号分隔），`x` `y` 是**格坐标**。

**队列卡死时值得试**：`/command?action=move&units=<id>&x=&y=` 或
`/control?op=order&unit=<id>&x=&y=` 能把卡住的建造单位送去工地，
实测 `plans` 一次从 56 降到 1，沿线方块真的建成 —— 比 `/break` 干净。

### `/spawn` 默认被禁用

服务端**默认拒绝**直接生成单位：

```json
{"ok":false,"code":1005,"error":"direct unit spawning is disabled: units must be produced by a factory. …"}
```

理由：直接 spawn 绕过整套产能 —— 没有建造时间、不需要电力、不需要工厂，
「谁先攒出产能」这个维度直接消失，对局退化成两个脚本对撞。

调试时用 `-Darena.allowspawn=true` 打开。正常对局**用工厂**：
建 `air-factory` / `ground-factory` / `naval-factory` → 供电 →
`/config?x=&y=&value=<单位名>` 选生产计划。

裁判（admin）可带 `team=<id>` **替别队**生成，用于组织比赛。"""

OLD_ADMIN_TABLE = """| `POST /referee/start` | 解除暂停 |
| `GET /referee/diag` | 同 `/diag` |"""

NEW_ADMIN_TABLE = """| `POST /referee/start` | 解除暂停 |
| `GET /referee/fog` | 读取当前迷雾设置（`fog` / `staticFog` / `pvp`） |
| `POST /referee/fog?fog=false` | 关掉迷雾（`fog=true&static=true` 打开并同步静态位图） |
| `POST /referee/observe` | 视角切换，同 `GET /observe` |
| `POST /referee/record?action=start&label=` | 开始录像（`action=stop` 结束） |
| `GET /referee/diag` | 同 `/diag` |"""

RULES = [
    (OLD_GET_TAIL, NEW_GET_TAIL),
    (OLD_OP_TABLE, NEW_OP_TABLE),
    (OLD_UNIT_PARA, NEW_UNIT_PARA),
    (OLD_ADMIN_TABLE, NEW_ADMIN_TABLE),
]


def main():
    text = P.read_text(encoding="utf-8")
    bad = []
    for old, new in RULES:
        n = text.count(old)
        label = old.splitlines()[0][:56]
        if n != 1:
            bad.append(f"{n} 次命中（应为 1）: {label}")
            print(f"  !! {n} 次  {label}")
            continue
        text = text.replace(old, new)
        print(f"  1 处  {label}")
    if bad:
        print("\n有规则不满足，未写盘：")
        for b in bad:
            print("  " + b)
        return 1
    P.write_text(text, encoding="utf-8")
    print(f"\nAPI.md 已补齐，共 {len(RULES)} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
