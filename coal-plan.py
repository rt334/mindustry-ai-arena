import json,urllib.request,urllib.parse,sys,collections
tok=sys.argv[1]
def api(p,**q):
    u="http://127.0.0.1:7199/v1/beta/"+p
    if q: u+="?"+urllib.parse.urlencode(q)
    r=urllib.request.Request(u); r.add_header("Authorization","Bearer "+tok)
    return json.loads(urllib.request.urlopen(r,timeout=40).read().decode())
b=api("buildings")["data"]["buildings"]
SZ={"core-nucleus":5,"silicon-smelter":2,"mechanical-drill":2,"combustion-generator":1,
    "conveyor":1,"router":1,"power-node":1,"sorter":1,"graphite-press":2}
occ=set(); belts=set()
for x in b:
    s=SZ.get(x["block"],1); off=-((s-1)//2)
    for dx in range(s):
        for dy in range(s): occ.add((x["x"]+off+dx,x["y"]+off+dy))
    if x["block"]=="conveyor": belts.add((x["x"],x["y"]))
# 扫煤
coal={}
for bx in range(230,330,40):
    for by in range(70,170,40):
        try: j=api("map",x=bx,y=by,w=40,h=40)
        except Exception: continue
        if not j.get("ok"): continue
        for t in j["data"]["tiles"]:
            if t.get("visible") and t.get("drop")=="coal": coal[(t["x"],t["y"])]=1
print("煤 %d 格"%len(coal))
# 锚点：footprint 全煤 + 不与已有冲突
anchors=[]
for (ax,ay) in coal:
    fp=[(ax+dx,ay+dy) for dx in range(2) for dy in range(2)]
    if any(p not in coal for p in fp): continue
    if any(p in occ for p in fp): continue
    anchors.append((ax,ay))
print("可下矿机锚点 %d 个"%len(anchors))
# 与已有传送带的距离（曼哈顿，到最近带子）
def dist(p):
    x,y=p; best=99
    for (bx,by) in belts:
        d=abs(bx-x)+abs(by-y)
        if d<best: best=d
        if best<=1: break
    return best
anchors.sort(key=dist)
print("\n=== 最近 18 个锚点（到最近带子的距离）===")
for p in anchors[:18]: print("   (%d,%d) 距带子 %d"%(p[0],p[1],dist(p)))
print("\n=== 现有传送带范围 ===")
xs=[p[0] for p in belts]; ys=[p[1] for p in belts]
print("   x %d..%d   y %d..%d  共 %d 格"%(min(xs),max(xs),min(ys),max(ys),len(belts)))
