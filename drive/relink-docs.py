#!/usr/bin/env python3
"""文档搬家后的引用修复。

把根目录的 md 收进 docs/ 之后，所有跨目录引用都要跟着改。
本脚本只做「字面替换」，每条规则都写死 old/new，跑完打印命中数 ——
命中 0 次的规则会报警，避免默默漏改。
"""
import pathlib
import sys

ROOT = pathlib.Path(r"C:\dsh\ai-arena")

TREE_OLD = """DESIGN.md                设计文档（含全部引擎发现与源码引用）
P0-VERIFICATION.md       技术验证报告（7 项原型验证）
P1-IMPLEMENTATION.md     最简闭环
P2-IMPLEMENTATION.md     对等约束
P3-IMPLEMENTATION.md     信息 API
P4-IMPLEMENTATION.md     操作 API
P5-IMPLEMENTATION.md     观战与裁判
P7-IMPLEMENTATION.md     编排（含 P6 录像摘要）"""

TREE_NEW = """docs/                    文档
  DESIGN.md              设计文档（含全部引擎发现与源码引用）
  API.md                 接口手册
  ENGINE-NOTES.md        引擎层说明（维护者文档）
  FEASIBILITY.md         目标可行性评估
  STRESS-TEST.md         压力测试报告
  PROMPTS.md             提示词与工作流约定
  phases/                P0~P7 分阶段实现报告
    P0-VERIFICATION.md   技术验证（7 项原型验证）
    P1-IMPLEMENTATION.md 最简闭环
    P2-IMPLEMENTATION.md 对等约束
    P3-IMPLEMENTATION.md 信息 API
    P4-IMPLEMENTATION.md 操作 API
    P5-IMPLEMENTATION.md 观战与裁判
    P7-IMPLEMENTATION.md 编排（含 P6 录像摘要）
  reviews/               产线攻坚复盘与接口提案
    REPORT.md            产线攻坚报告
    DEBUG-LOG.md         实战调试复盘
    FEATURE-REQUESTS.md  接口层改进提案
    REVIEW-ADDENDUM.md   对提案的核对与增补"""


def link(name):
    """docs/DESIGN.md 里指向 phases/ 的链接。"""
    return (f"]({name})", f"](phases/{name})")


