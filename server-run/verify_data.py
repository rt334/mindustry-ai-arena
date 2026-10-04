import json, urllib.request
d = json.load(urllib.request.urlopen("http://127.0.0.1:8080/data", timeout=20))
print(f"  尺寸      {d['width']} x {d['height']}")
print(f"  地板      {len(d['terrain'])} 格")
print(f"  方块      {len(d['blocks'])} 格  (blocksCount={d['blocksCount']})")
print(f"  地形就绪  {d['terrainReady']}")
print(f"  单位/建筑 {len(d['units'])} / {len(d['buildings'])}")
print(f"  错误      '{d['error']}'")
from collections import Counter
fc = Counter(d['terrain'].values())
print("  地板种类:")
for k, v in fc.most_common():
    print(f"    {k:<22} {v:>6}")
bc = Counter(d['blocks'].values())
print("  方块种类:")
for k, v in bc.most_common():
    print(f"    {k:<22} {v:>6}")
# 抽查一格，确认两层都取到了
sample = "175,100"
print(f"  抽查 ({sample}): 地板={d['terrain'].get(sample)}  方块={d['blocks'].get(sample)}")
