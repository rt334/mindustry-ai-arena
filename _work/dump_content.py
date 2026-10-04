#!/usr/bin/env python3
"""把 /content 的分类清单落到文本，便于对照。"""
import json, sys, urllib.parse, urllib.request

TOK = "0dfdae3b5fbdbbc13976591ec467c9d44e957c6e6bd676da"
BASE = "http://127.0.0.1:7199/v1/referee"

def call(p, **k):
    u = BASE + "/" + p + ("?" + urllib.parse.urlencode(k) if k else "")
    r = urllib.request.Request(u, headers={"Authorization": "Bearer " + TOK})
    b = json.loads(urllib.request.urlopen(r, timeout=30).read().decode())
    if not b.get("ok"):
        raise RuntimeError(b)
    return b["data"]

d = call("content")
L = []
L.append("== ITEMS ==")
for it in d["items"]:
    L.append(json.dumps(it, ensure_ascii=False))
L.append("")
L.append("== LIQUIDS ==")
for it in d["liquids"]:
    L.append(json.dumps(it, ensure_ascii=False))
L.append("")
L.append("== BLOCKS by category ==")
cats = {}
for b in d["blocks"]:
    cats.setdefault(b["category"], []).append(b)
for c, lst in sorted(cats.items()):
    L.append(f"--- {c} ({len(lst)}) ---")
    for b in sorted(lst, key=lambda b: b["name"]):
        L.append(f"   {b['name']:<24} size={b['size']} hp={b['health']} power={b['hasPower']} cost={b.get('cost')}")
L.append("")
L.append("== UNITS ==")
for u in d["units"]:
    L.append(json.dumps(u, ensure_ascii=False))
open(r"C:\dsh\ai-arena\_work\content.txt", "w", encoding="utf-8").write("\n".join(L))
print("ok")
