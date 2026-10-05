#!/usr/bin/env python3
"""验证录像补齐的四样：mapData / rot / removed / items。

做法：起录制 → 让对局跑一会儿（AI 在建东西）→ 停录制 → 直接读文件核对。

这条验证本身就是 TODO 2.1 的第一步：**JSONL 里的数据到底够不够画**。
之前读旧录像的结论是「不够，差四样」，这次核实补完之后够不够。
"""
import json
import os
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])
adm = Arena("referee", toks["referee"])
REC_DIR = r"C:\dsh\ai-arena\server-run\config\ai-arena-recordings"


def main():
    # ---- 起录制（/record 需要 admin token）----
    print("== 起录制 ==")
    try:
        r = adm.post("record", action="start", label="verify")
        print(f"  {json.dumps(r, ensure_ascii=False)[:160]}")
    except ArenaError as e:
        print(f"  ERR code={e.code} {e.message}")
        return 1

    # ---- 让对局跑一会儿：等 AI 真的建点东西出来 ----
    print("\n== 等对局产生变化（看核心数量，最多 90 秒）==")
    t0 = time.monotonic()
    while time.monotonic() - t0 < 90:
        bs = a.buildings()
        if len(bs) >= 4:
            break
        time.sleep(2)
    print(f"  当前可见建筑 {len(a.buildings())} 个，跑了 {time.monotonic()-t0:.0f}s")

    # ---- 停录制 ----
    print("\n== 停录制 ==")
    try:
        r = adm.post("record", action="stop")
        print(f"  {json.dumps(r, ensure_ascii=False)[:160]}")
    except ArenaError as e:
        print(f"  ERR code={e.code} {e.message}")
        return 1

    # ---- 找最新的录像文件 ----
    files = sorted(
        (os.path.join(REC_DIR, f) for f in os.listdir(REC_DIR) if f.endswith(".jsonl")),
        key=os.path.getmtime, reverse=True)
    if not files:
        print("找不到录像文件")
        return 1
    path = files[0]
    size = os.path.getsize(path)
    print(f"\n== 新录像 ==")
    print(f"  {os.path.basename(path)}  {size:,} B")

    with open(path, encoding="utf-8") as fh:
        lines = [json.loads(l) for l in fh if l.strip()]

    kinds = {}
    for j in lines:
        kinds[j.get("t")] = kinds.get(j.get("t"), 0) + 1
    print(f"  类型分布: {kinds}")

    meta = next((j for j in lines if j.get("t") == "meta"), None)
    snaps = [j for j in lines if j.get("t") == "snap"]

    print("\n== 逐项核对 ==")
    ok = True

    # 1) mapData
    md = (meta or {}).get("mapData")
    if not md:
        print("  [1] mapData        !! 缺失")
        ok = False
    else:
        fl, ors, wls = md.get("floors"), md.get("ores"), md.get("walls")
        md_bytes = len(json.dumps(md))
        print(f"  [1] mapData        OK  {md.get('w')}x{md.get('h')}  "
              f"floors {len(fl)//2 if fl else 0} 段 / ores {len(ors or [])} 格 / "
              f"walls {len(wls or [])} 格  ≈{md_bytes:,} B")
        # 抽查 RLE 的段长之和是否等于总格数
        if fl:
            total = sum(fl[i] for i in range(1, len(fl), 2))
            expect = md.get("w", 0) * md.get("h", 0)
            flag = "OK" if total == expect else f"!! 段长合计 {total} != {expect}"
            print(f"      RLE 段长合计 {total} / 期望 {expect}  {flag}")
            if total != expect:
                ok = False

    # 2) rot
    with_rot = [b for s in snaps for b in (s.get("builds") or []) if "rot" in b]
    all_builds = [b for s in snaps for b in (s.get("builds") or [])]
    if not all_builds:
        print("  [2] builds[].rot  -- 本段没有建筑变化，无法核对")
    elif len(with_rot) == len(all_builds):
        print(f"  [2] builds[].rot  OK  {len(with_rot)}/{len(all_builds)} 条带 rot")
    else:
        print(f"  [2] builds[].rot  !! 只有 {len(with_rot)}/{len(all_builds)} 条带 rot")
        ok = False

    # 3) removed
    has_removed = all("removed" in s for s in snaps)
    total_removed = sum(len(s.get("removed") or []) for s in snaps)
    if has_removed:
        print(f"  [3] removed       OK  每条 snap 都有该字段（本段共记录 {total_removed} 次拆除）")
    else:
        print("  [3] removed       !! 缺失")
        ok = False

    # 4) items（可选，没做不算失败）
    with_items = [b for b in all_builds if "items" in b]
    print(f"  [4] builds[].items {'OK  ' + str(len(with_items)) + ' 条' if with_items else '（未做，可选）'}")

    # ---- 换个角度：拿这份录像算一下「画一帧需要多少数据」 ----
    print("\n== 画一帧的可行性 ==")
    if snaps:
        avg = sum(len(json.dumps(s)) for s in snaps) / len(snaps)
        print(f"  平均每条 snap {avg:,.0f} B；全量帧单位 {len(snaps[0].get('units') or [])} 个、"
              f"建筑 {len(snaps[0].get('builds') or [])} 个")
    if md:
        print(f"  地图一次性 {len(json.dumps(md)):,} B（不随帧增长）")
        print(f"  结论：{'够画' if ok else '还差'} —— "
              f"地图 + 单位全量 + 建筑增量 + 拆除记录，四样齐了就能重建成任何一帧")
    print(f"\n  ⇒ {'四样齐全' if ok else '仍有缺失'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
