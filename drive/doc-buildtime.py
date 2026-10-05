#!/usr/bin/env python3
"""建造时间的文档收尾。"""
import pathlib
import sys

P = pathlib.Path(r"C:\dsh\ai-arena\docs\API.md")

PLACE_OLD = """**另注**：`ok:true` 只代表**请求已入队**，不代表建造完成；材料够 + 建造单位走到位置之后才会真正开工。"""

PLACE_NEW = """**另注**：`ok:true` 只代表**请求已入队**，不代表建造完成；材料够 + 建造单位走到位置之后才会真正开工。

### `/place` 的 `buildTime`：施工要多久

```json
{"buildTime":{"seconds":1.23,"buildCost":74.0,"builderSpeed":1.0}}
```

| 字段 | 含义 |
|---|---|
| `seconds` | **施工时长**（不含单位走过去的时间） |
| `buildCost` | 引擎的 `ConstructBuild.buildCost` |
| `builderSpeed` | 该建造单位的建造速度倍率 |

公式照抄引擎（`BuilderComp.java:246` + `ConstructBlock.java:451`）：

```
每帧增量 = type.buildSpeed × buildSpeedMultiplier × rules.buildSpeed(team) / buildCost
buildCost = block.buildTime × rules.buildCostMultiplier
seconds   = buildCost / (speed × 60)
```

**这是「规则」** —— 方块属性 + 单位速度，玩家看着进度条的涨速也能感知快慢。
**但它不含走路时间**：单位得先走到工地。真实耗时看 `/queue` 的 `etaSeconds`。

实测（gamma，speed=1）：`conveyor` 0.01s、`router` 0.1s、`silicon-smelter` 0.54s、
`scatter` 1.23s —— 和「由实测速率反推的总时长」吻合到 1%。"""

QUEUE_OLD = """| `constructing` / `progress` | **只在该格已在施工时出现**：施工进度 0~1 |"""

QUEUE_NEW = """| `constructing` / `progress` | **只在该格已在施工时出现**：施工进度 0~1 |
| `progressRate` / `etaSeconds` | 实测进度变化率（进度/秒）与据此外推的剩余秒数 |"""

ETA_TAIL_OLD = """判据是**进度连续不变、且建造单位自己也不动**，持续超过 3 秒。"""

ETA_TAIL_NEW = """判据是**进度连续不变、且建造单位自己也不动**，持续超过 3 秒。

#### `progressRate` / `etaSeconds`：还要多久

`progressRate` 是**实测**的进度涨速（两次采样之差 ÷ 时间），`etaSeconds` 由它外推：
`(1 - progress) / progressRate`。

**和 `buildTime.seconds` 是两个口径**：前者是理论施工时长、不含走路；
后者是从实际进度推出来的**剩余**时间，含已经被走掉的部分。
进度没在涨时 `etaSeconds` 不出现 —— 那时该看 `stuckSeconds`，而不是瞎估一个数。

实测 `scatter`（理论 1.23s）：

```
progress=0.24  rate=0.86  eta=1
progress=0.55  rate=0.95  eta=0
progress=0.99  rate=0.70  eta=0
⇒ 由速率反推的总时长 = [1.16, 1.23, 1.05, 1.25, 1.25, 1.43]
```

**这是「盯着进度条看它涨多快」**，真人抬眼就能做的事；接口只是把它自动化了。"""

RULES = [
    (PLACE_OLD, PLACE_NEW, "/place 的 buildTime"),
    (QUEUE_OLD, QUEUE_NEW, "/queue 的 progressRate / etaSeconds"),
    (ETA_TAIL_OLD, ETA_TAIL_NEW, "etaSeconds 的说明"),
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
    print("\nAPI.md 已更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
