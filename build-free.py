import json,urllib.request,urllib.parse,sys,collections,time
BT,REF=sys.argv[1],sys.argv[2]
def call(ag,tok,p,method="GET",**q):
    u="http://127.0.0.1:7199/v1/%s/%s"%(ag,p)
    if q: u+="?"+urllib.parse.urlencode({k:v for k,v in q.items() if v is not None})
    r=urllib.request.Request(u,method=method); r.add_header("Authorization","Bearer "+tok)
    return json.loads(urllib.request.urlopen(r,timeout=25).read().decode())
# 1) 全图矿（裁判 view=all）
ore=collections.defaultdict(set); floors=collections.Counter()
for bx in range(0,350,50):
    for by in range(0,200,50):
        try: j=call("referee",REF,"map",x=bx,y=by,w=50,h=50,view="all")
        except Exception: continue
        if not j.get("ok"): continue
        for t in j["data"]["tiles"]:
            if t.get("drop"): ore[t["drop"]].add((t["x"],t["y"]))
            if t.get("floor"): floors[t["floor"]]+=1
# 2) 己方建筑
bb=call("beta",BT,"buildings")["data"]["buildings"]
SZ={"core-nucleus":5,"silicon-smelter":2,"graphite-press":2,"mechanical-drill":2,
    "pneumatic-drill":2,"laser-drill":3,"combustion-generator":1,"conveyor":1,
    "router":1,"junction":1,"power-node":1,"sorter":1,"build1":2,"build2":2,"build3":3}
occ=set(); belts=set()
for x in bb:
    s=SZ.get(x["block"],1); off=-((s-1)//2)
    for dx in range(s):
        for dy in range(s): occ.add((x["x"]+off+dx,x["y"]+off+dy))
    if x["block"] in ("conveyor","junction","router"): belts.add((x["x"],x["y"]))
core=[x for x in bb if x["block"].startswith("core-")][0]
cx,cy=core["x"],core["y"]
print("核心 (%d,%d) %s"%(cx,cy,core.get("items")))
print("煤 %d 格  铜 %d  铅 %d  钛 %d  沙 %d"%(len(ore.get("coal") or []),len(ore.get("copper") or []),len(ore.get("lead") or []),len(ore.get("titanium") or []),len(ore.get("sand") or [])))
print()
# 3) 找「紧邻已有带子」的锚点（免铺新带）
DR={"coal":"mechanical-drill","sand":"mechanical-drill","copper":"mechanical-drill",
    "lead":"mechanical-drill","titanium":"pneumatic-drill"}
plan=[]
for item,blk in DR.items():
    v=ore.get(item) or set()
    size=2
    got=[]
    for (ax,ay) in sorted(v,key=lambda p:(p[0]-cx)**2+(p[1]-cy)**2):
        fp={(ax+dx,ay+dy) for dx in range(size) for dy in range(size)}
        if any(p not in v for p in fp): continue
        if any(p in occ for p in fp): continue
        if not any((px+dx,py+dy) in belts for (px,py) in fp for dx,dy in ((1,0),(-1,0),(0,1),(0,-1))): continue
        occ |= fp; got.append((ax,ay))
    plan += [(blk,gx,gy,item) for (gx,gy) in got]
    print("   %-9s 免铺点位 %2d 个: %s"%(item,len(got),got[:12]))
json.dump([{"block":p[0],"x":p[1],"y":p[2],"item":p[3]} for p in plan], open("plan-free.json","w"))
print()
print("合计免铺点位 %d 个"%len(plan))
# 4) 直接下单
ok=fail=0
for blk,gx,gy,item in plan:
    try:
        r=call("beta",BT,"place",method="POST",x=gx,y=gy,block=blk)
        if r.get("ok"): ok+=1
        else: fail+=1
    except Exception: fail+=1
print("下单 ok=%d fail=%d"%(ok,fail))
