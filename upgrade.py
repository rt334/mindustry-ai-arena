#!/usr/bin/env python3
"""矿机自动升级。

规则：**只要能造出更高级的矿机，就把现有的低級矿机换掉。**

为什么升级比堆数量划算（实测数据）：

    mechanical-drill  drillTime=600  size=2  tier=2  铜12
    pneumatic-drill   drillTime=400  size=2  tier=3  铜18+石墨10
    laser-drill       drillTime=280  size=3  tier=4  铜35+石墨30+硅30+钛20

2x2 满矿的煤产出：机械 0.343/s，气动 0.48/s（×1.4），
而 3x3 满矿的激光是 1.42/s（×4.1）。**煤的地图储量是硬约束**
（互不重叠只有 6 个 3x3 位），所以升级是唯一出路，堆数量到不了 5/s。

两种升级方式：
  同尺寸（mechanical -> pneumatic）  **原地换**：break 后同格重建，传送带全保留
  跨尺寸（pneumatic -> laser）       footprint 变了，必须重新选址布线

`break` 全额退款，所以升级不亏材料，只要求库存**曾经**够。

用法：
    python upgrade.py --token T --dry
    python upgrade.py --token T --apply --max 10
    python upgrade.py --token T --apply --reserve silicon=60,graphite=60
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request

# 等级 -> (名称, 尺寸, 造价)
TIERS = [
    ("mechanical-drill", 2, {"copper": 12}),
    ("pneumatic-drill", 2, {"copper": 18, "graphite": 10}),
    ("laser-drill", 3, {"copper": 35, "graphite": 30,
                        "silicon": 30, "titanium": 20}),
]
NAME_TO_TIER = {n: (sz, cost, i) for i, (n, sz, cost) in enumerate(TIERS)}


def api(host, port, agent, token, path, params=None, method="GET", timeout=20):
    url = f"http://{host}:{port}/v1/{agent}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def core_stock(host, port, agent, token):
    j = api(host, port, agent, token, "buildings")
    for b in j["data"]["buildings"]:
        if b["block"].startswith("core-"):
            return b.get("items") or {}
    return {}


def drills(host, port, agent, token):
    try:
        j = api(host, port, agent, token, "drill")
        return j["data"].get("drills", [])
    except Exception:
        return []


def affordable(stock, cost, reserve):
    """库存扣掉保留量之后，够不够这份造价。"""
    for item, need in cost.items():
        if stock.get(item, 0) - reserve.get(item, 0) < need:
            return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7199)
    ap.add_argument("--agent", default="alpha")
    ap.add_argument("--token", required=True)
    ap.add_argument("--reserve", default="",
                    help="保留量，形如 silicon=60,graphite=60 —— 升级不要抢工厂的料")
    ap.add_argument("--max", type=int, default=8, help="本次最多升几台")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--wait-build", type=int, default=0,
                    help=">0 时轮询等待建造完成（不空等，一满足就返回）")
    args = ap.parse_args()

    reserve = {}
    if args.reserve:
        for seg in args.reserve.split(","):
            if not seg.strip():
                continue
            k, v = seg.split("=")
            reserve[k.strip()] = int(v)

    stock = core_stock(args.host, args.port, args.agent, args.token)
    print(f"核心库存: {stock}")
    if reserve:
        print(f"保留量:   {reserve}")

    cur = drills(args.host, args.port, args.agent, args.token)
    print(f"\n当前矿机 {len(cur)} 台:")
    by_type = {}
    for d in cur:
        by_type[d["block"]] = by_type.get(d["block"], 0) + 1
    for k in sorted(by_type):
        sz, cost, ti = NAME_TO_TIER.get(k, (0, {}, -1))
        print(f"   {k:<20} x{by_type[k]:<4} tier={ti+2 if ti>=0 else '?'}")

    # 找当前能造的最高级
    target = None
    for i in range(len(TIERS) - 1, -1, -1):
        name, sz, cost = TIERS[i]
        if affordable(stock, cost, reserve):
            target = i
            break
    if target is None:
        print("\n没有可造的高级矿机（库存不足）")
        return 0
    tname, tsize, tcost = TIERS[target]
    print(f"\n可造的最高级: {tname} (size={tsize}) 造价={tcost}")

    # 找可升级的
    todo = []
    for d in cur:
        old = d["block"]
        if old not in NAME_TO_TIER:
            continue
        osz, ocost, oi = NAME_TO_TIER[old]
        if oi >= target:
            continue
        todo.append((d, old, osz, oi))

    if not todo:
        print("所有矿机都已是最上级")
        return 0

    todo.sort(key=lambda t: (t[3], t[0]["y"], t[0]["x"]))
    print(f"\n可升级 {len(todo)} 台，本次处理 {min(len(todo), args.max)} 台：")
    done = 0
    for d, old, osz, oi in todo[:args.max]:
        same = (osz == tsize)
        tag = "原地换" if same else "需重选址"
        print(f"   ({d['x']:3},{d['y']:3}) {old} -> {tname}  [{tag}]")
        if not args.apply:
            continue
        if not same:
            # 跨尺寸不能原地换：footprint 变了会和邻居撞上。
            # 交给 build-array.py 重新规划，这里只报告。
            continue
        try:
            api(args.host, args.port, args.agent, args.token, "break",
                {"x": d["x"], "y": d["y"]}, method="POST")
            api(args.host, args.port, args.agent, args.token, "place",
                {"x": d["x"], "y": d["y"], "block": tname}, method="POST")
            done += 1
        except Exception as e:
            print(f"      失败: {e}")

    if args.apply:
        print(f"\n已下单升级 {done} 台")
        if args.wait_build:
            # 轮询而不是空等：建造单位干完就立刻返回
            for i in range(args.wait_build):
                cur2 = drills(args.host, args.port, args.agent, args.token)
                n = sum(1 for d in cur2 if d["block"] == tname)
                if n >= done:
                    print(f"   建造完成（第 {i} 次轮询）{tname} x{n}")
                    break
    return 0


if __name__ == "__main__":
    sys.exit(main())
