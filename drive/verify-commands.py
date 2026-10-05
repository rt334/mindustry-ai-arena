#!/usr/bin/env python3
"""8 种 /command action 的冒烟验证。

这些 action 的代码早就写了，但除了 move 之外从没实际调用过。判据不是
「每种都能成功」—— attackUnit 没有敌人当然会失败；判据是**每种都给出
结构化的、有意义的答复**，而不是 500 / 空 body / -1。

action 表（HttpApi.java:2745-2752）：
    move  attackUnit  assistBuilding  setCommand
    setStance  commandBuilding  requestItem  transferInventory
"""
import json
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])


def wait_ready(timeout=120):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            if any(b["block"].startswith("core") for b in a.buildings()):
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def call(action, **params):
    """返回 (ok, code, status, message)。"""
    try:
        r = a.post("command", action=action, **params)
        return True, 0, 200, json.dumps(r, ensure_ascii=False)[:160]
    except ArenaError as e:
        return False, e.code, getattr(e, "status", None), str(e.message)[:160]
    except Exception as e:
        return False, -2, None, f"{type(e).__name__}: {e}"


def main():
    if not wait_ready():
        print("等不到核心")
        return 1
    core = next(b for b in a.buildings() if b["block"].startswith("core"))
    cx, cy = core["x"], core["y"]
    units = a.units()
    if not units:
        print("没有单位")
        return 1
    u = units[0]
    uid = u["id"]
    print(f"核心 ({cx},{cy})   单位 #{uid} {u['type']} @({u['x']/8:.0f},{u['y']/8:.0f})")
    others = [x for x in units if x["id"] != uid]
    print(f"其它单位 {[(x['id'], x['type'], x['team']) for x in others]}\n")

    # 找一个能当目标的建筑（有 CommandAI 的更好，比如炮塔；这里先用核心）
    blds = a.buildings()
    cid = core.get("id")
    print(f"建筑 {len(blds)} 个   核心 id = {cid}")
    print(f"  （建筑 id 是这一轮新加的字段 —— 以前没有，导致 commandBuilding 谁都调不了）")
    print(f"  首个建筑的字段: {list(blds[0].keys())}\n")

    cases = [
        ("move",              dict(units=uid, x=cx + 6, y=cy + 6)),
        ("move(不传 units)",   dict(x=cx + 6, y=cy + 6)),
        ("move(传错参数名)",    dict(unit=uid, x=cx + 6, y=cy + 6)),
        ("attackUnit",        dict(units=uid, target=(others[0]["id"] if others else 99999))),
        ("assistBuilding",    dict(units=uid, x=cx, y=cy)),
        ("setCommand",        dict(units=uid, cmd="mine")),
        ("setCommand(乱写)",  dict(units=uid, cmd="not-a-command")),
        ("setStance",         dict(units=uid, stance="holdFire", enable=True)),
        ("setStance(乱写)",   dict(units=uid, stance="not-a-stance")),
        ("commandBuilding",   dict(units=uid, buildings=cid, x=cx, y=cy)),
        ("commandBuilding(无 buildings)", dict(units=uid, x=cx, y=cy)),
        ("requestItem",       dict(x=cx, y=cy, item="copper", amount=10)),
        ("transferInventory", dict(x=cx, y=cy)),
        ("乱写的 action",     dict(units=uid)),
    ]

    results = []
    for label, params in cases:
        if label == "乱写的 action":
            ok, code, status, msg = call("totallyBogus", **params)
        else:
            action = label.split("(")[0]
            ok, code, status, msg = call(action, **params)
        bad = (code == -2) or (status is not None and status >= 500) or (not ok and not msg)
        results.append((label, ok, code, status, msg, bad))
        flag = "  ✗ 服务端异常" if bad else ""
        print(f"  {label:<20} ok={str(ok):<5} code={code:<6} status={status}"
              f"  {msg[:90]}{flag}")
        time.sleep(0.25)

    print("\n== 小结 ==")
    broken = [r for r in results if r[5]]
    if broken:
        print("  以下调用让服务端异常或返回空响应：")
        for label, ok, code, status, msg, _ in broken:
            print(f"    {label}  code={code} status={status} msg={msg[:80]}")
    else:
        print("  8 种 action 全部给出结构化答复，没有 5xx / 空 body / 传输层错误")

    # 每种 action 是否都被识别（不是 unknown action）
    unknown = [r for r in results if "unknown action" in (r[4] or "") and "乱写" not in r[0]]
    if unknown:
        print("  下面这些 action 竟然没被识别：")
        for r in unknown:
            print(f"    {r[0]}  {r[4][:80]}")
    else:
        print("  所有 action 名都被识别（只有故意乱写的那条报 unknown）")

    # move 是否真的生效：看单位有没有动
    print("\n== move 是否真的生效 ==")
    before = (a.units() or [{}])[0]
    bx, by = before.get("x", 0) / 8, before.get("y", 0) / 8
    try:
        a.post("command", action="move", units=uid, x=cx + 14, y=cy + 14)
    except ArenaError as e:
        print(f"  move 被拒 {e.code} {e.message[:90]}")
    moved = None
    t0 = time.monotonic()
    while time.monotonic() - t0 < 20:
        now = (a.units() or [{}])[0]
        nx, ny = now.get("x", 0) / 8, now.get("y", 0) / 8
        d = ((nx - bx) ** 2 + (ny - by) ** 2) ** 0.5
        if d > 3:
            moved = d
            break
        time.sleep(0.5)
    print(f"  位移 {moved:.1f} 格" if moved else "  20 秒内没动")
    return 0 if not broken else 1


if __name__ == "__main__":
    sys.exit(main())
