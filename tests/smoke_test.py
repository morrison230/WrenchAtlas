# -*- coding: utf-8 -*-
"""冒烟测试：首页 / 页面API / 图片 / 点击追线"""
import json
import time
import urllib.parse
import urllib.request

B = "http://127.0.0.1:3000"


def get(path, timeout=40):
    t0 = time.time()
    with urllib.request.urlopen(B + path, timeout=timeout) as r:
        body = r.read()
        return r.status, body, time.time() - t0


s, body, dt = get("/")
print(f"[首页] {s}  {len(body)}B  {dt*1000:.0f}ms")

s, body, dt = get("/api/pages")
d = json.loads(body.decode("utf-8"))
print(f"[页面API] {s}  共 {len(d['pages'])} 页  {dt*1000:.0f}ms")
p0 = d["pages"][0]
print("   首条 id:", p0["id"])
print("   首条 title:", p0["title"], "| system:", p0["system"], "| kind:", p0["kind"])
wiper = [p for p in d["pages"] if "雨刮" in p["title"] and p["kind"] == "wiring"][0]
print("   雨刮页:", wiper["id"], wiper["size"])

s, body, dt = get("/media/pages/" + urllib.parse.quote(wiper["image"].split("/")[-1]))
print(f"[大图] {s}  {len(body)/1024:.0f}KB  {dt*1000:.0f}ms")

s, body, dt = get("/media/" + urllib.parse.quote(wiper["thumb"], safe="/"))
print(f"[缩略图] {s}  {len(body)/1024:.0f}KB  {dt*1000:.0f}ms")

name = wiper["image"].split("/")[-1]
for (x, y) in [(1500, 1600), (1200, 1400), (2000, 1800), (820, 1228)]:
    q = f"/api/trace?page={urllib.parse.quote(name)}&x={x}&y={y}"
    s, body, dt = get(q)
    r = json.loads(body.decode("utf-8"))
    tag = f"found={r.get('found')}"
    if r.get("found"):
        b = r["bbox"]
        tag += f" bbox={b} area={r['area']} maskKB={len(r['mask'])/1024:.0f} hit={r['hit']}"
    print(f"[追线 ({x},{y})] {s}  {dt*1000:.0f}ms  {tag}")
