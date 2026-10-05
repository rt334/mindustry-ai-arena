#!/usr/bin/env python3
"""§四「/place 的失败码没有统计」—— 造出各类失败并真的数一遍。

TODO 原文：「这一轮造了多少次 1008 / 1009、哪些是误报，没有记录」。
关键是最后半句 —— **哪些是误报**。所以这份统计不只数码，还要把每类失败的
触发方式与「这个拒绝是否合理」一并写下来，否则数字本身没有用。

做法：对每一类失败**刻意构造**若干次，记录 (code, message)，然后人工判定
合理性（本脚本里写死判定理由，因为那需要理解语义，不能靠程序猜）。
"""
import collections
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

OUT = Path(r"C:\dsh\ai-arena\docs\place-failure-stats.md")


def main():
    toks, admin = load_tokens()
    a = Arena("beta", toks["beta"])
    ref = Arena("referee", admin)

    core = None
    t0 = time.monotonic()
    while time.monotonic() - t0 < 120:
        try:
            core = next((b for b in a.buildings() if b["block"].startswith("core")), None)
        except Exception:
            core = None
        if core:
            break
        time.sleep(1)
    if not core:
        print("等不到核心")
        return 1
    cx, cy = core["x"], core["y"]
    print(f"核心 ({cx},{cy})  {core['items']}")

    # 先看有哪些方块名可用（造「未知方块」用）
    try:
        c = a.get("content")
        blocks = {b["name"]: b for b in (c.get("blocks") or [])}
    except ArenaError:
        blocks = {}
    print(f"内容表 {len(blocks)} 个方块")

    # ── 构造各类失败 ──────────────────────────────────────────────────
    # 每类：(标签, 触发方式, 合理性判定)
    cases = [
        ("合法放置（对照组）", lambda: a.post("place", x=cx + 4, y=cy + 5,
                                            block="conveyor", rot=0),
         "应成功"),
        ("同格重复放置", lambda: a.post("place", x=cx + 4, y=cy + 5,
                                      block="conveyor", rot=0),
         "合理 —— 那格已经有方块/计划"),
        ("核心脚下（footprint 被占）", lambda: a.post("place", x=cx, y=cy + 3,
                                                  block="conveyor", rot=0),
         "合理 —— 核心占着"),
        ("未知方块名", lambda: a.post("place", x=cx + 8, y=cy + 8,
                                    block="totally-not-a-block", rot=0),
         "合理 —— 名字不存在"),
        ("飞出世界边界", lambda: a.post("place", x=-50, y=-50,
                                     block="conveyor", rot=0),
         "合理 —— 坐标越界"),
        ("出己方视野（远处）", lambda: a.post("place", x=20, y=20,
                                           block="conveyor", rot=0),
         "合理 —— 看不见就不能建"),
        ("材料不足（要硅的方块）", lambda: a.post("place", x=cx + 6, y=cy + 7,
                                              block="solar-panel", rot=0),
         "**要看** —— 材料不足是「排队后卡住」还是「直接拒」？"),
        ("rot 越界（rot=9）", lambda: a.post("place", x=cx + 9, y=cy + 5,
                                           block="conveyor", rot=9),
         "**要看** —— 引擎怎么处理越界朝向"),
    ]

    tally = collections.OrderedDict()
    print("\n== 逐类触发 ==")
    for label, fn, judge in cases:
        try:
            r = fn()
            code, msg = 0, json.dumps(r, ensure_ascii=False)[:150]
        except ArenaError as e:
            code, msg = e.code, str(e.message)[:150]
        tally[label] = (code, msg, judge)
        print(f"  {label:<26} code={code:<6} {msg[:88]}")
        time.sleep(0.3)

    # ── 汇总 ──────────────────────────────────────────────────────────
    print("\n== 统计 ==")
    by_code = collections.Counter(c for c, _, _ in tally.values())
    for code, n in sorted(by_code.items()):
        name = {0: "成功", 1001: "参数错", 1002: "未知名", 1003: "越界",
                1004: "批量/上限", 1005: "不可用/不可见", 1008: "footprint 被占",
                1009: "放置非法"}.get(code, "?")
        print(f"  {code:<6} {name:<16} {n} 次")

    NAMES = {0: "成功", 1001: "参数错", 1002: "未知方块/动作", 1003: "坐标越界",
             1004: "批量或上限", 1005: "不可见/不可用", 1007: "写队列预算",
             1008: "footprint 被占", 1009: "放置非法", 1429: "限流"}
    # ── 写报告 ────────────────────────────────────────────────────────
    lines = ["# `/place` 失败码统计", "",
             "由 `drive/collect-place-failures.py` 实机跑出，不是估的。",
             "「合理性」那一列是人工判定 —— 只数码没有用，要看**这个拒绝该不该发生**。",
             "", f"- 时间：{time.strftime('%Y-%m-%d %H:%M')}",
             f"- 核心：({cx},{cy})，库存 {json.dumps(core['items'], ensure_ascii=False)}",
             "", "| 触发方式 | HTTP/code | 响应（截断） | 合理性判定 |",
             "|---|---|---|---|"]
    for label, (code, msg, judge) in tally.items():
        m = msg.replace("|", "\\|")[:110]
        lines.append(f"| {label} | `{code}` | `{m}` | {judge} |")
    lines += ["", "## 码表", "", "| code | 含义 | 次数 |", "|---|---|---|"]
    for code, n in sorted(by_code.items()):
        lines.append("| `%d` | %s | %d |" % (code, NAMES.get(code, "?"), n))
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n已写出 {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
