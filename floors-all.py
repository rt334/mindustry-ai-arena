import json,urllib.request,urllib.parse,sys,collections
tok=sys.argv[1]
def api(p,**q):
    u="http://127.0.0.1:7199/v1/referee/"+p
    if q: u+="?"+urllib.parse.urlencode(q)
    r=urllib.request.Request(u); r.add_header("Authorization","Bearer "+tok)
    return json.loads(urllib.request.urlopen(r,timeout=40).read().decode())
floors=collections.Counter(); total=0; ok=0
for bx in range(0,350,50):
    for by in range(0,200,50):
        try: j=api("map",x=bx,y=by,w=50,h=50,view="all")
        except Exception as e: continue
        if not j.get("ok"): continue
        ok+=1
        for t in j["data"]["tiles"]:
            total+=1
            f=t.get("floor")
            if f: floors[f]+=1
print("成功查询 %d 块，共 %d 格"%(ok,total))
print("=== 全部地板 ===")
for k,v in floors.most_common(): print("   %-24s %5d"%(k,v))
print()
print("=== 是否有任何液体相关 ===")
hits=[k for k in floors if any(w in k for w in ("water","liquid","tar","slag","oil","cryo"))]
print("   %s"%hits if hits else "   无")
