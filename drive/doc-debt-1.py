#!/usr/bin/env python3
"""把这一轮验证发现的东西写进 API.md 与 CHANGELOG.md。

四项修复：
  1. 成功响应被回成 HTTP 400（ok:false 子串匹配误判）
  2. 批量的接受数只藏在 message 散文里，tiles 是请求数
  3. /queue?clear 的条数没有结构化字段
  4. arena.py 把持续 429 报成 -1
"""
import pathlib
import sys

API = pathlib.Path(r"C:\dsh\ai-arena\docs\API.md")
CHG = pathlib.Path(r"C:\dsh\ai-arena\CHANGELOG.md")

# ── API.md ─────────────────────────────────────────────────────────────
API_OLD = """`POST /queue?clear=true` 清空全队待办计划，返回清掉了几条。"""

API_NEW = """`POST /queue?clear=true` 清空全队待办计划：

```json
{"cleared": 60, "message": "cleared 60 pending plan(s)"}
```

`cleared` 是结构化字段，直接读它 —— 别去解析 message。

### 批量下单的返回：`tiles` 是请求数，`accepted` 才是排上的

`/place` 与 `/break` 走 `shape=` 时是批量。返回里两套数字**含义不同**：

| 字段 | 含义 |
|---|---|
| `tiles` | 你**请求**了多少格 |
| `requested` | 同上（显式字段） |
| `accepted` | 真正排上队的条数 |
| `skipped` | `{invalid, invisible, noUnit}` 的分项 |
| `limitReached` | 是否撞到了 `plansPerUnit`（默认 60） |

**超过 `plansPerUnit` 的部分是被静默丢弃的**：实测请求 70 格、队列上限 60，
返回 `ok: true` 而 `accepted` 只有 60。只读 `tiles` 会以为 70 条都排上了。

```json
{"requested":70, "accepted":60, "skipped":{"invalid":10,"invisible":0,"noUnit":0},
 "limitReached":true, "plansPerUnit":60, "tiles":70, "shape":"line", "message":"..."}
```

想确认到底排上了多少，**读 `accepted`，或者直接看 `/queue` 的 `plans`**。"""

CHG_OLD = "## 回放（2026-10-05）"
CHG_NEW = """## 接口正确性（2026-10-05）

四个缺陷由一轮实测查出（`drive/verify-debt-1.py` / `verify-debt-2.py` 可复现）：

- **修：成功响应被回成 HTTP 400。** `/place` 在材料不足时，成功排上计划却返回
  `400` 配 body `{"ok":true,...}`。原因是判定「这是不是错误响应」用了全文子串
  匹配 `contains("\\"ok\\":false")`，而成功响应里 `materials.requirements`
  每项都带 `{"ok":false,"short":N}`。客户端按状态码分流就会把成功当失败。
  改成只看开头（错误响应必然以 `{"ok":false` 开头）。**这一条最要命**：
  它只在材料不足时触发，正是 AI 最需要看清 `materials` 的时刻。
- **`/place`、`/break` 的批量响应新增 `requested` / `accepted` / `skipped` /
  `limitReached`。** 以前接受数只藏在 `message` 的散文里，而 `tiles` 是
  **请求数** —— 请求 70 格、上限 60 时返回 `ok:true` 且 `tiles:70`，
  实际只排上 60。
- **`/queue?clear` 新增 `cleared` 字段。** 以前条数只在 `message` 文本里。
- **客户端库把持续 429 如实报成 `1429`。** 以前退避重试耗尽后统一抛
  `-1 unreachable`，调用方会去查网络，而真正该做的是降频。

## 回放（2026-10-05）"""

def main():
    # API.md
    t = API.read_text(encoding="utf-8")
    if t.count(API_OLD) != 1:
        print(f"!! API 锚点 {t.count(API_OLD)} 次")
        return 1
    API.write_text(t.replace(API_OLD, API_NEW), encoding="utf-8")
    print("  ✓ API.md：批量字段与 clear 字段")

    # CHANGELOG.md
    c = CHG.read_text(encoding="utf-8")
    if c.count(CHG_OLD) != 1:
        print(f"!! CHANGELOG 锚点 {c.count(CHG_OLD)} 次")
        return 1
    CHG.write_text(c.replace(CHG_OLD, CHG_NEW), encoding="utf-8")
    print("  ✓ CHANGELOG.md：新增「接口正确性」一节")
    return 0


if __name__ == "__main__":
    sys.exit(main())
