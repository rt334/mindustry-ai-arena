#!/usr/bin/env python3
"""B3 的结论：不需要新接口，只需要写清楚怎么用现有接口做到。

按「人类在同一条件下能获取的信息」这条红线衡量：
  真人能做的 —— 框选若干单位，再下建造指令。
  对应到接口 —— 多次带 unit= 的 /place。**这已经够了。**
  真人做不到的 —— 让接口替他把计划均衡分派到多个单位。那反而是特供。

每个单位在引擎里本来就有自己的建造队列（BuilderComp），所以「多建造单位」
不是缺失的能力，是需要 AI 自己分派。
"""
import pathlib
import sys

P = pathlib.Path(r"C:\dsh\ai-arena\docs\API.md")

OLD = """### `/place` 的 `config`：随建造一起设"""

NEW = """### 多个建造单位

**引擎里每个单位有各自的建造队列**，而 `/place` 默认只把计划交给其中一个
（被接管的那个，否则第一个可建造的）。要驱动多个单位并行干活，自己分派：

1. `GET /units` 取所有 `canBuild=true` 的单位
2. 按距离或负载自行分配，逐个 `POST /place?unit=<id>&...`

**这和真人的操作一一对应** —— 玩家也是框选一部分单位、让它们建各自就近的房子，
而不是把所有单位都指向同一个工地。所以这里**没有**「自动均衡分派」的接口：
真人也做不到，那是特供。

**怎么让单位变多**：单位必须由工厂生产，`/spawn` 默认被禁用（见上文）：

```
建 ground-factory（或 air-factory / naval-factory）
  → 供电（发电机 + power-node 连线，相邻不会自动并网）
  → POST /config?x=<工厂x>&y=<工厂y>&value=<单位名>     选生产计划
  → 等它产出（轮询 /factory 的 currentPlan 与进度）
  → POST /command?action=move&units=<新单位id>&x=&y=     指挥它去工地
```

工厂只吃它的产线需要的材料，产线选错会一直停着 ——
`/factory` 会给出 `requirements` 和当前进度，不必猜。"""


def main():
    text = P.read_text(encoding="utf-8")
    n = text.count(OLD)
    if n != 1:
        print(f"!! {n} 次命中（应为 1），未写盘")
        return 1
    P.write_text(text.replace(OLD, NEW), encoding="utf-8")
    print("API.md：已补「多个建造单位」一节")
    return 0


if __name__ == "__main__":
    sys.exit(main())
