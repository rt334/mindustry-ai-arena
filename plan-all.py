import json,urllib.request,urllib.parse,sys,collections
tok=sys.argv[1]
def api(p,method="GET",**q):
    u="http://127.0.0.1:7199/v1/beta/"+p
    if q: u+="?"+urllib.parse.urlencode({k:v for k,v in q.items() if v is not None})
    r=urllib.request.Request(u,method=method); r.add_header("Authorization","Bearer "+tok)
    return json.loads(urllib.request.urlopen(r,timeout=25).read().decode())
bb=api("buildings")["data"]["buildings"]
SZ={"core-nucleus":5,"silicon-smelter":2,"mechanical-drill":2,"combustion-generator":1,
    "conveyor":1,"router":1,"power-node":1,"sorter":1,"graphite-press":2}
occ=set()
for x in bb:
    s=SZ.get(x["block"],1); off=-((s-1)//2)
    for dx in range(s):
        for dy in range(s): occ.add((x["x"]+off+dx,x["y"]+off+dy))
# 找核心
core=[x for x in bb if x["block"].startswith("core-")][0]
cx,cy=core["x"],core["y"]
print("核心 (%d,%d) %s"%(cx,cy,core.get("items")))
# 扫核心周边矿
ore=collections.defaultdict(set)
for bx in range(cx-45,cx+46,45):
    for by in range(cy-45,cy+46,45):
        try: j=api("map",x=bx,y=by,w=45,h=45)
        except Exception: continue
        if not j.get("ok"): continue
        for t in j["data"]["tiles"]:
            if not t.get("visible"): continue
            if t.get("drop"): ore[t["drop"]].add((t["x"],t["y"]))
print("\n=== 核心周边矿脉 ===")
for k in ("copper","lead","titanium","coal","sand"):
    v=ore.get(k) or set()
    if not v: print("   %-9s 无"%k); continue
    v=sorted(v,key=lambda p:(p[0]-cx)**2+(p[1]-cy)**2)
    print("   %-9s %4d 格  最近 %s"%(k,len(v),v[0]))
# 各矿可用锚点
print("\n=== 可用矿机锚点（footprint 全矿石 + 不与现有冲突）===")
plan=[]
for k in ("copper","lead","titanium"):
    v=ore.get(k) or set()
    got=[]
    for (ax,ay) in sorted(v,key=lambda p:(p[0]-cx)**2+(p[1]-cy)**2):
        fp=[(ax+dx,ay+dy) for dx in range(2) for dy in range(2)]
        if any(p not in v for p in fp): continue
        if any(p in occ for p in fp): continue
        for p in fp: occ.add(p)
        got.append((ax,ay))
        if len(got)>=6: break
    plan.append((k,got))
    print("   %-9s %s"%(k,got))
json.dump({k:v for k,v in plan}, open("plan-drills.json","w"))
