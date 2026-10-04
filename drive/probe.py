#!/usr/bin/env python3
"""局面全量快照：把只读端点一次打全，用于定位瓶颈。

用法：python probe.py [--agent beta] [--stalls 30]
"""
import argparse
import collections
import json
import sys

sys.path.insert(0, r"C:\dsh\ai-arena\skill\scripts")
from arena import Arena, ArenaError, load_tokens


def dump(name, v):
    print(f"---- {name} ----")
    print(json.dumps(v, ensure_ascii=False, indent=1)[:4000])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="beta")
    ap.add_argument("--stalls", type=int, default=25)
    ap.add_argument("--admin", default="referee")
    args = ap.parse_args()

    toks, _ = load_tokens()
    a = Arena(args.agent, toks[args.agent])
    if not a.ping():
        print("服务端不在线")
        return 1

    dump("state", a.state())

    b = a.buildings()
    cnt = collections.Counter(x["block"] for x in b)
    print(f"---- buildings 共 {len(b)} ----")
    for k, v in cnt.most_common():
        print(f"  {v:>4}  {k}")
    core = next((x for x in b if x["block"].startswith("core")), None)
    if core:
        print(f"  core @({core['x']},{core['y']}) items={core['items']} hp={core['health']}/{core['maxHealth']}")

    print("---- units ----")
    for u in a.units():
        print(f"  #{u['id']} {u['type']} @({u['x'] / 8:.0f},{u['y'] / 8:.0f}) "
              f"hp={u['health']:.0f} canBuild={u['canBuild']} ctrl={u.get('controller')}")

    dump("rates", a.rates(window=20))

    stl = a.stalls()
    print(f"---- stalls 共 {len(stl)}（列前 {args.stalls}）----")
    kinds = collections.Counter(s["kind"] for s in stl)
    print(f"  kinds: {dict(kinds)}")
    for s in stl[: args.stalls]:
        hold = s.get("heldSeconds", 0)
        miss = ",".join(
            f"{m.get('item') or m.get('kind')}x{m.get('need')}(have {m.get('have')})"
            for m in s.get("missing", [])) or "-"
        print(f"  ({s['x']:>3},{s['y']:>3}) {s['block']:<20} {s['kind']:<14} "
              f"eff={s.get('efficiency', 0):.2f} held={hold:>7.1f}s 缺[{miss}]")

    dump("queue", a.queue())

    if args.admin:
        adm = Arena(args.admin, toks[args.admin])
        try:
            dump("diag(admin)", adm.get("diag"))
        except ArenaError as e:
            print(f"---- diag ---- {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
