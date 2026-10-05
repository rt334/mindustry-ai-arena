#!/usr/bin/env python3
"""给 TODO 加一节「验证状态」：把最近几轮的改动按验证程度分清楚。

动机很直接：第 12–19 轮在不启游戏的约束下加了一批东西（审计、发现文件、
写队列预算、SSE、蓝图、版本号、溯源、start.py），其中**只有两项在实机上
验过**。如果不把这件事写下来，后来人读 TODO 会以为它们都完成了 ——
而这正是 reviews/ 那批复盘反复警告的失败模式。
"""
import pathlib
import sys

T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")

SECTION = """

---

## 八、验证状态（第 12–19 轮新增改动的账）

**为什么要单列**：那几轮在「不启游戏」的约束下加了一批东西，其中只有两项
在实机上跑过。不写下来，后来人读这份 TODO 会以为它们都完成了 ——
而 `reviews/` 那批复盘反复警告的正是这个：**「看起来完成、实际没人跑过」。**

| 改动 | 验证程度 | 证据 / 缺什么 |
|---|---|---|
| 审计日志 `Audit.java` | **实机验过** | `/place` 记了、`/map` 没记，日志内容逐字核对过 |
| 端口发现文件 `bridge-*.json` | **实机验过** | 5 个 agent 各一份，内容核对过 |
| 写队列每 tick 预算 | 只编译过 | 缺：并发写压测，看 1007 是否按预期出现、主线程是否真的没被按住 |
| SSE `/stream` | 只编译过 | 缺：连上去看事件逐条推送、心跳、1006 重同步、并发上限 8 是否生效 |
| 蓝图导入/导出 | 只编译过 | 缺：导出一段真实产线再导回去；特别是「多格方块只记锚点」只做了静态推理 |
| 接口版本号 `API_VERSION` | 只编译过 | 缺：`/ping` 实际返回里有没有 `apiVersion` |
| 录像 `meta.apiVersion` | 只编译过 | 缺：录一段再看头里有没有这个字段 |
| `start.py` | **部分验过** | `check` / `status` / `--help` 实测；`play` / `watch` 未跑（会启游戏） |
| `ENGINE-NOTES` 的 rot 勘误 | 文档 | 无需运行验证 |
| §七 甄别、§六 边界 | 文档 | 无需运行验证 |

### 下次启游戏时，按这个顺序补验

1. `python start.py check` → `play` → `status`（顺带验 `/ping` 的 `apiVersion`）
2. 读 `server-run/bridge-beta.json`，看有没有 `apiVersion`
3. 发一次 `/place`，看 `server-run/ai-arena-audit.jsonl` 有没有新行（这个已验过，回归用）
4. 录一段，读 `meta` 头看 `apiVersion`
5. 导出核心周边一块，再导回另一处，看 `placed` 与 `failureCodes`
6. 连 `/stream?since=0&seconds=10`，看事件、心跳、`end`
7. 并发打写请求，看写队列预算是否按 tick 拒绝

**前六项都是一分钟以内的事**；只有第 7 项需要造负载。
"""


def main():
    t = T.read_text(encoding="utf-8")
    if "## 八、验证状态" in t:
        print("  · 已有该节，跳过")
        return 0
    T.write_text(t.rstrip() + SECTION, encoding="utf-8")
    print("  ✓ TODO 追加「八、验证状态」")
    return 0


if __name__ == "__main__":
    sys.exit(main())
