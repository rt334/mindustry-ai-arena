#!/usr/bin/env python3
"""把对等性/安全性这三件事写进文档。"""
import pathlib
import sys

D = pathlib.Path(r"C:\dsh\ai-arena\docs")

API_OP_OLD = """| `POST /control` | `op=` … | 单位操控。`op` 取值：`pos` `order` `warp` `enter` `release` `fire` `stopmove` `orders` |"""

API_OP_NEW = """| `POST /control` | `op=` … | 单位操控。`op` 取值：`pos` `order` `enter` `release` `fire` `stopmove` `orders`；**`warp` 默认禁用**（见下） |"""

API_TAIL_ANCHOR = """### 多个建造单位"""

API_TAIL_NEW = """### `/control?op=warp` 默认被禁用

`warp` **直接改单位坐标**，是 P0 技术验证留下的调试探针。它也是唯一的瞬移后门：

```json
{"ok":false,"code":1005,"error":"direct position setting is disabled: unit movement must go through the engine (use /command?action=move). Server-side override: -Darena.allowwarp=true"}
```

**为什么禁**：对等约束里「移动速度 = 引擎行为」——人类玩家只能 WASD，
而 `warp` 让 AI 一步跨到任意坐标，走位、赶路、规避全都不再成立。

**要移动就用 `/command?action=move`**（或 `/control?op=order`），走引擎的
`CommandAI`，速度和人类同源。

### 限流

**每个 agent 一个令牌桶**，默认 `60/s`、突发 `200`（`ai-arena.json` 的 `rateLimit`）。
超限返回 `429` + `code 1429`，响应里写明当前配置：

```json
{"ok":false,"code":1429,"error":"rate limit exceeded: 60/s (burst 200)"}
```

限流在**鉴权之后**执行 —— 过不了鉴权的请求不该消耗配额。
实测连打 900 次：放行 591 次，与「桶 200 + 耗时 6.5s × 60/s ≈ 590」吻合。

> 这条以前是**死配置**：`perSecond`/`burst` 解析了，`1429` 也写在错误码表里，
> 但没有任何限流逻辑 —— 一个 agent 放开打就能占满 HTTP 线程池。
> 客户端轮询建议留出余量（比如 5–10 次/秒就够用了）。

### 多个建造单位"""

DESIGN_ERR_OLD = """1001 bad_request      1002 not_found         1003 out_of_bounds
1004 queue_full       1005 read_only         1006 cursor_expired
1007 op_expired       1008 place_blocked     1009 place_invalid
1401 unauthorized     1403 forbidden         1500 internal_error

1008 -> HTTP 409（footprint 被占，挪一格即可）
1009 -> HTTP 400（引擎拒绝，重试无意义）"""

DESIGN_ERR_NEW = """1001 bad_request      1002 not_found         1003 out_of_bounds
1004 queue_full       1005 read_only         1006 cursor_expired
1007 op_expired       1008 place_blocked     1009 place_invalid
1401 unauthorized     1403 forbidden         1429 rate_limited
1500 internal_error

1008 -> HTTP 409（footprint 被占，挪一格即可）
1009 -> HTTP 400（引擎拒绝，重试无意义）
1429 -> HTTP 429（令牌桶空了，默认 60/s、突发 200）"""

RULES = [
    (D / "API.md", [
        (API_OP_OLD, API_OP_NEW, "/control 的 op 列表标注 warp 禁用"),
        (API_TAIL_ANCHOR, API_TAIL_NEW, "warp 禁用说明 + 限流说明"),
    ]),
    (D / "DESIGN.md", [
        (DESIGN_ERR_OLD, DESIGN_ERR_NEW, "错误码表补 1429"),
    ]),
]


def main():
    bad = []
    for path, rules in RULES:
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
    print("文档已更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
