#!/usr/bin/env python3
"""验证 /intel 端到端 —— §三 里最大的一条未验证项。

`/intel` 的契约：单位在敌方核心视野内**连续 600 tick（10 秒）**才把该核心标成已知，
另有 30 tick 容差。

**我在这份脚本的第一版里写错过一句**：以为「gamma 本来就有视野，直接开过去就行，
当初的判断是多余的」。实测反证 —— 把 gamma 开到敌方核心 **5 格**外，
请求周边 31x31 地图，**`visible=0`**，一片空白。

原因在 `ENGINE-NOTES.md` §二十八：只有 6 个快速飞行单位被显式设为 0，
**gamma 正是其中之一**。它跑得快，但看不见。

所以 `/intel` 的依赖是真的：**必须有 fogRadius > 0 的单位**。
链子是 煤+沙 → 硅冶炼厂 → air-factory → `poly`。
把单位开过去不够 —— 这个脚本现在的结论是「**这个前置不成立**」，
它本身仍有价值：把「为什么走不通」钉死在这里，省得下次再试一遍。

步骤：
  1. 用 /control?op=order 把 gamma 派往一个敌方核心
  2. 沿途轮询 /map，确认敌方核心真的进了**己方视野**
  3. 抵达后保持不动，轮询 /intel 直到 state 不再是 unknown
  4. 顺带记录容差行为（离开视野会不会掉回 unknown）
"""
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

TARGET = (198, 27)      # team#103 的 core-shard，由裁判视角查得
TEAM_ID = 103


def my_unit(a):
    u = a.units()
    return u[0] if u else None


def main():
    toks, _ = load_tokens()
    a = Arena("beta", toks["beta"])

    u = my_unit(a)
    if not u:
        print("没有单位")
        return 1
    uid = u["id"]
    print(f"单位 #{uid} {u['type']} 起点 ({u['x']/8:.0f},{u['y']/8:.0f})")
    print(f"目标敌方核心 {TARGET}（team {TEAM_ID}）")

    print("\n== 派往目标 ==")
    try:
        r = a.post("control", op="order", unit=uid, x=TARGET[0], y=TARGET[1])
        print(" ", r)
    except ArenaError as e:
        print("  失败", e.code, e.message[:140])
        return 1

    # ── 1. 等它看见敌方核心 ───────────────────────────────────────────
    print("\n== 等敌方核心进己方视野（判据是 /map 里出现该方块）==")
    t0 = time.monotonic()
    spotted_at = None
    last = None
    while time.monotonic() - t0 < 300:
        u = my_unit(a)
        if u:
            ux, uy = u["x"] / 8, u["y"] / 8
            try:
                ts = a.map(int(ux) - 12, int(uy) - 12, 25, 25)
            except ArenaError:
                ts = []
            for t in ts:
                blk = (t.get("block") or "").strip()
                if blk.startswith("core") and t.get("team") == f"team#{TEAM_ID}" \
                        or (blk.startswith("core") and t.get("team") == TEAM_ID):
                    spotted_at = (t["x"], t["y"], time.monotonic() - t0, ux, uy)
                    break
            if not spotted_at:
                # 也看看是不是已经走到了
                for t in ts:
                    if (t.get("block") or "").strip().startswith("core") and \
                            str(t.get("team")) in (str(TEAM_ID),):
                        spotted_at = (t["x"], t["y"], time.monotonic() - t0, ux, uy)
                        break
            near = (round(ux), round(uy))
            if near != last:
                print(f"  t+{time.monotonic()-t0:5.1f}s  单位 ({near[0]},{near[1]})  距离目标 "
                      f"{abs(near[0]-TARGET[0])+abs(near[1]-TARGET[1])}")
                last = near
        if spotted_at:
            break
        time.sleep(3)

    if not spotted_at:
        print("  300 秒内没看见敌方核心 —— 可能路被挡或没走到")
        u = my_unit(a)
        if u:
            print(f"  末位置 ({u['x']/8:.0f},{u['y']/8:.0f})")
        return 1
    print(f"  ✓ 看见核心于 ({spotted_at[0]},{spotted_at[1]})，t+{spotted_at[2]:.1f}s，"
          f"单位在 ({spotted_at[3]:.0f},{spotted_at[4]:.0f})")

    # ── 2. 停在原地，等 600 tick 确认 ────────────────────────────────
    print("\n== 停在原地等连续 600 tick 确认 ==")
    t0 = time.monotonic()
    got = None
    while time.monotonic() - t0 < 120:
        # 反复下同一位置的 order，抵消 20 秒过期
        try:
            a.post("control", op="order", unit=uid, x=TARGET[0], y=TARGET[1])
        except ArenaError:
            pass
        try:
            r = a.get("intel")
        except ArenaError as e:
            print("  /intel", e.code, e.message[:120])
            break
        core = next((c for c in (r.get("cores") or []) if c.get("teamId") == TEAM_ID), None)
        st = core.get("state") if core else None
        print(f"  t+{time.monotonic()-t0:5.1f}s  state={st}"
              + (f"  {json_safe(core)}" if st and st != "unknown" else ""))
        if st and st != "unknown":
            got = core
            break
        time.sleep(6)

    print()
    if got:
        print("  **/intel 端到端：通过** —— 敌方核心由 unknown 变为已知")
        print(f"     {json_safe(got)}")
        return 0
    print("  **/intel 仍未确认** —— 超时了，见上面的 state 轨迹")
    return 1


def json_safe(o):
    import json
    return json.dumps(o, ensure_ascii=False)[:200]


if __name__ == "__main__":
    sys.exit(main())
