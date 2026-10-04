import json,urllib.request,urllib.parse,sys
tok=sys.argv[1]
def api(p,**q):
    u="http://127.0.0.1:7199/v1/beta/"+p
    if q: u+="?"+urllib.parse.urlencode(q)
    r=urllib.request.Request(u); r.add_header("Authorization","Bearer "+tok)
    return json.loads(urllib.request.urlopen(r,timeout=30).read().decode())
# 在发电机 (288,107) 周边 14 格内找煤
cx,cy=288,107
j=api("map",x=cx-14,y=cy-14,w=29,h=29)
ore={}
for t in j["data"]["tiles"]:
    d=t.get("drop")
    if d: ore.setdefault(d,[]).append((t["x"],t["y"]))
print("=== 发电机 (288,107) 周边 14 格内矿脉 ===")
for k,v in sorted(ore.items(), key=lambda kv:-len(kv[1])):
    v.sort(key=lambda p:(p[0]-cx)**2+(p[1]-cy)**2)
    print("   %-9s %3d 格  最近的 8 个: %s" % (k,len(v)," ".join("(%d,%d)"%p for p in v[:8])))
print()
# 2x2 footprint 全在煤上的锚点候选
b=api("buildings")["data"]["buildings"]
occ=set()
SZ={"core-nucleus":5,"silicon-smelter":2,"mechanical-drill":2,"combustion-generator":1,"conveyor":1,"router":1}
for x in b:
    s=SZ.get(x["block"],1); off=-((s-1)//2)
    for dx in range(s):
        for dy in range(s): occ.add((x["x"]+off+dx,x["y"]+off+dy))
tile={(t["x"],t["y"]):t for t in j["data"]["tiles"]}
cands=[]
for ax in range(cx-14,cx+15):
    for ay in range(cy-14,cy+15):
        fp=[(ax+dx,ay+dy) for dx in range(2) for dy in range(2)]
        if any(p in occ for p in fp): continue
        drops=[(tile.get(p) or {}).get("drop") for p in fp]
        if all(d=="coal" for d in drops):
            cands.append((abs(ax-cx)+abs(ay-cy),(ax,ay)))
cands.sort()
print("=== 能挖煤的 2x2 锚点（按到发电机距离）===")
for d,p in cands[:10]: print("   (%d,%d) 距 %d"%(p[0],p[1],d))
if not cands: print("   附近无（需从现有煤线引流）")
