#!/usr/bin/env python3
"""对照 /command?action=move 与 /control?op=order —— 谁能真的让单位动。

疑点：/command?action=move 返回 "commanded 1 unit(s) to position"，
但单位 20 秒没动。而单位的 controller 是 Player#218 ——
AIArena.java 里记着「gamma 被影子 AI 玩家持有，而影子玩家永远不发移动输入」。

那么：玩家持有的单位是不是根本不理会 AI 下达的指挥？如果是，
/command?action=move 就是个「回成功但不生效」的接口，必须写进文档或改掉。
"""
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])


def pos():
    u = (a.units() or [None])[0]
    if not u:
        return None
    return u["id"], u["x"] / 8, u["y"] / 8, u.get("controller")


def wait_move(tag, tgt, timeout=14):
    p0 = pos()
    if not p0:
        print(f"  {tag}: 没单位")
        return None
    _, x0, y0, ctrl = p0
    best = 0.0
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        p = pos()
        if p:
            _, x, y, _ = p
            d = ((x - x0) ** 2 + (y - y0) ** 2) ** 0.5
            best = max(best, d)
            if d > 4:
                break
        time.sleep(0.4)
    print(f"  {tag:<34} 位移 {best:5.2f} 格  controller={ctrl}")
    return best


def main():
    u = (a.units() or [None])[0]
    if not u:
        print("没有单位")
        return 1
    core = next(b for b in a.buildings() if b["block"].startswith("core"))
    cx, cy = core["x"], core["y"]
    uid = u["id"]
    print(f"单位 #{uid} {u['type']}  controller={u.get('controller')}")
    print(f"核心 ({cx},{cy})\n")

    print("== A. /command?action=move 到 (cx+18, cy+14) ==")
    try:
        r = a.post("command", action="move", units=uid, x=cx + 18, y=cy + 14)
        print(f"  应答 {r}")
    except ArenaError as e:
        print(f"  被拒 {e.code} {e.message[:100]}")
    wait_move("move 之后", (cx + 18, cy + 14))

    print("\n== B. /control?op=order 到 (cx-18, cy+14) ==")
    try:
        r = a.post("control", op="order", unit=uid, x=cx - 18, y=cy + 14)
        print(f"  应答 {r}")
    except ArenaError as e:
        print(f"  被拒 {e.code} {e.message[:100]}")
    wait_move("order 之后", (cx - 18, cy + 14))

    print("\n== C. 再试 move，但目标就在脚边（1 格）==")
    p = pos()
    if p:
        _, px, py, _ = p
        try:
            r = a.post("command", action="move", units=uid, x=px + 3, y=py)
            print(f"  应答 {r}")
        except ArenaError as e:
            print(f"  被拒 {e.code} {e.message[:100]}")
        wait_move("move 近距离", (px + 3, py))

    print("\n== D. 单位的指令状态 ==")
    try:
        r = a.post("control", op="orders")
        print(f"  /control?op=orders → {str(r)[:300]}")
    except ArenaError as e:
        print(f"  被拒 {e.code} {e.message[:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
