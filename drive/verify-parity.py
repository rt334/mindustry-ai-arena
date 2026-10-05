#!/usr/bin/env python3
"""验证本轮三处对等性修复：

1. 敌方建筑的库存被裁掉（DESIGN.md 4.4 那处「刻意偏离」的前提）
2. setup 不会泄漏规则改动（enemyCoreBuildRadius 等三项存了又还）
3. 顺带确认 /diag 的 rules 快照可用

第 2 条要靠「setup 前后对比」——因为规则值本身没有别的暴露途径。
"""
import json
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
adm = Arena("referee", toks["referee"])


def rules_of():
    d = adm.get("diag")
    return d.get("rules") or {}


def main():
    before = rules_of()
    print("== setup 前的规则 ==")
    for k, v in before.items():
        print(f"  {k:<22} {v}")

    # ---- 1. 库存裁剪 ----
    print("\n== 1. 敌方建筑库存是否被裁 ==")
    allb = adm.get("buildings", view="all").get("buildings", [])
    print(f"  view=all 共 {len(allb)} 个建筑")
    with_items = [b for b in allb if b.get("items")]
    print(f"    其中带 items 的 {len(with_items)} 个（admin 特权，应当全部带）")

    # 逐个队伍的视角对比
    for tid in (1, 2, 102, 103):
        try:
            tb = adm.get("buildings", view=tid).get("buildings", [])
        except ArenaError as e:
            print(f"  view={tid}: ERR {e.code}")
            continue
        mine = [b for b in tb if b.get("team") == tid and b.get("items")]
        other = [b for b in tb if b.get("team") != tid]
        other_with = [b for b in other if b.get("items")]
        print(f"  view={tid:<4} 共 {len(tb):>3} 个建筑 | "
              f"本队带 items {len(mine):>2} | "
              f"可见的敌方建筑 {len(other)}（其中带 items {len(other_with)}）")
        if other_with:
            print(f"    !! 泄漏：{[(b['x'], b['y'], b['block'], b['items']) for b in other_with[:3]]}")

    print("\n  说明：可见的敌方建筑大多为 0（开局各队相距 228 格，视野只有 61），")
    print("        所以这条主要靠上面的统计确认；有敌方建筑进视野时会自动受裁剪。")

    # ---- 2. setup 前后对比 ----
    print("\n== 2. setup 是否泄漏规则 ==")
    try:
        r = adm.post("setup", map="veins")
        print(f"  setup 完成: {json.dumps(r, ensure_ascii=False)[:120]}")
    except ArenaError as e:
        print(f"  setup ERR code={e.code} {e.message}")
        return 1

    after = rules_of()
    print("  setup 后的规则:")
    diffs = []
    for k in before:
        b, a = before.get(k), after.get(k)
        flag = "" if b == a else "   <<< 变了"
        if b != a:
            diffs.append((k, b, a))
        print(f"    {k:<22} {a}{flag}")

    if diffs:
        print(f"\n  ⇒ 有 {len(diffs)} 项在 setup 前后不一致：")
        for k, b, a in diffs:
            print(f"     {k}: {b} -> {a}")
    else:
        print(f"\n  ⇒ 全部一致，setup 没有泄漏规则改动")
    return 0


if __name__ == "__main__":
    sys.exit(main())
