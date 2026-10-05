#!/usr/bin/env python3
"""把电力断开写进文档，并把「用户能看到什么」这条红线落成文字。

红线：报警只覆盖**肉眼可见**的现象 ——
  堵死（带子完全不动）、矿机不出货、电力条空 / 连线断。
不覆盖**减速瓶颈**（带子在动但慢），那要观察推导，不是看一眼就知道的。
"""
import pathlib
import sys

P = pathlib.Path(r"C:\dsh\ai-arena\docs\API.md")

KIND_OLD = """| `kind` | `beltStall` / `drillBlocked` / `factoryBlocked` / `missingInput` |"""

KIND_NEW = """| `kind` | `beltStall` / `drillBlocked` / `factoryBlocked` / `missingInput` / `powerUnconnected` / `powerStarved` |"""

CAUSE_OLD = """| 取值 | 含义 | 往哪查 |
|---|---|---|---|
| `starved` | 上游没把料送来（缺输入） | **上游** |
| `outputBlocked` | 自己有料且已满仓，出料侧不收 | **下游** |
| `outputRefused` | 出料侧不收，但自己还没满仓（刚堵上） | 下游 |
| `unknown` | 其它情况（电力、配方等），看 `missing` | 两者都不是 |"""

CAUSE_NEW = """| 取值 | 含义 | 往哪查 |
|---|---|---|---|
| `starved` | 上游没把料送来（缺输入） | **上游** |
| `outputBlocked` | 自己有料且已满仓，出料侧不收 | **下游** |
| `outputRefused` | 出料侧不收，但自己还没满仓（刚堵上） | 下游 |
| `unpowered` | 需要电，但**一根线都没接** | **查电网** |
| `underpowered` | 接了线，但电力不够（发电机不足 / 链路断） | **查电网** |
| `unknown` | 其它情况，看 `missing` | 两者都不是 |"""

TAIL_OLD = """> 这两者以前要靠 `outputAccepts` 和 `missing` 自己拼。典型误判是「核心满了 →
> 整条上游线回堵 → 上游钻机全部 `eff=0.0` 且满仓」，看着像产线坏了，
> 其实是**下游吃饱了**。"""

TAIL_NEW = """> 这两者以前要靠 `outputAccepts` 和 `missing` 自己拼。典型误判是「核心满了 →
> 整条上游线回堵 → 上游钻机全部 `eff=0.0` 且满仓」，看着像产线坏了，
> 其实是**下游吃饱了**。

#### 覆盖范围：只报「看一眼就知道」的

判据和**人类肉眼能看到的**对齐：

| 报 | 为什么 |
|---|---|
| `beltStall` | 带子**完全不动**——堵死了，一眼可见 |
| `drillBlocked` | 矿机**不出货**（钻头满仓转不动） |
| `powerUnconnected` / `powerStarved` | 电力条空 / 连线断，屏幕上直接显示 |
| `missingInput` | 方块停着，配方要什么、库里有没有，选中就能看 |

**不报**「这条链在减速」「吞吐上限只有 1.2/s」这类——那是**观察 + 推导**得出的，
游戏界面从不显示，得自己盯一段时间算出来。接口直接给就等于送答案。

同理 `beltStall` 的阈值是引擎的 `clogHeat` 逼近 1（约堵了一秒），
对应「肉眼确认它卡住了」，而不是「它比刚才慢了」。"""

RULES = [
    (KIND_OLD, KIND_NEW, "kind 表加两个电力值"),
    (CAUSE_OLD, CAUSE_NEW, "cause 表加 unpowered / underpowered"),
    (TAIL_OLD, TAIL_NEW, "补覆盖范围说明（红线落地）"),
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