EDITS = {
    "README.md": [
        ("](STRESS-TEST.md)", "](docs/STRESS-TEST.md)"),
        ("](API.md)", "](docs/API.md)"),
        ("](ENGINE-NOTES.md)", "](docs/ENGINE-NOTES.md)"),
        ("](FEASIBILITY.md)", "](docs/FEASIBILITY.md)"),
        ("**`API.md` 与 `skill/`", "**`docs/API.md` 与 `skill/`"),
        ("引擎实现层的知识归 `ENGINE-NOTES.md`", "引擎实现层的知识归 `docs/ENGINE-NOTES.md`"),
        (TREE_OLD, TREE_NEW),
    ],
    "docs/DESIGN.md": [
        link("P0-VERIFICATION.md"),
        link("P1-IMPLEMENTATION.md"),
        link("P2-IMPLEMENTATION.md"),
        link("P3-IMPLEMENTATION.md"),
        link("P4-IMPLEMENTATION.md"),
        link("P5-IMPLEMENTATION.md"),
        link("P7-IMPLEMENTATION.md"),
    ],
    "docs/phases/P0-VERIFICATION.md": [
        ("对应 `DESIGN.md` 第 9 节 P0", "对应 `../DESIGN.md` 第 9 节 P0"),
        ("印证了 DESIGN.md 的判断", "印证了 `../DESIGN.md` 的判断"),
        ("## 4. 对 DESIGN.md 的修正", "## 4. 对 `../DESIGN.md` 的修正"),
        ("DESIGN.md                     设计文档", "../DESIGN.md                设计文档"),
    ],
    "docs/phases/P1-IMPLEMENTATION.md": [
        ("对应 `DESIGN.md` 第 9 节 P1", "对应 `../DESIGN.md` 第 9 节 P1"),
        ("### 3.1 读写分离（DESIGN.md 5.2）", "### 3.1 读写分离（`../DESIGN.md` 5.2）"),
        ("与 DESIGN.md 4.5 一致", "与 `../DESIGN.md` 4.5 一致"),
        ("## 6. 对 DESIGN.md 的修正", "## 6. 对 `../DESIGN.md` 的修正"),
    ],
    "docs/phases/P2-IMPLEMENTATION.md": [
        ("对应 `DESIGN.md` 第 9 节 P2", "对应 `../DESIGN.md` 第 9 节 P2"),
        ("## 8. 对 DESIGN.md 的修正", "## 8. 对 `../DESIGN.md` 的修正"),
    ],
    "docs/phases/P3-IMPLEMENTATION.md": [
        ("对应 `DESIGN.md` 第 9 节 P3", "对应 `../DESIGN.md` 第 9 节 P3"),
        ("## 6. 对 DESIGN.md 的修正", "## 6. 对 `../DESIGN.md` 的修正"),
    ],
    "docs/phases/P4-IMPLEMENTATION.md": [
        ("对应 `DESIGN.md` 第 9 节 P4", "对应 `../DESIGN.md` 第 9 节 P4"),
        ("设计约束（DESIGN.md P4）", "设计约束（`../DESIGN.md` P4）"),
        ("## 6. 对 DESIGN.md 的修正", "## 6. 对 `../DESIGN.md` 的修正"),
    ],
    "docs/phases/P5-IMPLEMENTATION.md": [
        ("对应 `DESIGN.md` 第 9 节 P5", "对应 `../DESIGN.md` 第 9 节 P5"),
        ("DESIGN.md P5 里记的风险", "`../DESIGN.md` P5 里记的风险"),
        ("## 6. 对 DESIGN.md 的修正", "## 6. 对 `../DESIGN.md` 的修正"),
    ],
    "docs/phases/P7-IMPLEMENTATION.md": [
        ("对应 `DESIGN.md` 第 9 节 P7", "对应 `../DESIGN.md` 第 9 节 P7"),
        ("DESIGN.md P7 的验收标准", "`../DESIGN.md` P7 的验收标准"),
        ("DESIGN.md                  设计文档（含 9 项引擎发现）",
         "../DESIGN.md               设计文档（含 9 项引擎发现）"),
    ],
    "docs/ENGINE-NOTES.md": [
        ("见 `_work/REVIEW-ADDENDUM.md` 第一节", "见 `reviews/REVIEW-ADDENDUM.md` 第一节"),
    ],
    "docs/reviews/REVIEW-ADDENDUM.md": [
        ("我自己的 `ENGINE-NOTES.md` 里写的是", "我自己的 `../ENGINE-NOTES.md` 里写的是"),
    ],
    "skill/SKILL.md": [
        ("`ENGINE-NOTES.md`。", "`docs/ENGINE-NOTES.md`。"),
    ],
    "skill/README.md": [
        ("仓库的 `ENGINE-NOTES.md`（维护者文档", "仓库的 `docs/ENGINE-NOTES.md`（维护者文档"),
    ],
    "ai-client.py": [
        ("（DESIGN.md P4 的验收标准", "（`docs/DESIGN.md` P4 的验收标准"),
    ],
}


def main():
    bad = []
    for rel, rules in EDITS.items():
        p = ROOT / rel
        if not p.exists():
            bad.append(f"{rel}: 文件不存在")
            continue
        text = p.read_text(encoding="utf-8")
        hits = []
        for old, new in rules:
            n = text.count(old)
            if n == 0:
                hits.append(f"      !! 未命中: {old.splitlines()[0][:60]}")
                bad.append(f"{rel}: 规则未命中")
                continue
            text = text.replace(old, new)
            hits.append(f"      {n} 处  {old.splitlines()[0][:56]}")
        p.write_text(text, encoding="utf-8")
        print(f"  {rel}")
        print("\n".join(hits))
    print()
    if bad:
        print("有问题:")
        for b in bad:
            print("  " + b)
        return 1
    print("全部规则命中，无遗漏")
    return 0


if __name__ == "__main__":
    sys.exit(main())
