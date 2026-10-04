import json,urllib.request,urllib.parse,sys,collections
tok=sys.argv[1]
def api(p,**q):
    u="http://127.0.0.1:7199/v1/beta/"+p
    if q: u+="?"+urllib.parse.urlencode(q)
    r=urllib.request.Request(u); r.add_header("Authorization","Bearer "+tok)
    return json.loads(urllib.request.urlopen(r,timeout=30).read().decode())
bb=api("buildings")["data"]["buildings"]
SZ={"core-nucleus":5,"silicon-smelter":2,"mechanical-drill":2,"pneumatic-drill":2,
    "laser-drill":3,"graphite-press":2,"combustion-generator":1,"conveyor":1,
    "router":1,"junction":1,"power-node":1,"sorter":1,"build1":2,"build2":2}
occ=set()
for x in bb:
    s=SZ.get(x["block"],1); off=-((s-1)//2)
    for dx in range(s):
        for dy in range(s): occ.add((x["x"]+off+dx,x["y"]+off+dy))
print("=== 现状 ===")
for k,v in collections.Counter(x["block"] for x in bb).most_common():
    print("   %-22s %d"%(k,v))
core=[x for x in bb if x["block"].startswith("core-")][0]
print("   核心 %s"%core.get("items"))
print()
# 扫煤，找沿现有带子的锚点
coal={}
for bx in range(250,335,42):
    for by in range(60,170,42):
        try: j=api("map",x=bx,y=by,w=42,h=42)
        except Exception: continue
        if not j.get("ok"): continue
        for t in j["data"]["tiles"]:
            if t.get("visible") and t.get("drop")=="coal":
                coal[(t["x"],t["y"])]=(t.get("dropHardness") or 2)
belts={(x["x"],x["y"]) for x in bb if x["block"] in ("conveyor","junction","router")}
cand=[]
for (ax,ay) in coal:
    fp=[(ax+dx,ay+dy) for dx in range(2) for dy in range(2)]
    if any(p not in coal for p in fp): continue
    if any(p in occ for p in fp): continue
    touch=any((px+dx,py+dy) in belts for (px,py) in fp for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)))
    if touch: cand.append((ax,ay))
print("=== 可挂现有带子旁的煤矿机锚点 %d 个 ==="%len(cand))
# 互相去重
picked=[]; used=set()
for (ax,ay) in sorted(cand):
    fp={(ax+dx,ay+dy) for dx in range(2) for dy in range(2)}
    if fp & used: continue
    used |= fp; picked.append((ax,ay))
print("   去重后 %d 个: %s"%(len(picked),picked[:16]))
json.dump(picked, open("plan-coal2.json","w"))
