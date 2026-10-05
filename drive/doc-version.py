#!/usr/bin/env python3
"""收尾：API.md 写版本约定、REPORT.md 加指路、TODO §四 更新三条状态。"""
import pathlib
import sys

MOD = pathlib.Path(r"C:\dsh\ai-arena")
API = MOD / "docs" / "API.md"
TODO = MOD / "docs" / "TODO.md"
REPORT = MOD / "docs" / "reviews" / "REPORT.md"

API_SECTION = """

---

## 接口版本号

`GET /ping` 的响应里带 `apiVersion`（无鉴权，最容易探测到的地方）：

```json
{"ok":true,"data":{"headless":true,"tick":12345,"agents":5,"apiVersion":"1.4"}}
```

端口发现文件（`bridge-<agent>.json`）里也带一份。

**跨版本的对局成绩不可比。** 成绩记录必须带上这个号 —— 这个接口改过不少次
（`stuckReason`、批量的 `requested`/`accepted`、`/queue` 的 `cleared`、
`/drill` 的 `itemsPerSecond`、SSE、蓝图……），而 `reviews/` 里几批数据是
不同时期跑的。没有版本号，「这局 AI 是 3.2/s、那局是 2.1/s」根本说不清
是不是同一个接口测出来的。

### 什么时候加号

| 变更 | 动作 | 例 |
|---|---|---|
| **破坏性**：删字段、改字段语义、改默认行为 | `major` +1 | 把 `tiles` 的含义从「请求数」改成「接受数」 |
| **增量**：只加字段、只加端点 | `minor` +1 | 加 `itemsPerSecond`、加 `/stream` |

「加了字段」也算变更、也要 +1 —— 老客户端虽然还能跑，但它记录的成绩
少了新字段的信息，与新版本的成绩仍然不是同一批可比数据。
"""

REPORT_OLD = "| `acc4.py` | 建造加速器（按 pending.json 循环 warp 建造单位） |"
REPORT_NEW = ("| `acc4.py` | 建造加速器（按 pending.json 循环 warp 建造单位）——"
              "⚠ **该工具用 warp（直接改坐标的瞬移），真人玩家做不到，"
              "它跑出的吞吐数字不可作可比基线**，见 "
              "[REVIEW-ADDENDUM.md](REVIEW-ADDENDUM.md) §四。 |")

TODO_ROWS = [
    ("| **`docs/reviews/` 那批数据没标注** | `CONDITIONS.md` 里写了「`acc4.py` 用 warp 加速建造，那批数据不能再作为可比基线」，但 `reviews/` 里的原文**没有加这条注**，直接读会当成可比数据 |",
     "| **`docs/reviews/` 那批数据没标注** | **已关闭**。核查：`REVIEW-ADDENDUM.md` §四 已带完整补注（warp 是瞬移、真人做不到、端点已默认禁用）。但注释只在 ADDENDUM 里，读 `REPORT.md` 的人不会顺手翻到 —— 已在 `REPORT.md` 的 `acc4.py` 那行加了 ⚠ 指路。 |"),
    ("| **接口版本号没有约定** | 跨版本的对局成绩不可比，但没有版本号可标 |",
     "| **接口版本号没有约定** | **已做**：`AIArena.API_VERSION = \"1.4\"`，挂在 `/ping` 与端口发现文件上；约定（什么算破坏性、增量也要 +1、成绩必须带号）写进 `API.md`。 |"),
]


def main():
    ok = True

    a = API.read_text(encoding="utf-8")
    if "## 接口版本号" in a:
        print("  · API.md 已有该节")
    else:
        API.write_text(a.rstrip() + API_SECTION, encoding="utf-8")
        print("  ✓ API.md 追加接口版本号一节")

    r = REPORT.read_text(encoding="utf-8")
    n = r.count(REPORT_OLD)
    if n == 1:
        REPORT.write_text(r.replace(REPORT_OLD, REPORT_NEW, 1), encoding="utf-8")
        print("  ✓ REPORT.md 的 acc4.py 行加了 ⚠ 指路")
    else:
        print(f"  !! REPORT.md 锚点 {n} 次")
        ok = False

    t = TODO.read_text(encoding="utf-8")
    for old, new in TODO_ROWS:
        m = t.count(old)
        if m != 1:
            print(f"  !! TODO 锚点 {m} 次：{old[:40]}…")
            ok = False
            continue
        t = t.replace(old, new, 1)
        print(f"  ✓ TODO §四：{old[3:24]}…")
    TODO.write_text(t, encoding="utf-8")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
