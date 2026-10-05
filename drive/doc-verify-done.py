#!/usr/bin/env python3
"""§八 结账：六项「只编译过」已实机验证。"""
import pathlib
import sys

T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")

OLD_START = "## 八、验证状态（第 12–19 轮新增改动的账）"
OLD_END = "### 下次启游戏时，按这个顺序补验"

NEW = """## 八、验证状态（第 12–19 轮新增改动的账）

**结账：已实机验证。** `python drive/verify-all.py` 一次跑完，12 项全过。

```
PASS 12 / FAIL 0 / SKIP 0
```

| 改动 | 验证程度 | 证据 |
|---|---|---|
| 审计日志 `Audit.java` | **实机验过** | 日志增长 1421→1572 B，末行是 `/place`；`/map` 不记 |
| 端口发现文件 | **实机验过** | `{"agent":"beta","apiVersion":"1.4","httpPort":7199,...}` |
| 接口版本号 `API_VERSION` | **实机验过** | `/ping` 返回 `apiVersion='1.4'` |
| 录像 `meta.apiVersion` | **实机验过** | 首行 `{"t":"meta","version":2,"apiVersion":"1.4",...}` |
| SSE `/stream` | **实机验过** | `hello` / `ev` / `cursor` / `end` 全部收到，468 字节 |
| 蓝图导入/导出 | **实机验过（部分）** | 导出 2 个方块、base64 180 字符、JSON 可解析；**导入那次 `placed:0`** —— 见下 |
| `/place` 的 `appliedRot` / `anchorX/Y` / `size` | 只编译过 | 本脚本没覆盖，仍是待验 |
| 写队列每 tick 预算 | 只编译过 | 要造并发负载才有意义，见下 |

### 两项要如实说的

**蓝图的导入没真正走通。** 导出对了，但导回时 `placed:0, skipped:2` ——
落在另一处被地形或视野挡了。端点**给了结构化的拒绝**（`failureCodes` 带具体格），
这本身是对的；但「导出去再导回来能重建」这件事**还没被证明**。
要证明得挑一块空地重试。

**写队列预算仍没验。** 它要并发负载；没有负载时它永远不会触发，
放进自动脚本只会造出一张「没测到东西」的假绿表。做法是并发打写请求，
看是否按 tick 返回 `1007`。

### 这个脚本自己犯的三个错（都已修）

写 `verify-all.py` 的过程中踩了三次，都是「看起来是功能坏了，其实是脚本错了」：

1. **没带 Authorization 头** —— `/ping` 不需要鉴权所以过了，其余全 401，
   表上像是「五个功能同时坏了」
2. **`/record` 用 beta token 却请求 `/v1/beta`** —— admin 的 token 与路径里的
   agent 必须一致，否则报「token 不属于该 agent」
3. **录像目录搜错** —— 写在 `Core.settings.getDataDirectory()/ai-arena-recordings/`，
   我去 `server-run/` 根目录找，报「没找到文件」

教训：**验证脚本自身的错误会伪装成被测对象的错误**，而且伪装得很像 ——
所以脚本第一件事就该是确认「前提成立」（服务端在不在、鉴权通不通），
再谈功能对不对。

### 下次启游戏时怎么补验"""


def main():
    t = T.read_text(encoding="utf-8")
    a = t.find(OLD_START)
    b = t.find(OLD_END)
    if a < 0 or b < 0 or b <= a:
        print(f"  !! 定位失败 a={a} b={b}")
        return 1
    T.write_text(t[:a] + NEW + t[b + len(OLD_END):], encoding="utf-8")
    print("  ✓ §八 已结账")
    return 0


if __name__ == "__main__":
    sys.exit(main())
