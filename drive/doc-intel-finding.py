#!/usr/bin/env python3
"""纠正 verify-intel.py 里我自己的错误判断，并把结论写进 TODO §三。"""
import pathlib
import sys

S = pathlib.Path(r"C:\dsh\ai-arena\drive\verify-intel.py")
T = pathlib.Path(r"C:\dsh\ai-arena\docs\TODO.md")

DOC_OLD = """`/intel` 的契约：单位在敌方核心视野内**连续 600 tick（10 秒）**才把该核心标成已知，
另有 30 tick 容差。此前从未跑通过，因为需要「先有产线造出有视野的单位」——
而 gamma 本来就有视野，直接开过去就行（当初的判断是多余的）。"""

DOC_NEW = """`/intel` 的契约：单位在敌方核心视野内**连续 600 tick（10 秒）**才把该核心标成已知，
另有 30 tick 容差。

**我在这份脚本的第一版里写错过一句**：以为「gamma 本来就有视野，直接开过去就行，
当初的判断是多余的」。实测反证 —— 把 gamma 开到敌方核心 **5 格**外，
请求周边 31x31 地图，**`visible=0`**，一片空白。

原因在 `ENGINE-NOTES.md` §二十八：只有 6 个快速飞行单位被显式设为 0，
**gamma 正是其中之一**。它跑得快，但看不见。

所以 `/intel` 的依赖是真的：**必须有 fogRadius > 0 的单位**。
链子是 煤+沙 → 硅冶炼厂 → air-factory → `poly`。
把单位开过去不够 —— 这个脚本现在的结论是「**这个前置不成立**」，
它本身仍有价值：把「为什么走不通」钉死在这里，省得下次再试一遍。"""

TODO_OLD = "| **`/intel` 状态机** | 需要单位在敌方核心视野内**连续 10 秒（600 tick）**。它是对等约"
TODO_NEW = "| **`/intel` 状态机** | **已定位前置，仍未验通**。实测把 gamma 开到敌方核心 5 格外，周边 31x31 的 `visible=0` —— **gamma 的 fogRadius 是 0**（`ENGINE-NOTES` §二十八：只有 6 个快速飞行单位被显式设为 0，gamma 是其中之一），跑得快但看不见。所以「必须有 fogRadius>0 的单位」这条依赖是真的，链子是 煤+沙 → 硅冶炼厂 → air-factory → `poly`。**当初的判断没错，是我中途想当然以为 gamma 能看见、白试了一轮。** 复现脚本 `drive/verify-intel.py`（它会自己报「前置不成立」）。原始说明：需要单位在敌方核心视野内**连续 10 秒（600 tick）**。它是对等约"


def main():
    s = S.read_text(encoding="utf-8")
    if s.count(DOC_OLD) == 1:
        S.write_text(s.replace(DOC_OLD, DOC_NEW, 1), encoding="utf-8")
        print("  ✓ verify-intel.py 的 docstring 已纠正")
    else:
        print(f"  !! 脚本 docstring 锚点 {s.count(DOC_OLD)} 次")

    t = T.read_text(encoding="utf-8")
    if t.count(TODO_OLD) == 1:
        T.write_text(t.replace(TODO_OLD, TODO_NEW, 1), encoding="utf-8")
        print("  ✓ TODO §三 /intel 行已更新")
    else:
        print(f"  !! TODO 锚点 {t.count(TODO_OLD)} 次")
        for ln in t.splitlines():
            if "/intel" in ln and "状态机" in ln:
                print("   实际:", ln[:110])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
