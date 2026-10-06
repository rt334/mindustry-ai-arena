#!/usr/bin/env python3
"""验证 /intel 端到端 —— 用裁判 spawn 绕开产线前置。

**契约**（DESIGN.md §6.2）：单位在敌方核心视野内**连续 600 tick（10 秒）**、
容错 30 tick，才把该核心由 `unknown` 标成 `confirmed`（此后永久保留快照）。

**上一版卡在哪（保留作证）**：用队伍默认的 `gamma` 去侦察 —— 它 `fogRadius = 0`
（ENGINE-NOTES §二十八：56 个单位里只有 6 个被显式设为 0，`gamma` 正是其一），
把它开到敌方核心 **5 格**外，`/map` 依然全 `visible=0`。
所以「煤+沙 → 硅冶炼厂 → air-factory → `poly`」这条链是**真的**。

**但验证状态机不必先把产线做出来**：带 `-Darena.allowspawn=true` 起服务器后，
裁判可以用 `team=` 把单位直接放到任意位置（`HttpApi:684` 给坐标时不做视野检查）。
于是本脚本改成：

  1. admin 查全图建筑 → 找到**敌方核心**的真实坐标（不再写死）
  2. admin spawn 一个 `poly`（`fogRadius > 0`）到敌核心旁边，指定它属于被测那队
  3. 轮询被测队的 `/units` 确认它确有视野半径
  4. 轮询 `/intel`，记录 `unknown → confirmed` 的 tick 轨迹

前置：
  - 服务器带 `-Darena.allowspawn=true` 起，且已设 `ARENA_ADMIN_TOKEN`
  - 已经 setup 过一局（referee）

用法：python drive/verify-intel.py [--agent beta]
"""
import argparse
import json
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_admin_token, load_own_token   # noqa: E402

WATCH_TICKS = 600          # 契约：连续可见 10 秒
TOLERANCE = 30             # 契约：容差 0.5 秒


def find_enemy_core(admin: Arena, my_team: int):
    """从裁判视角找敌方核心（返回 (x, y, team, name)）。"""
    r = admin.get("buildings", view="all")
    items = r if isinstance(r, list) else (r.get("buildings") or [])
    for b in items:
        # API.md §`GET /buildings`：方块名的字段叫 `block`，不叫 `name`
        name = str(b.get("block") or b.get("name") or "")
        team = b.get("team")
        if name.startswith("core") and team is not None and int(team) != int(my_team):
            return int(b["x"]), int(b["y"]), int(team), name
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="beta")
    args = ap.parse_args()

    admin = Arena("referee", load_admin_token())
    a = Arena(args.agent, load_own_token(args.agent))

    # --- 自己的队伍 ---
    st = a.state()
    my_team = None
    self_info = st.get("self") or {}
    my_team = self_info.get("id", self_info.get("teamId"))
    if my_team is None:
        print("拿不到自己的队伍 id，/state 结构可能变了：", json.dumps(self_info)[:200])
        return 1
    print(f"被测队伍 {args.agent} = team {my_team}   tick={st.get('tick')}")

    # --- 1. 找敌方核心 ---
    core = find_enemy_core(admin, my_team)
    if not core:
        print("敌方核心没找到 —— 对局 setup 了吗？（/referee/setup?map=...）")
        return 1
    cx, cy, cteam, cname = core
    print(f"敌方核心 {cname} at ({cx},{cy})  team={cteam}")

    # --- 2. spawn 一个 poly 到它旁边（4 格，远小于 poly 的 21.75 视野） ---
    sx, sy = cx + 4, cy
    print(f"\n== 裁判 spawn poly 到 ({sx},{sy})，指定属于 team {my_team} ==")
    try:
        r = admin.post("spawn", type="poly", x=sx, y=sy, team=my_team)
        print("  ", json.dumps(r, ensure_ascii=False)[:200])
    except ArenaError as e:
        print(f"  spawn 失败 code={e.code} {e.message[:200]}")
        print("  （是否忘了 -Darena.allowspawn=true ？）")
        return 1

    # --- 3. 确认它真的有视野半径 ---
    print("\n== 确认单位存在且有 fogRadius ==")
    unit = None
    for _ in range(20):
        us = a.units()
        unit = next((u for u in us if u.get("type") == "poly"), None)
        if unit:
            break
        time.sleep(0.5)
    if not unit:
        print("  没在 /units 里看到 poly —— 生成失败或已被打掉")
        return 1
    fr = unit.get("fogRadius")
    print(f"  单位 #{unit['id']} {unit['type']} at "
          f"({unit['x']/8:.0f},{unit['y']/8:.0f})  fogRadius={fr}")
    if not fr:
        print("  fogRadius 缺失或为 0 ⇒ **前置不成立**，这个单位不贡献视野")
        return 1

    # --- 4. 轮询 /intel 看状态机 ---
    print(f"\n== 轮询 /intel（契约：连续可见 {WATCH_TICKS} tick = 10 秒，容差 {TOLERANCE}）==")
    t0 = time.monotonic()
    first_confirmed = None
    seen = []
    while time.monotonic() - t0 < 60:
        # 必须每一轮重申「待在这儿」—— 单位没有指令时 CommandAI 会自己找目标飞走。
        # 实测：不重申的话它两秒内就飞出视野（visibleTicks 从 156 掉回 0）。
        try:
            a.post("control", op="order", unit=unit["id"], x=cx + 4, y=cy)
        except ArenaError:
            pass
        try:
            r = a.get("intel")
        except ArenaError as e:
            print(f"  /intel 失败 code={e.code} {e.message[:120]}")
            return 1
        cores = r.get("cores") if isinstance(r, dict) else None
        target = next((c for c in (cores or []) if c.get("teamId") == cteam), None)
        stt = target.get("state") if target else None
        el = time.monotonic() - t0
        line = f"  t+{el:5.1f}s  state={stt}"
        if target and stt == "scouting":
            line += (f"  progress={target.get('progress')}"
                     f"  visibleTicks={target.get('visibleTicks')}"
                     f"  lastSeenTick={target.get('lastSeenTick')}")
        elif target and stt == "confirmed":
            line += "  " + json.dumps(target, ensure_ascii=False)[:180]
        # 侦察单位还在不在、跑没跑 —— 掉回 unknown 时必须能分辨是「单位没了」还是「机制有 bug」
        try:
            us = a.units()
            u = next((x for x in us if x.get("id") == unit["id"]), None)
            line += (f"   unit=({u['x']/8:.0f},{u['y']/8:.0f}) hp={u.get('health')}"
                     if u else "   unit=**不在了**")
        except ArenaError:
            line += "   unit=?"
        print(line)
        seen.append((round(el, 1), stt, (target or {}).get("visibleTicks")))
        # 只有 confirmed 是契约的终态；scouting 只是「累积中」
        if stt == "confirmed":
            first_confirmed = el
            break
        time.sleep(2)

    print()
    if first_confirmed is not None:
        print(f"  **/intel 端到端：通过** —— 敌方核心在 t+{first_confirmed:.1f}s 由 unknown 变为已确认")
        print(f"     轨迹：{seen}")
        return 0
    print("  **未确认** —— 60 秒内 state 一直是 unknown，见上面轨迹")
    print(f"     轨迹：{seen}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
