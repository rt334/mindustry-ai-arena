#!/usr/bin/env python3
"""把蓝图导入/导出记进 API.md 与 TODO。"""
import pathlib
import sys

T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")
A = pathlib.Path(r"C:\dsh\ai-arena\docs\API.md")

TODO_OLD = "| 蓝图导入 | DESIGN.md 402–426 给了 `readBase64` → 逐格 `BuildPlan` 的路径 | 18（现 33）个端点里没有 |"
TODO_NEW = ("| 蓝图导入 | DESIGN.md 402–426 给了 `readBase64` → 逐格 `BuildPlan` 的路径 | "
            "**已实现（未运行时验证），但换了格式**：`GET/POST /v1/{agent}/blueprint`，"
            "用我们自己的显式 JSON（base64 装在 `data=` 里），**不是 `.msch` 二进制**——"
            "没有参考实现时照猜写解析器，只会产出「看着像对、其实错位」的东西。"
            "`.msch` 读取器仍未实现。 |")

API_SECTION = """

---

## 蓝图导入 / 导出

```
GET  /v1/{agent}/blueprint?x=&y=&w=&h=          导出该矩形区域
POST /v1/{agent}/blueprint?x=&y=&data=<base64>  把蓝图放在 (x,y)
```

**为什么有用**：这张图**每局重新随机**（矿脉位置全变），所以布局本来没法跨局
复用。有了它，一局调好的产线可以存下来、下一局搬到新地形上。

### 格式

**我们自己的显式 JSON，不是 Mindustry 的 `.msch` 二进制。**

DESIGN.md 402–426 给的是 `readBase64` → 逐格 `BuildPlan` 那条路。没走它的原因：
`.msch` 是 base64 包着一段自定义二进制（format 字节 + version + tags + tiles），
在没有参考实现的情况下照猜写解析器，产出的是「看着像对、其实错位」的东西。
显式 JSON 可读、可手改、可离线校验，先要可靠再说兼容。

```json
{"v":1,"w":24,"h":12,"count":37,
 "blocks":[{"dx":0,"dy":0,"block":"conveyor","rot":0},
           {"dx":2,"dy":0,"block":"mechanical-drill","rot":0}]}
```

base64 编码后放进 `data=`。导出返回里带 `format: "ai-arena-blueprint-json/1"`。

### 导出

```json
{"x":265,"y":118,"w":24,"h":12,"count":37,
 "data":"eyJ2IjoxLCJ3IjoyNC...",
 "format":"ai-arena-blueprint-json/1",
 "message":"exported 37 block(s)"}
```

多格方块**只在锚点记一次**（否则导入时会重复放）。

### 导入

坐标按 `(dx,dy)` 相对 `x,y` 平移。响应：

```json
{"placed":35, "skipped":2, "total":37,
 "firstFailureTile":<编码后的格坐标>,
 "failureCodes":"(293,120)=1008 (294,120)=1008 ",
 "message":"blueprint: placed 35/37, skipped 2 (see failureCodes)"}
```

`skipped` **不是静默丢弃**：每条失败都带错误码与具体格，`failureCodes` 还做了
长度截断（最多 240 字符）免得响应被刷爆。全部失败时返回 `1005`。

> **验证状态**：已编译进 mod，**尚未在实机上跑过**。按当前轮次要求没有启动
> 游戏，所以导入/导出的实际行为是按代码写的，不是实测的。
> 特别是「多格方块只记锚点」这条，只做了静态推理，没验过。
"""


def main():
    ok = True
    t = T.read_text(encoding="utf-8")
    if t.count(TODO_OLD) == 1:
        T.write_text(t.replace(TODO_OLD, TODO_NEW, 1), encoding="utf-8")
        print("  ✓ TODO §2.2 蓝图行已更新")
    else:
        print(f"  !! TODO 锚点 {t.count(TODO_OLD)} 次")
        ok = False

    a = A.read_text(encoding="utf-8")
    if "## 蓝图导入 / 导出" in a:
        print("  · API.md 已有该节")
    else:
        A.write_text(a.rstrip() + API_SECTION, encoding="utf-8")
        print("  ✓ API.md 追加蓝图一节")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
