import json,urllib.request,urllib.parse,sys,collections
tok=sys.argv[1]
def api(p,**q):
    u="http://127.0.0.1:7199/v1/beta/"+p
    if q: u+="?"+urllib.parse.urlencode(q)
    r=urllib.request.Request(u); r.add_header("Authorization","Bearer "+tok)
    return json.loads(urllib.request.urlopen(r,timeout=40).read().decode())
b=api("buildings")["data"]["buildings"]
SZ={"core-nucleus":5,"silicon-smelter":2,"mechanical-drill":2,"combustion-generator":1,
    "conveyor":1,"router":1,"power-node":1,"sorter":1}
occ=set(); belts=set()
for x in b:
    s=SZ.get(x["block"],1); off=-((s-1)//2)
    for dx in range(s):
        for dy in range(s): occ.add((x["x"]+off+dx,x["y"]+off+dy))
    if x["block"]=="conveyor": belts.add((x["x"],x["y"]))
# 扫 beta 视野内的矿
ore=collections.defaultdict(dict)
for bx in range(0,350,50):
    for by in range(0,200,50):
        try: j=api("map",x=bx,y=by,w=50,h=50)
        except Exception: continue
        if not j.get("ok"): continue
        for t in j["data"]["tiles"]:
            if not t.get("visible"): continue
            d=t.get("drop")
            if d: ore[d][(t["x"],t["y"])]=t.get("dropHardness")
print("=== beta 视野内矿脉 ===")
for k,v in sorted(ore.items(), key=lambda kv:-len(kv[1])): print("   %-9s %4d 格"%(k,len(v)))
# 2x2 锚点：footprint 全在目标矿上 且 与现有传送带相邻（免铺新带）
def anchors(item):
    tiles=ore.get(item) or {}
    out=[]
    for (ax,ay) in list(tiles.keys()):
        fp=[(ax+dx,ay+dy) for dx in range(2) for dy in range(2)]
        if any(p not in tiles for p in fp): continue
        if any(p in occ for p in fp): continue
        # 与已铺传送带相邻？
        touch=False
        for (px,py) in fp:
            for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
                if (px+dx,py+dy) in belts: touch=True; break
            if touch: break
        out.append((0 if touch else 1,(ax,ay)))
    out.sort()
    return out
for item in ("coal","sand"):
    a=anchors(item)
    touch=[p for f,p in a if f==0]
    print("\n=== %s 可下矿机锚点 %d 个（其中 %d 个紧邻已有传送带）==="%(item,len(a),len(touch)))
    print("   紧邻带子的: %s"%(touch[:24] if touch else "无"))
