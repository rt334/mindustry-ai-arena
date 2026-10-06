#!/usr/bin/env python3
"""§四 流程欠账：给 warp 那批数据加注 + 生成 CHANGELOG。

两件事：
  1. REVIEW-ADDENDUM 里「400 次 warp 清掉 59 项」那段，原文没标注
     「这批数据不能当基线用」。CONDITIONS.md 里写了，但读 reviews 的人看不到。
     历史记录不改内容，只加一条醒目的注。
  2. 从 git log 生成 CHANGELOG.md —— 现在只有 commit 历史，缺一份
     面向使用者的「接口改了什么」摘要。

CHANGELOG 按日期/主题分组，只收录对使用者有影响的改动，
内部重构和脚本文档不进（那些 git log 里能查到）。
"""
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(r"C:\dsh\ai-arena")
REVIEW = ROOT / "docs" / "reviews" / "REVIEW-ADDENDUM.md"
CHANGELOG = ROOT / "CHANGELOG.md"


def git(*args):
    r = subprocess.run(["git", "-C", str(ROOT), *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout


# ── 1. 给 warp 段加注 ──────────────────────────────────────────────────
ANCHOR = """对方的 `acc4.py`（按自维护清单循环 warp 建造单位）解决的是
「一个 builder → 一堆待建方块」的吞吐问题，实测 400 次 warp 清掉 59 项。"""

ANNOTATED = """对方的 `acc4.py`（按自维护清单循环 warp 建造单位）解决的是
「一个 builder → 一堆待建方块」的吞吐问题，实测 400 次 warp 清掉 59 项。

> **⚠ 这批数据不能再当基线用（2026-10-05 补注）**
>
> `warp` 是**直接改单位坐标的瞬移**，不是引擎流水线里的移动。真人玩家做不到
> 把建造单位瞬移到工地，所以「400 次 warp 清掉 59 项」这个吞吐数字
> **超出人类可达范围**，不能和正常建造的性能对比。
>
> 该端点已在 `8cbc024` 默认禁用（`-Darena.allowwarp=true` 才开），
> 复现这批数字需要显式打开。原文保留不改（历史记录），但结论请按此折算。
>
> 详见 [CONDITIONS.md](../CONDITIONS.md) 的事故记录第 1 条。"""


def annotate():
    t = REVIEW.read_text(encoding="utf-8")
    if "这批数据不能再当基线用" in t:
        print("  reviews：已加过注，跳过")
        return True
    n = t.count(ANCHOR)
    if n != 1:
        print(f"  !! reviews 锚点 {n} 次命中（应为 1）")
        return False
    REVIEW.write_text(t.replace(ANCHOR, ANNOTATED), encoding="utf-8")
    print("  reviews：warp 数据已加注")
    return True


# ── 2. 生成 CHANGELOG ──────────────────────────────────────────────────
HEAD = """# 变更记录

面向**使用者**的接口改动摘要 —— 只收录会影响你怎么调接口的那些。
内部重构、脚本文档、验证过程不进这里（那些 `git log` 里能查到）。

格式按「主题」分组而非按 commit，因为一次改动常常跨多个提交。

> **接口版本约定**：目前没有语义化版本号。`docs/API.md` 是唯一权威，
> 改动以本文档记录为准。跨版本的对局成绩不可比 —— 见
> [TODO.md](docs/TODO.md) 里「接口版本号没有约定」一条。

"""

# 手写的主题分组（比机械按 commit 分更有用）
THEMES = [
    ("回放", "2026-10-05", """- **录像格式补齐四样**（`c51ecb5`）：`meta` 加 `mapData`（整张地图，三段 RLE）、
  `snap.builds` 加 `rot`、`snap` 新增 `removed`（本帧消失的方块）、`version` 升到 2。
  改动前录像画不出来 —— 没有地图、没有朝向、拆掉的方块不记录。
- **新增回放播放器**（`0674bb2`）：`replay/index.html`，单文件零依赖，
  浏览器打开后拖入 `.jsonl` 即播。"""),

    ("接口安全与对等", "2026-10-05", """- **`/control?op=warp` 默认禁用**（`8cbc024`）：它直接改单位坐标，是唯一的瞬移后门。
  禁用后返回 `403` + `code 1005`。服务器侧可用 `-Darena.allowwarp=true` 打开。
  **要移动单位请用 `/command?action=move` 或 `/control?op=order`。**
- **限流真的生效了**（`8cbc024`）：以前 `rateLimit` 配置解析了但没有任何逻辑。
  现在每 agent 一个令牌桶（默认 60/s、突发 200），超限返回 `429` + `code 1429`。
- **敌方建筑不再暴露库存**（`459550e`）：非己方建筑的 `items`/`liquids` 一律清空。
  以前可见的敌方核心会连库存一起给，绕过了 `Intel` 的确认机制。
- **`setup` 不再泄漏规则改动**（`459550e`）：`enemyCoreBuildRadius` 等三项
  以前改了不还原。当前地图看不出差异（原值即目标值），换图才会显形。"""),

    ("建造体验", "2026-10-05", """- **`/place` 返回材料预检**（`d2a2132`）：每次下单都回 `materials`，
  逐项给「要多少 / 有多少 / 缺多少」。`adequate=false` 说明这计划会一直卡着。
- **`/place` 返回施工时长**（`d2a2132`）：`buildTime.seconds`，
  按引擎公式 `buildCost / builderSpeed` 算，不含走路时间。
- **`/place` 支持 `shape=path`**（`d5ea328`）：折线布线，朝向由服务端算。
- **`/place` 的 `mode: transfer`**（`d5ea328`）：对同格重复下单即转移建造目标，
  返回 `previousBlock` 与 `inheritedProgress` —— 对应游戏里双击方块改目标。
- **`/queue` 报「为什么卡」**（`76760b1`）：新增 `stuckReason`，四种取值 ——
  `missingMaterials` / `tileOccupied` / `builderTooFar` / `unknown`。
  `hint` 改为按原因分情况给；以前一律建议移动命令，在被墙挡住时是误导。
- **`/queue` 给进度与预计**（`d5ea328`）：`progressRate` / `etaSeconds`（实测外推）、
  `stuckSeconds`（进度不动且单位也不动超过 3 秒）。"""),

    ("物流与停机诊断", "2026-10-05", """- **建筑暴露接货口与输出格**（`d5ea328`）：`acceptsFrom` / `sendsTo`。
  不用再试探「这条带子接哪个方向」。
- **`/stalls` 新增电力类别**（`145043b`）：`powerUnconnected` / `powerStarved`，
  对应「电力断开」与「电力不足」两种肉眼可见的现象。
- **`/state` 新增 `limits` 与 `vision`**（`d5ea328`）：不用试探就知道批量上限、
  地图窗口上限、自己的视野半径。"""),

    ("接口文档", "2026-10-05", """- **新增「信息可见性契约」**（`e944c5e`）：逐字段标注「对应人类能直接看到的什么」，
  并写死缺省语义 —— 字段不出现表示**不适用**，不是「没查到」。
- **新增「并发与执行顺序」**（`e944c5e`）：请求经 `Core.app.post` 进主线程队列
  按入队顺序执行。串行发顺序确定，并发发谁先谁后都可能。
- **新增 [docs/CONDITIONS.md](docs/CONDITIONS.md)**（`e944c5e`）：能力边界、
  对等约束定义、发现过的越界路径与处理。
- **新增 [docs/TODO.md](docs/TODO.md)**（`8aefbd5`）：未完成事项盘点。"""),

    ("多格方块坐标", "2026-10-05", """- **修正坐标语义**（`0222d49`）：`/buildings`、`/place`、`/map` 的坐标是
  **中心**（多格方块），不是左上角。引擎内部（`Edges`、`getLinkedTiles`）才用左上角，
  换算是 `block.sizeOffset`。
  同时修掉 `drillOutputs` 的 footprint 计算 —— 它以前对 3x3 及以上会偏一格，
  导致 `laser-drill` 的 `sendsTo` 指向错误的邻居。"""),
]


def gen_changelog():
    body = [HEAD]
    for title, date, text in THEMES:
        body.append(f"## {title}（{date}）\n\n{text}\n")
    CHANGELOG.write_text("\n".join(body), encoding="utf-8")
    print(f"  CHANGELOG.md：已生成 {len(THEMES)} 个主题分组")


def main():
    print("== 1. reviews 数据加注 ==")
    ok1 = annotate()
    print("\n== 2. 生成 CHANGELOG ==")
    gen_changelog()
    return 0 if ok1 else 1


if __name__ == "__main__":
    sys.exit(main())
