#!/usr/bin/env python3
"""更新 TODO.md —— 2.1 回放做完了。"""
import pathlib
import sys

P = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")

OLD = """### 2.1 回放（最大的一块）

**现状**：服务器侧录像已完整（JSON Lines，`meta`/`snap`/`ev`/`end`，方块存增量）。
**客户端图形回放完全没做。**

**旧方案**（[DESIGN.md](DESIGN.md)）：游戏内客户端 Mod，替换 `Vars.world`，
自估 850–1400 行、「不可单会话完成」。

**新方案**（借鉴 meow-ai-arena 的 `viewer.html`，8.3 KB 就够）：
1. **先验证**：JSONL 里的数据到底够不够画（**这才是真风险，不是渲染代码量**）
2. **最轻路径**：Python + Pillow 渲成 PNG 序列 → ffmpeg 合成，约 150–250 行
3. **推荐路径**：独立 HTML 播放器，约 500–700 行，单会话可完成

**走 HTML 有三处必须和它不同**：
- 录像几十 MB，**不能内嵌** → `fetch()` + `ReadableStream` 逐行解析
- `snap` 是增量的，拖时间轴前要能重建状态 → **每 100 个 snap 拍一张全量关键帧**
- 渲染分三档：纯色矩形+首字母（~200 行）→ sprite sheet（+150 行）→ 静态底图

**阻塞**：无阻塞，纯粹是没排上。"""

NEW = """### 2.1 回放 ✅ 已完成

**[`replay/index.html`](../replay/index.html) —— 单文件零依赖，拖入 `.jsonl` 即播。**

骨架借鉴 meow-ai-arena 的 `viewer.html`（8.3 KB 纯前端 + canvas，
证明「回放不需要重放引擎，只要状态序列 + 一个画法」）。三处必须不同：

| | 它 | 我们 |
|---|---|---|
| 数据载入 | 录像几百 KB–2 MB，`const R=/*__REPLAY__*/null` 内嵌进 HTML | 几十 MB，**不能内嵌** → `<input type=file>` + `file.stream()` 逐块读 |
| 跳转 | 帧是全量，seek 是 O(1)，敢不做索引 | `builds` 是**增量**，必须重放 → **每 100 帧存一份建筑副本**，把 O(n) 降到 O(100) |
| 地图 | 明文数组内嵌在 header | 三段 **RLE**（floors/ores/walls），客户端解码 |

功能：播放/逐帧/进度条/1–10× 倍速、跳到关键事件、点队伍高亮过滤、网格、1–8× 缩放。
地图按名称哈希配色（不需要知道是哪张图），建筑画队伍色块 + 朝向三角 + 首字母。

**这次动手前先做了「数据够不够画」的验证，结论是不够，补了四样**（见 git `c51ecb5`）：
地图（完全没有）、建筑 `rot`、被拆方块的记录（`removed`）、`items`（可选，未做）。
其中 `removed` 那条最隐蔽——`knownBuilds` 每帧用当前全量替换，拆掉的方块从集合
消失后**不写任何记录**，回放端会一直画着它。

**验证方式**：没有 headless 浏览器，但「重建出来的状态对不对」是纯逻辑。
`drive/verify-player.js` 把播放器里那几段函数抄出来跑真实录像，用两套互不相干的
算法对账（Map 覆盖+删除 vs 集合差），并抽查 checkpoint 重建与从头重放是否等价。
实测一份专门造来覆盖全分支的录像（建 5 条带子、拆 2 条、再建 2 条）：
出现过 11 个 key、被拆 2 个 → 最终 9 个建筑，两套算法一致。

**仍未做**：`builds[].items`（能看出谁堵了，画面信息量更大）、sprites 渲染
（现在是最简的色块+字母档）、长时间录像的滚动加载（目前全量解析进内存）。"""

OLD2 = """- **录像完整性**：文件写入验过，**能不能还原成完整对局没验**"""

NEW2 = """- **录像完整性**：~~文件写入验过，能不能还原成完整对局没验~~ → **已验**。`drive/verify-player.js` 用两套互不相干的算法对账（Map 覆盖+删除 vs 集合差），并抽查 checkpoint 重建与从头重放是否等价。实测一份覆盖全分支的录像（建 5 条带子、拆 2 条、再建 2 条）：11 个 key、拆 2 个 → 最终 9 个建筑，两套算法一致"""

RULES = [
    (OLD, NEW, "2.1 回放标记完成"),
    (OLD2, NEW2, "录像完整性标记已验"),
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
    print("\nTODO.md 已更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
