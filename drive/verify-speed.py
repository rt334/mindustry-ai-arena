#!/usr/bin/env python3
"""精确测速：用 /control?op=pos 的高精度 worldX/worldY，与引擎报的 speed() 对账。

为什么重测：上一版用 /units 的 x/y（每 0.25s 采一次）算出 66 格/秒，
而 UnitComp.java:298 给出的换算是 type.speed * 60 / tilesize = 26.6 格/秒。
差得太多，必须查清是采样误差还是真有加速通道 —— 这直接关系到
「AI 不能超过人类 WASD 速度」能不能算数。

方法：连续读 pos（高精度、廉价），取较长时间窗算平均速度，避开起停阶段。
"""
import json
import sys
import time

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens

toks, _ = load_tokens()
a = Arena("beta", toks["beta"])
TILESIZE = 8.0


def pos_of(uid):
    r = a.post("control", op="pos", unit=uid)
    return json.loads(r["message"])


def main():
    u = (a.units() or [None])[0]
    if not u:
        print("没有单位")
        return 1
    uid = u["id"]
    p0 = pos_of(uid)
    print(f"单位 #{uid} {p0['type']}")
    print(f"  speed()={p0['speed']:.4f}  typeSpeed={p0['typeSpeed']}  flying={p0['flying']}")
    print(f"  换算 type.speed * 60 / {TILESIZE:.0f} = {p0['typeSpeed'] * 60 / TILESIZE:.2f} 格/秒")
    print(f"  speed()     * 60 / {TILESIZE:.0f} = {p0['speed'] * 60 / TILESIZE:.2f} 格/秒  ← 含倍率")

    # 让单位跑一段长距离（用 order，move 只属于 /command）
    print("\n发 order 到 (270,100)（约 58 格），中段采样：")
    try:
        a.post("control", op="order", unit=uid, x=270, y=100)
    except ArenaError as e:
        print(f"  order ERR {e.code} {e.message}")
        return 1

    time.sleep(0.8)   # 避开起步阶段

    print("\n移动中逐次采样（0.3s 窗口）：")
    samples = []
    for i in range(16):
        p = pos_of(uid)
        samples.append((time.monotonic(), p["worldX"], p["worldY"],
                        p["speed"], p["velX"], p["velY"]))
        time.sleep(0.3)

    print(f"  {'窗口':<6}{'位移(格)':<12}{'实测格/秒':<12}{'speed()*60/8':<14}{'|vel|*60/8':<12}")
    for i in range(1, len(samples)):
        t0, x0, y0, sp0, vx0, vy0 = samples[i - 1]
        t1, x1, y1, sp1, vx1, vy1 = samples[i]
        dt = t1 - t0
        if dt < 0.01:
            continue
        moved = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 / TILESIZE
        v_meas = moved / dt
        v_eng = sp1 * 60 / TILESIZE
        v_vel = ((vx1 ** 2 + vy1 ** 2) ** 0.5) * 60 / TILESIZE
        print(f"  {i:<6}{moved:<12.2f}{v_meas:<12.2f}{v_eng:<14.2f}{v_vel:<12.2f}")

    print("\n结论判读：")
    print("  若「实测格/秒」≈「speed()*60/8」，则速度完全由引擎的 speed() 决定，")
    print("  而 speed() = type.speed × strafePenalty × boost × floorSpeedMultiplier()")
    print("  （UnitComp.java:193）—— 全都是世界规则，人类玩家同样受它约束。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
