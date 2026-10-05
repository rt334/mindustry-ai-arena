#!/usr/bin/env python3
"""§八 结账（第二次）：蓝图往返与写队列预算都已验证。"""
import pathlib
import sys

T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")

OLD_START = "### 两项要如实说的"
OLD_END = "### 这个脚本自己犯的三个错（都已修）"

NEW = """### 两项补充验证（已做完）

`verify-all.py` 跑完后还剩两项，都用单独的脚本补上了。

**蓝图往返保真 —— 通过。** `drive/verify-blueprint-roundtrip.py`：

先在已知空地建 3 条带子 + 1 个 router，导出，再导到另一片空地，
然后**按位置和方块名逐个核对**（判据是状态，不是时长）：

```
导出 count=4  format=ai-arena-blueprint-json/1
导入 {"placed": 4, "skipped": 0, "total": 4}
位置+方块名都一致: 4/4
    ✓ (279,82) conveyor   ✓ (279,83) router
    ✓ (280,82) conveyor   ✓ (281,82) conveyor
```

上一轮 `verify-all.py` 里拿到 `placed:0` 是因为导回的位置被地形挡了 ——
端点给的拒绝是对的，只是那一次没证明「能重建」。这次换到确认过的空地，
**4/4 全部以正确的相对位置与方块名重建**。

**写队列每 tick 预算 —— 通过。** `drive/verify-write-budget.py`：
24 线程 × 8 秒并发写。

第一次跑**没测到**：5662 次里 7618 次（含重试）撞的是 `1429` 限流，
只有 166 次进到游戏线程 —— 瓶颈在令牌桶，不在写队列。
临时把 `rateLimit` 放宽（`perSecond=20000, burst=50000`，测完已还原并重启）后再跑：

```
(409, 1008)   5494   footprint ... blocked        （目标格已被占，属正常拒绝）
(200)          121
(504, 1007)     47   write queue budget exhausted for tick 55 (1.0 ms/tick); retry next tick
```

**1007 出现了**，消息与设计一致，说明按 tick 的计量与拒绝确实在工作。

> 这一项的价值不在于「通过」，而在于**第一次跑的时候它被限流掩盖了**。
> 如果只看到「没触发 1007」就记成「功能可能有问题」，会得到完全错误的结论；
> 如果看到「没触发」就记成「通过」，那就是假绿表。**必须先确认瓶颈在哪一层。**

### 这个脚本自己犯的三个错（都已修）"""


def main():
    t = T.read_text(encoding="utf-8")
    a = t.find(OLD_START)
    b = t.find(OLD_END)
    if a < 0 or b < 0 or b <= a:
        print(f"  !! 定位失败 a={a} b={b}")
        return 1
    T.write_text(t[:a] + NEW + t[b:], encoding="utf-8")
    print("  ✓ §八 已补写两项验证结果")
    return 0


if __name__ == "__main__":
    sys.exit(main())
