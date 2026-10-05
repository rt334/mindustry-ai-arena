#!/usr/bin/env python3
"""把这一轮验证的东西写进 API.md 与 CHANGELOG.md。

新增/修正：
  · /buildings 有 id 字段了（以前没有，导致 commandBuilding 谁都调不了）
  · /command 的 units= 是复数逗号分隔；漏传现在报 1001 而不是「no valid units」
  · /command?action=move 以前回成功但不生效，现已修
"""
import pathlib
import sys

API = pathlib.Path(r"C:\dsh\ai-arena\docs\API.md")
CHG = pathlib.Path(r"C:\dsh\ai-arena\CHANGELOG.md")

A1_OLD = "| `team` | 队伍 id |\n| `block` | 方块名 |"
A1_NEW = ("| `team` | 队伍 id |\n"
          "| `id` | **建筑唯一 id** —— `/command?action=commandBuilding` 要的就是它 |\n"
          "| `block` | 方块名 |")

A2_OLD = "### `/command` 的 8 种 action"
A2_NEW = """### `/command` 的 8 种 action

**`units=` 是复数、逗号分隔**（`units=219,220`），不是 `unit=`。漏传或写错名字
会返回 `1001 required: units=<id>[,<id>...]`。

`move` / `attackUnit` / `assistBuilding` / `setCommand` / `setStance` 需要 `units=`；
`commandBuilding` 需要 `buildings=`（建筑 id 见 `/buildings` 的 `id` 字段）。

> **`move` 的行为说明**：引擎的 `Call.commandUnits` 是喂给 `CommandAI` 的，
> 而本竞技场里**每个单位都被影子 Player 持有**（`controller=Player#NNN`），
> 玩家持有的单位不理会 AI 指挥。所以 `move` 现在会额外走 `moveOrders`
> （每帧直接写速度与朝向，绕过控制器），**它是真的会动的**。
> `attackUnit` / `assistBuilding` 仍只走引擎 RPC —— 指挥会被记录，
> 但玩家持有的单位是否执行取决于引擎行为。要移动单位优先用 `move` 或
> `/control?op=order`。

"""

C1_OLD = "## 接口正确性（2026-10-05）"
C1_NEW = """## 接口正确性（2026-10-05 · 第二批）

又一轮实测（`drive/verify-commands.py`、`compare-move-order.py`）：

- **`/command?action=move` 回成功但单位纹丝不动。** 同一单位、同一目标：
  `move` 位移 **0.00 格**，`/control?op=order` 位移 **23.14 格**。原因是
  `command()` 走 `Call.commandUnits`（喂给 `CommandAI` 的引擎 RPC），而本竞技场
  每个单位都被影子 Player 持有，玩家持有的单位不理会 AI 指挥。
  已改为位置类指令额外挂 `moveOrders`（每帧直接写速度，绕过控制器）——
  复测位移 **22.99 格**。
- **新增建筑 `id` 字段。** `/command?action=commandBuilding` 要求传 `buildings=`
  建筑 id，但 `/buildings` 以前根本不暴露 id —— **这个 action 对任何客户端都是死路**。
- **`/command` 漏传 `units=` 时不再报误导性错误。** 以前回
  `1002 no valid units for crux`，读起来像「你给的 id 不属于这队」，
  真实原因往往是参数名写成了单数 `unit=`。现在报
  `1001 required: units=<id>[,<id>...]`。

顺带验证：
- **`cursor_expired` 契约**（此前从未跑通）：`since=1` → `410 + code 1006`，
  消息指明 `resync with since=0`，而 `since=0` 永远可用。
  为此把 `EventLog.CAPACITY` 做成可用 `-Darena.eventlog.capacity=N` 覆盖 ——
  攒满 4096 条事件要十几分钟正常游玩，与契约本身无关。
- **8 种 `/command` action 全部可达**，参数校验齐全（未知 cmd/stance、
  缺 units、缺 buildings 都给出结构化错误），无 5xx、无空 body。

## 接口正确性（2026-10-05 · 第一批）"""

RULES = [
    (API, A1_OLD, A1_NEW, "buildings 加 id 字段"),
    (API, A2_OLD, A2_NEW, "/command 小节补 units= 与 move 说明"),
    (CHG, C1_OLD, C1_NEW, "CHANGELOG 第二批"),
]


def main():
    texts = {p: p.read_text(encoding="utf-8") for p in (API, CHG)}
    bad = []
    for path, old, new, label in RULES:
        t = texts[path]
        n = t.count(old)
        if n != 1:
            bad.append(f"{path.name}: {n} 次 → {label}")
            print(f"  !! {n}  {label}")
            continue
        texts[path] = t.replace(old, new, 1)
        print(f"  ✓ 1 处  {label}")
    if bad:
        print("\n有问题，未写盘：")
        for b in bad:
            print("   " + b)
        return 1
    for p, t in texts.items():
        p.write_text(t, encoding="utf-8")
    print("\n文档已更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
