#!/usr/bin/env python3
"""打分制：算「效率分」，裁判视角、与任务书用同一个公式。

## 分数是什么

    效率分 = 目标物品的核心净产率(/s) ÷ 该队已建方块数

**为什么是这个比值**：两次实测给出了它的判别力 ——
人类那份「8 台冶炼厂共享一条分配列」大约一百个方块做到 `+5.02/s`；
而 AI 那次用 **432** 个方块（365 条带子服务 3 台炉子）做到 `+3.11/s`。
单纯比产率时两者是 5.02 : 3.11（差 1.6 倍），
换成效率后是 ~0.05 : 0.007（差 7 倍）—— **堆量在分母上被直接惩罚**。

这正是「加成本项」的落地：不动能力定义、不动对等约束，
只把目标从单一标量改成带成本的比值。

## 它为什么不算越界（DESIGN §7.9）

产率和方块数**参赛方自己就能拿到**（`/rates` 的 `core.<item>.perSecond`、
`/buildings` 的条数），真人玩家也能数物品、数建筑。
这个脚本只是**替裁判算同一个除法** —— 它不给任何「该怎么建」的建议。
所以它属于「报状态」，不属于「报结论」。

## 用法

    python drive/score.py --agent beta              算一次
    python drive/score.py --all                     两个队都算（需要 admin）
    python drive/score.py --agent beta --watch 30   每 30 秒算一次，直到 Ctrl+C
    python drive/score.py --agent beta --window 30  /rates 的回看窗口（默认 30 秒）

退出码：0 正常 / 2 环境问题（服务器没起、拿不到 token）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
ADMIN_FILE = ROOT / "server-run" / "admin-token.txt"
CONFIG = ROOT / "server-run" / "config" / "ai-arena.json"

TARGET_ITEM = "silicon"          # 这一局的目标物品
TEAM_NAME = {"1": "alpha", "2": "beta", "100": "sharded", "101": "crux"}


def get(base: str, agent: str, token: str, action: str, params: str = "", timeout=10.0):
    url = f"{base}/v1/{agent}/{action}" + (f"?{params}" if params else "")
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "code": e.code}
    except Exception as e:
        return {"ok": False, "_err": str(e)}


def load_admin() -> str | None:
    import os
    t = os.environ.get("ARENA_ADMIN_TOKEN", "").strip()
    if t:
        return t
    if ADMIN_FILE.exists():
        return ADMIN_FILE.read_text(encoding="utf-8-sig").strip()
    return None


def board(base: str, admin: str, window: float) -> list[dict]:
    """裁判视角：一次拿全部队伍的分。

    用 referee 的 `view=all` —— 那会进审计（`privileged:true`），这是**维护者**在
    核账，不是参赛方在读，属于组织者特权，见 CONDITIONS 事故记录第 6 条。
    """
    st = get(base, "referee", admin, "state", "view=all")
    if not st.get("ok"):
        return []
    data = st.get("data") or {}
    tick = data.get("tick")

    rows = []
    for team_id in data.get("teams", []) or []:
        pass  # 结构未知时不猜；下面用 units/buildings 的实际返回驱动

    bs = (get(base, "referee", admin, "buildings", "view=all").get("data") or {}).get("buildings") or []
    by_team: dict = {}
    for b in bs:
        t = b.get("team")
        by_team.setdefault(t, 0)
        by_team[t] += 1

    # /rates 是**按调用方自己的队**算的 —— 裁判没有队，所以逐个 agent 代问
    agents = []
    if CONFIG.exists():
        cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
        for a in cfg.get("agents") or []:
            if a.get("id") in ("alpha", "beta"):
                agents.append((a["id"], a.get("token"), a.get("team")))

    for aid, tok, _team in agents:
        st2 = get(base, aid, tok, "state")
        d2 = st2.get("data") or {}
        tid = d2.get("team")
        if tid is None or tid < 0:
            continue
        r = get(base, aid, tok, "rates", f"window={window}")
        core = ((r.get("data") or {}).get("core") or {})
        # `/rates` 的 `core` **只列 `delta != 0` 的物品**（API.md 有记）——
        # 所以「没有这个条目」= 「这一窗口内它没变」= **0**，不是「读不到」。
        # 不区分这两者时，「还没开始产」和「接口坏了」在输出里长得一模一样。
        item = core.get(TARGET_ITEM) or {}
        per_sec = item.get("perSecond", 0.0)
        teamb = (get(base, aid, tok, "buildings").get("data") or {}).get("buildings") or []
        blocks = len([b for b in teamb if b.get("team") == tid])
        eff = (per_sec / blocks) if (isinstance(per_sec, (int, float)) and blocks > 0) else None
        rows.append({"agent": aid, "team": tid,
                     "teamName": TEAM_NAME.get(str(tid), d2.get("teamName") or str(tid)),
                     "perSecond": per_sec, "blocks": blocks,
                     "stock": item.get("end"), "efficiency": eff,
                     "tick": tick})
    return rows


def show(rows: list[dict], window: float) -> None:
    ts = time.strftime("%H:%M:%S")
    if not rows:
        print(f"[{ts}] 算不出分 —— 服务器在跑吗？状态是不是 playing？")
        return
    print(f"[{ts}]  目标 {TARGET_ITEM} · /rates 窗口 {window}s")
    for r in rows:
        ps = r["perSecond"]
        eff = r["efficiency"]
        ps_s = f"{ps:+.2f}/s" if isinstance(ps, (int, float)) else "  n/a "
        eff_s = f"{eff:.5f}" if isinstance(eff, (int, float)) else " n/a "
        print(f"    {r['agent']:6s} team={r['team']:<3} "
              f"净产率 {ps_s:>9s}   方块 {r['blocks']:>4d}   "
              f"库存 {str(r['stock']):>6s}   效率分 {eff_s}")
    print(f"    分数 = 核心净产率({TARGET_ITEM}, /s) ÷ 己方方块数")


def main() -> int:
    ap = argparse.ArgumentParser(description="打分制：效率分 = 净产率 ÷ 方块数")
    ap.add_argument("--base", default="http://127.0.0.1:7199")
    ap.add_argument("--agent", help="只算某一个（默认两个都算）")
    ap.add_argument("--all", action="store_true", help="两个队都算（默认）")
    ap.add_argument("--window", type=float, default=30.0, help="/rates 回看窗口秒数")
    ap.add_argument("--watch", type=float, help="每 N 秒算一次，直到 Ctrl+C")
    args = ap.parse_args()

    try:
        with urllib.request.urlopen(f"{args.base}/ping", timeout=5) as r:
            json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"服务器没起（{args.base}/ping 不通）: {e}", file=sys.stderr)
        return 2

    admin = load_admin()
    if not admin:
        print(f"拿不到 admin token（{ADMIN_FILE}）—— 先 `python start.py play`",
              file=sys.stderr)
        return 2

    while True:
        rows = board(args.base, admin, args.window)
        if args.agent:
            rows = [r for r in rows if r["agent"] == args.agent]
        show(rows, args.window)
        if not args.watch:
            return 0
        time.sleep(args.watch)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(0)
