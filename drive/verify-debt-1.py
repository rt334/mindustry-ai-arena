#!/usr/bin/env python3
"""验证债务 batch 1（第三版）：stuckReason / 批量上限 / queue?clear / 429 语义。

前两版的教训：
  · 限速。密集请求会被自己的限流打回 429（这本身说明限流生效），
    但脚本把它读成「候选点全被拒」，白跑一轮。这里每步之间留间隔。
  · 读对字段。批量响应里的 tiles 是**请求数**，接受数在 accepted。
    修完接口后这两者都明确给出来了。
  · 别自己从 /map 猜空地。让引擎判：拿一串候选点挨个试。
"""
import json
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])

GAP = 0.06          # 每次请求之间留间隔，60/s 的限流下绰绰有余


def pause():
    time.sleep(GAP)


def core_of():
    return next(b for b in a.buildings() if b["block"].startswith("core"))


def wait_ready(timeout=90):
    """等快照就绪。刚重启时 /buildings 会是空的（snapshotFresh=False），
    直接读会 StopIteration —— 这是采样时机问题，不是接口问题。"""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            bs = a.buildings()
        except Exception:
            bs = []
        if any(b["block"].startswith("core") for b in bs):
            return True
        time.sleep(1)
    return False


def main():
    if not wait_ready():
        print("90 秒内没等到核心出现在快照里")
        return 1
    core = core_of()
    cx, cy = core["x"], core["y"]
    print(f"核心 ({cx},{cy})  {core['items']}")
    st = a.state()
    print(f"limits = {json.dumps(st.get('limits'), ensure_ascii=False)}\n")
    ok = {}

    # ── 1. stuckReason = missingMaterials ──────────────────────────────
    print("== 1. stuckReason=missingMaterials ==")
    print("  shock-mine 是 1x1，成本 铅25+硅12；核心硅 0 → 必然卡在缺硅")
    placed = None
    for dy in (3, 4, 5, 6, -3, -4):
        for dx in (1, -1, 2, -2, 0):
            x, y = cx + dx, cy + dy
            try:
                r = a.post("place", x=x, y=y, block="shock-mine", rot=0)
            except ArenaError as e:
                print(f"    ({x},{y}) {e.code}: {e.message[:70]}")
                pause()
                continue
            m = r.get("materials") or {}
            print(f"    ✓ 下单 ({x},{y})  adequate={m.get('adequate')}")
            print(f"      requirements = {json.dumps(m.get('requirements'), ensure_ascii=False)}")
            placed = (x, y)
            break
        if placed:
            break
        pause()

    if not placed:
        ok["missingMaterials"] = False
        print("    没找到能下单的位置")
    else:
        print("    等 stuckReason 出现（判据是状态，不是时长）……")
        got, t0 = None, time.monotonic()
        while time.monotonic() - t0 < 30:
            q = a.queue()
            for b in (q.get("builders") or []):
                for p in (b.get("planList") or []):
                    if p.get("stuckReason"):
                        got = p
                        break
                if got:
                    break
            if got:
                break
            time.sleep(1)
            pause()
        if got:
            print(f"    ✓ ({got.get('x')},{got.get('y')}) {got.get('block')}")
            print(f"      stuckSeconds = {got.get('stuckSeconds')}")
            print(f"      stuckReason  = {got.get('stuckReason')}")
            print(f"      hint         = {got.get('hint')}")
            ok["missingMaterials"] = str(got.get("stuckReason", "")).startswith("missingMaterials")
        else:
            print("    ✗ 30 秒内没出现 stuckReason")
            ok["missingMaterials"] = False

    # ── 2. /queue?clear=true ───────────────────────────────────────────
    print("\n== 2. /queue?clear=true ==")
    pause()
    try:
        r = a.post("queue", clear="true")
        print(f"  响应 {json.dumps(r, ensure_ascii=False)[:200]}")
        n = r.get("cleared")
        ok["clear"] = isinstance(n, int) and n > 0
        print(f"  cleared = {n}（类型 {type(n).__name__}）"
              f"  → {'✓ 结构化字段可用' if ok['clear'] else '✗ 仍读不到'}")
    except ArenaError as e:
        print(f"  ERR code={e.code} {e.message[:160]}")
        ok["clear"] = False
    pause()
    q = a.queue()
    left = sum(len(b.get("planList") or []) for b in (q.get("builders") or []))
    print(f"  复核：队列剩余 {left} 条")

    # ── 3. 批量上限：请求 70 应只接受 60 ───────────────────────────────
    print("\n== 3. 批量上限（MAX_PLANS_PER_UNIT = 60）==")
    pause()
    y = cy + 20
    try:
        r = a.post("place", shape="line", x1=cx - 35, y1=y, x2=cx + 34, y2=y,
                   block="conveyor")
        print(f"  70 格批量 → {json.dumps(r, ensure_ascii=False)[:240]}")
        req, acc = r.get("requested"), r.get("accepted")
        print(f"    requested={req}  accepted={acc}  tiles={r.get('tiles')}")
        print(f"    limitReached={r.get('limitReached')}  plansPerUnit={r.get('plansPerUnit')}")
        print(f"    skipped={json.dumps(r.get('skipped'), ensure_ascii=False)}")
        ok["batchCap"] = (req == 70 and acc == 60 and r.get("limitReached") is True)
    except ArenaError as e:
        print(f"  70 格 → code={e.code} {e.message[:200]}")
        ok["batchCap"] = False

    # 复核：队列里实际有多少条
    pause()
    q = a.queue()
    total = sum(len(b.get("planList") or []) for b in (q.get("builders") or []))
    print(f"  复核：队列实际 {total} 条  {'✓ 与 accepted 一致' if total == 60 else '← 与 accepted 不符'}")

    # 清掉，别留着
    pause()
    try:
        r = a.post("queue", clear="true")
        print(f"  清队列 → cleared={r.get('cleared')}")
    except ArenaError as e:
        print(f"  清队列失败 {e.code}")

    # ── 4. 429 应报 1429 而不是 -1 ─────────────────────────────────────
    print("\n== 4. 限流耗尽后报什么码 ==")
    print("  连打 /state（有效端点；打 /ping 会返回 1002 而碰不到限流器）")
    a2 = Arena("beta", toks["beta"])
    a2.max_retries = 2          # 别退避太久
    limited = 0
    last_code = None
    for i in range(700):
        try:
            a2.get("state")
        except ArenaError as e:
            last_code = e.code
            limited += 1
            if limited <= 2:
                print(f"    第 {i} 次 → code={e.code}  {e.message[:90]}")
        except Exception as e:
            print(f"    第 {i} 次 → {type(e).__name__}: {e}")
            break
    if last_code is not None:
        ok["rateCode"] = (last_code == 1429)
        print(f"  共触发 {limited} 次；末次 code={last_code}"
              f"  → {'✓ 如实报 1429' if ok['rateCode'] else '✗ 仍是 ' + str(last_code)}")
    else:
        ok["rateCode"] = None
        print("  一轮没打满配额（说明限流没生效，或 quota 比预期大）")

    print("\n== 小结 ==")
    for k, v in ok.items():
        mark = "✓" if v else ("--" if v is None else "✗")
        print(f"  {k:<20} {mark}")
    return 0 if all(v for v in ok.values() if v is not None) else 1


if __name__ == "__main__":
    sys.exit(main())
