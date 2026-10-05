#!/usr/bin/env python3
"""把 §八 的人工清单改成「跑一条命令」，并说明写队列预算那项仍需手工。"""
import pathlib
import subprocess
import sys

T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")

OLD = """### 下次启游戏时，按这个顺序补验

1. `python start.py check` → `play` → `status`（顺带验 `/ping` 的 `apiVersion`）
2. 读 `server-run/bridge-beta.json`，看有没有 `apiVersion`
3. 发一次 `/place`，看 `server-run/ai-arena-audit.jsonl` 有没有新行（这个已验过，回归用）
4. 录一段，读 `meta` 头看 `apiVersion`
5. 导出核心周边一块，再导回另一处，看 `placed` 与 `failureCodes`
6. 连 `/stream?since=0&seconds=10`，看事件、心跳、`end`
7. 并发打写请求，看写队列预算是否按 tick 拒绝

**前六项都是一分钟以内的事**；只有第 7 项需要造负载。"""

NEW = """### 下次启游戏时怎么补验

**一条命令**：

```
python start.py play      # 起局，等 /ping 通
python drive/verify-all.py
```

`drive/verify-all.py` 把上表 1–6 项做成了脚本，一次跑完给一张 PASS/FAIL 表。
每项独立，某一项失败不影响后面 —— 要的是整张表，不是第一个错就停。

它自己会在开头确认「到底有没有服务端可验」：没有就清楚地拒绝并给出下一步，
**而不是抛一堆栈让人猜**。这条失败路径已实测（服务端关着时 `exit=2`）。

**仍属手工的一项**：**写队列每 tick 预算** —— 它要造并发负载才有意义，
放进自动脚本只会造出一张「没测到东西」的假绿表。做法是并发打写请求，
看有没有按 tick 返回 1007。

> 为什么这份清单值得做成脚本：它原本是七个自然语言步骤，
> 而**没被执行的清单等于没有清单**。把它变成一条命令之后，
> 「哪天顺手验一下」和「哪天有空照着文档走一遍」是两件成本差很远的事。
> 这也正是第八节存在的理由 —— 让欠的账一眼看得见、一跑就能还。"""


def main():
    t = T.read_text(encoding="utf-8")
    if t.count(OLD) != 1:
        print(f"  !! 锚点 {t.count(OLD)} 次")
        return 1
    T.write_text(t.replace(OLD, NEW, 1), encoding="utf-8")
    print("  ✓ §八 已改为指向 verify-all.py")

    r = subprocess.run([sys.executable, "-m", "py_compile",
                        str(T.parent.parent / "drive" / "verify-all.py")],
                       capture_output=True, text=True)
    print("  ✓ verify-all.py 语法检查通过" if r.returncode == 0
          else f"  !! 语法错误: {r.stderr[:200]}")
    return 0 if r.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
