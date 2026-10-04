import json,urllib.request,urllib.parse,sys
tok=sys.argv[1]; ag="beta"
def api(p,**q):
    u="http://127.0.0.1:7199/v1/%s/%s"%(ag,p)
    if q: u+="?"+urllib.parse.urlencode(q)
    r=urllib.request.Request(u); r.add_header("Authorization","Bearer "+tok)
    return json.loads(urllib.request.urlopen(r,timeout=30).read().decode())
b=api("buildings")["data"]["buildings"]
SIZE={"core-nucleus":5,"silicon-smelter":2,"mechanical-drill":2,"combustion-generator":1,
      "router":1,"conveyor":1,"power-node":1,"graphite-press":2}
occ=set()
for x in b:
    s=SIZE.get(x["block"],1); off=-((s-1)//2)
    for dx in range(s):
        for dy in range(s):
            occ.add((x["x"]+off+dx,x["y"]+off+dy))
core=[x for x in b if x["block"].startswith("core-")][0]
cx,cy=core["x"],core["y"]
print("核心 (%d,%d)  库存 %s"%(cx,cy,core.get("items")))
free=[]
for dx in range(-8,9):
    for dy in range(-8,9):
        p=(cx+dx,cy+dy)
        if p in occ: continue
        d=abs(dx)+abs(dy)
        if d<1 or d>9: continue
        free.append((d,p))
free.sort()
print("\n=== 核心附近空格（前 14）===")
for d,p in free[:14]: print("   (%d,%d) 曼哈顿距离 %d"%(p[0],p[1],d))
# 哪些空格与核心 footprint 相邻
cs=5; coff=-2
adj=[]
for d,p in free:
    x,y=p
    for ax in range(cx+coff,cx+coff+cs):
        for ay in range(cy+coff,cy+coff+cs):
            if abs(x-ax)+abs(y-ay)==1: adj.append((d,p)); break
        else: continue
        break
print("\n=== 与核心相邻的空格（放发电机可共享电网）===")
for d,p in adj[:12]: print("   (%d,%d) 距 %d"%(p[0],p[1],d))
