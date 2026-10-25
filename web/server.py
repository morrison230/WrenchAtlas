# -*- coding: utf-8 -*-
"""
WrenchAtlas · 本地服务

两个能力：
  1. 页面列表与图片服务（浏览 114 页增强图）
  2. 点击追线：点图上任意一点，返回它所在的整块连通笔画（L1）

连通域按页缓存，首次查询约 3–4 秒，之后毫秒级。

启动:
  python web/server.py --pack packs/suzuki-sx4-2010 --port 3000
"""
import argparse
import base64
import hashlib
import io
import json
import re
import socket
import sys
from collections import OrderedDict, defaultdict
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent))
import report  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"

CONF = {
    "packs": {},      # pack_id -> Path（启动时扫描 packs/*/pack.json）
    "default": "",    # 默认车型包 id
    "pages": {},      # pack_id -> [page records]
    "conn": {},       # pack_id -> 连接器索引（懒加载缓存）
}
CACHE: "OrderedDict[str, tuple]" = OrderedDict()
CACHE_MAX = 3
OCR_CACHE: dict = {}   # pack_id -> 全文 OCR 索引


def discover_packs(root: Path) -> dict:
    """扫描 packs/ 下所有带 pack.json 的车型包。

    以 _ 开头的目录（_template 等）视为模板，不参与运行时。
    """
    out = {}
    base = root / "packs"
    if not base.exists():
        return out
    for d in sorted(base.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        meta = d / "pack.json"
        if not meta.exists():
            continue
        try:
            m = json.loads(meta.read_text("utf-8"))
        except Exception:
            continue
        pid = m.get("id") or d.name
        out[pid] = d.resolve()
    return out


def pack_path(pid: str | None = None) -> Path:
    """解析车型包路径。pid 为空时用默认包。"""
    packs = CONF["packs"]
    if not packs:
        raise HTTPException(503, "没有可用的车型包")
    if not pid:
        pid = CONF["default"]
    p = packs.get(pid)
    if p is None:
        raise HTTPException(404, f"没有车型包 {pid}")
    return p


def pack_meta(pid: str) -> dict:
    try:
        return json.loads((CONF["packs"][pid] / "pack.json").read_text("utf-8"))
    except Exception:
        return {"id": pid}


def pages_of(pid: str | None = None) -> list:
    """取某车型包的页面索引（懒加载 + 缓存）。"""
    p = pack_path(pid)
    key = p.name
    if key not in CONF["pages"]:
        f = p / "data" / "pages.json"
        CONF["pages"][key] = (json.loads(f.read_text("utf-8"))["pages"]
                              if f.exists() else [])
    return CONF["pages"][key]

# 连接器号形态：字母 1~3 个 + 数字，允许中间空格（如 "E382 G334 14"）
CONN_TOKEN = re.compile(r"\b([A-Z]{1,3})[\s-]?(\d{1,4})\b")


def build_conn_index(circuits):
    """建立 {连接器: {system: 次数}} 的反查索引，用于跨系统牵连提示。"""
    idx = defaultdict(lambda: defaultdict(int))
    for c in circuits:
        for n in c.get("nodes", []):
            seen = set()
            for pin in n.get("pins", []) or []:
                for m in CONN_TOKEN.finditer(str(pin).upper()):
                    key = f"{m.group(1)}{m.group(2)}"
                    if key in seen:
                        continue
                    seen.add(key)
                    idx[key][c.get("system")] += 1
    return idx


def attach_shared(circuit, conn_idx, name_by_sys):
    """给每个节点挂上「这些连接器还出现在哪些系统」。"""
    for n in circuit.get("nodes", []):
        shared = []
        seen = set()
        for pin in n.get("pins", []) or []:
            for m in CONN_TOKEN.finditer(str(pin).upper()):
                key = f"{m.group(1)}{m.group(2)}"
                if key in seen:
                    continue
                seen.add(key)
                sysmap = conn_idx.get(key, {})
                others = [s for s in sysmap if s != circuit.get("system")]
                if len(sysmap) >= 2 and others:
                    shared.append({
                        "conn": key,
                        "all_systems": [name_by_sys.get(s, s) for s in sysmap],
                        "others": [name_by_sys.get(s, s) for s in others],
                        "count": len(sysmap),
                    })
        if shared:
            n["shared_connectors"] = shared
    return circuit

app = FastAPI(title="WrenchAtlas")


# ---------- 连通域缓存 ----------

def build_segments(img_path: Path):
    """
    按方向分离出独立线段，并按端点邻近建立邻接关系。
      水平段、垂直段各自成段（拐角处自然断开）
      端点相近（拐角）-> 连成一条折线
      中部交叉（十字）-> 端点相距远，不会误连
    """
    arr = np.array(Image.open(img_path).convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    mask = (gray < 200).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))

    labels = np.zeros(gray.shape, np.uint16)
    segs = []
    for direction, kernel in (("h", (60, 1)), ("v", (1, 60))):
        m = cv2.morphologyEx(
            mask, cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, kernel))
        n, lab = cv2.connectedComponents(m, connectivity=8)
        for i in range(1, n):
            ys, xs = np.nonzero(lab == i)
            if len(ys) < 40:
                continue
            sid = len(segs) + 1
            if sid >= 65000:
                break
            y1, y2, x1, x2 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
            labels[lab == i] = sid
            if direction == "h":
                yc = (y1 + y2) // 2
                ends = [(x1, yc), (x2, yc)]
            else:
                xc = (x1 + x2) // 2
                ends = [(xc, y1), (xc, y2)]
            segs.append({"id": sid, "dir": direction,
                         "bbox": [x1, y1, x2, y2], "ends": ends,
                         "area": int(len(ys))})

    LINK = 24
    adj = defaultdict(set)
    for i, a in enumerate(segs):
        ax1, ay1, ax2, ay2 = a["bbox"]
        for j in range(i + 1, len(segs)):
            b = segs[j]
            bx1, by1, bx2, by2 = b["bbox"]
            if (bx1 - LINK > ax2 or ax1 - LINK > bx2 or
                    by1 - LINK > ay2 or ay1 - LINK > by2):
                continue
            if any((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 <= LINK * LINK
                   for p in a["ends"] for q in b["ends"]):
                adj[a["id"]].add(b["id"])
                adj[b["id"]].add(a["id"])
    return labels, gray.shape, adj


def collect_segments(adj, start: int, limit: int = 12):
    """
    从点击的段出发，沿端点连接扩展出一条折线。
    上限 12 段：防止在元件密集区（如开关内部）无限串成一大片。
    """
    seen = {start}
    q = [start]
    while q and len(seen) < limit:
        cur = q.pop(0)
        for nb in adj.get(cur, ()):
            if nb not in seen:
                seen.add(nb)
                q.append(nb)
    return seen


def get_labels(page_name: str, pid: str | None = None):
    key = f"{(pid or CONF['default'])}::{page_name}"
    if key in CACHE:
        CACHE.move_to_end(key)
        return CACHE[key]
    path = pack_path(pid) / "pages" / page_name
    if not path.exists():
        raise HTTPException(404, "page not found")
    data = build_segments(path)
    CACHE[key] = data
    if len(CACHE) > CACHE_MAX:
        CACHE.popitem(last=False)
    return data


def nearest_hit(labels: np.ndarray, x: int, y: int, radius: int = 70):
    """点在空白处时，向外找最近的笔画。"""
    h, w = labels.shape
    if 0 <= y < h and 0 <= x < w and labels[y, x]:
        return int(labels[y, x]), (x, y)
    for r in range(4, radius, 4):
        y1, y2 = max(0, y - r), min(h, y + r + 1)
        x1, x2 = max(0, x - r), min(w, x + r + 1)
        win = labels[y1:y2, x1:x2]
        if win.any():
            ys, xs = np.nonzero(win)
            d = (ys + y1 - y) ** 2 + (xs + x1 - x) ** 2
            i = int(np.argmin(d))
            return int(win[ys[i], xs[i]]), (int(xs[i] + x1), int(ys[i] + y1))
    return 0, (x, y)


def make_mask(sel: np.ndarray, color=(255, 198, 0, 168)):
    """生成裁剪后的高亮层，返回 bbox 与 base64 PNG。"""
    ys, xs = np.nonzero(sel)
    if len(ys) == 0:
        return None
    y1, y2 = int(ys.min()), int(ys.max()) + 1
    x1, x2 = int(xs.min()), int(xs.max()) + 1
    sub = sel[y1:y2, x1:x2]

    rgba = np.zeros((y2 - y1, x2 - x1, 4), dtype=np.uint8)
    rgba[sub] = color
    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG", optimize=True)
    return {
        "bbox": [x1, y1, x2, y2],
        "area": int(sub.sum()),
        "mask": "data:image/png;base64," +
                base64.b64encode(buf.getvalue()).decode("ascii"),
    }


# ---------- 路由 ----------

@app.get("/api/packs")
def api_packs():
    """列出全部车型包。前端用它渲染车型切换器。"""
    out = []
    for pid, p in CONF["packs"].items():
        m = pack_meta(pid)
        out.append({
            "id": pid,
            "make": m.get("make", ""),
            "make_cn": m.get("make_cn", ""),
            "model": m.get("model", ""),
            "model_cn": m.get("model_cn", ""),
            "year": m.get("year"),
            "engine": m.get("engine", ""),
            "label": m.get("label") or " ".join(
                x for x in [m.get("make_cn") or m.get("make"),
                            m.get("model_cn") or m.get("model"),
                            str(m.get("year") or ""),
                            m.get("engine", "")] if x),
            "pages": len(pages_of(pid)),
            "is_default": pid == CONF["default"],
        })
    return {"packs": out, "default": CONF["default"]}


@app.get("/api/pack")
def api_pack(pack: str | None = Query(None)):
    """当前车型包元信息。"""
    p = pack_path(pack)
    pid = pack or CONF["default"]
    return {"id": pid, "meta": pack_meta(pid), "pages": len(pages_of(pid))}


@app.get("/api/circuits")
def api_circuits(pack: str | None = Query(None)):
    """返回所有信号流图数据，并把 source_page 解析成可打开的图片名。"""
    pid = pack or CONF["default"]
    cdir = pack_path(pack) / "data" / "circuits"
    if not cdir.exists():
        return {"circuits": []}
    by_id = {p["id"]: p for p in pages_of(pack)}
    circuits = []
    for f in sorted(cdir.glob("*.json")):
        try:
            c = json.loads(f.read_text("utf-8"))
        except Exception:
            continue
        raw = str(c.get("source_page", ""))
        pid_page = raw.split(",")[0].strip()
        page = by_id.get(pid_page)
        c["source_image"] = page["image"].split("/")[-1] if page else None
        c["source_label"] = (f'{page["title"]} p{page["page"]}（{page["file"]}）'
                             if page else raw)
        c["file"] = f.name
        circuits.append(c)

    if pid not in CONF["conn"]:
        CONF["conn"][pid] = build_conn_index(circuits)
    name_by_sys = {c.get("system"): c.get("name") for c in circuits}
    for c in circuits:
        attach_shared(c, CONF["conn"][pid], name_by_sys)
    return {"circuits": circuits, "pack": pid}


@app.get("/api/symptoms")
def api_symptoms(pack: str | None = Query(None)):
    """症状索引，并把 circuits 的 system 标识解析成中文名与文件名。"""
    f = pack_path(pack) / "data" / "symptoms.json"
    if not f.exists():
        return {"symptoms": []}
    d = json.loads(f.read_text("utf-8"))

    names = {}
    cdir = pack_path(pack) / "data" / "circuits"
    if cdir.exists():
        for cf in cdir.glob("*.json"):
            try:
                c = json.loads(cf.read_text("utf-8"))
                names[c["system"]] = {"name": c["name"], "id": c["id"], "file": cf.name}
            except Exception:
                pass

    for s in d.get("symptoms", []):
        for b in s.get("branches", []):
            b["circuit_info"] = [
                names.get(x, {"name": x, "id": x, "file": None})
                for x in b.get("circuits", [])
            ]
    return d


def load_ocr(pid: str | None = None) -> dict:
    """加载本车型包的全文 OCR 索引（懒加载 + 缓存）。

    数据来自 data/ocr/*.json，由 builder/ocr.py 生成。
    """
    p = pack_path(pid)
    key = p.name
    if key in OCR_CACHE:
        return OCR_CACHE[key]
    idx = {}
    d = p / "data" / "ocr"
    if d.exists():
        for f in sorted(d.glob("*.json")):
            if f.name.startswith("_"):
                continue        # _sources.json / _quality_report.json 不是页面索引
            try:
                idx.update(json.loads(f.read_text("utf-8")))
            except Exception:
                continue
    OCR_CACHE[key] = idx
    return idx


def search_manual(pid: str | None, q: str, limit: int = 30) -> list:
    """在全文字库里搜。多词视为 AND，按命中次数排序。"""
    idx = load_ocr(pid)
    if not idx:
        return []
    terms = [t for t in q.lower().split() if t.strip()]
    if not terms:
        return []
    out = []
    for key, v in idx.items():
        txt = v.get("text") or ""
        if not txt:
            continue
        low = txt.lower()
        if not all(t in low for t in terms):
            continue
        score = sum(low.count(t) for t in terms)
        pos = low.find(terms[0])
        s = max(0, pos - 70)
        e = min(len(txt), pos + 150)
        snippet = txt[s:e].replace("\n", " ")
        out.append({
            "id": key,
            "doc": v.get("doc"),
            "file": v.get("file"),
            "page": v.get("page"),
            "score": score,
            "chars": v.get("chars", 0),
            "quality": v.get("quality"),
            "grade": v.get("grade"),
            "snippet": ("…" if s > 0 else "") + snippet + ("…" if e < len(txt) else ""),
        })
    # 相关性优先，质量作为次级（质量差的在后面，但不埋没最相关的页）
    rank = {"good": 0, "sparse": 1, "fair": 2, "poor": 3, None: 1}
    out.sort(key=lambda x: (-x["score"], rank.get(x["grade"], 1),
                            x["doc"] or "", x["page"] or 0))
    return out[:limit]


def ocr_stats(pid: str | None = None) -> dict:
    """全文库的分级统计，用于页面提示。"""
    idx = load_ocr(pid)
    stat = {}
    for v in idx.values():
        g = v.get("grade") or "unknown"
        stat[g] = stat.get(g, 0) + 1
    stat["total"] = len(idx)
    return stat


def load_ocr_sources(pid: str | None = None) -> dict:
    """doc_id -> {文件名/相对路径: PDF 绝对路径}。用于按需渲染原页。"""
    p = pack_path(pid)
    f = p / "data" / "ocr" / "_sources.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text("utf-8"))
    except Exception:
        return {}


def resolve_source(pid: str | None, file: str) -> Path | None:
    """在 _sources.json 里找 PDF 路径。key 可能是文件名或相对路径。"""
    srcs = load_ocr_sources(pid)
    for doc in srcs.values():
        files = doc.get("files", {})
        hit = files.get(file) or files.get(file.replace("\\", "/"))
        if hit and Path(hit).exists():
            return Path(hit)
        # 退一步：按文件名匹配
        for k, v in files.items():
            if Path(k).name == Path(file).name and Path(v).exists():
                return Path(v)
    return None


@app.get("/api/manualpage")
def api_manualpage(file: str = Query(...), page: int = Query(..., ge=1),
                   dpi: int = Query(150, ge=72, le=400),
                   pack: str | None = Query(None)):
    """按需渲染手册原页（PNG）。结果缓存在 data/ocr/pagecache/。"""
    src = resolve_source(pack, file)
    if src is None:
        raise HTTPException(404, f"找不到原文件 {file}（先跑 builder/ocr_sources.py）")

    cache_dir = pack_path(pack) / "data" / "ocr" / "pagecache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    tag = hashlib.md5(f"{src}|{page}|{dpi}".encode("utf-8")).hexdigest()[:16]
    cached = cache_dir / f"{tag}.png"
    if cached.exists():
        return FileResponse(cached, media_type="image/png")

    import pymupdf
    try:
        doc = pymupdf.open(src)
    except Exception as e:
        raise HTTPException(500, f"打不开 {src.name}: {e}")
    if page > doc.page_count:
        doc.close()
        raise HTTPException(404, f"{src.name} 只有 {doc.page_count} 页")
    pix = doc[page - 1].get_pixmap(dpi=dpi)
    pix.save(cached)
    n = doc.page_count
    doc.close()
    return FileResponse(cached, media_type="image/png",
                        headers={"X-Total-Pages": str(n)})


@app.get("/api/search")
def api_search(q: str = Query(..., min_length=1), pack: str | None = Query(None),
               manual: int = 1):
    """全站搜索：连接器号 / 故障码 / 症状 / 系统名 / 诊断提示 / 手册全文。"""
    ql = q.strip().lower()
    res = {"query": q, "circuits": [], "pages": [], "symptoms": [], "manual": []}
    if not ql:
        return res

    cdir = pack_path(pack) / "data" / "circuits"
    if cdir.exists():
        for f in sorted(cdir.glob("*.json")):
            try:
                c = json.loads(f.read_text("utf-8"))
            except Exception:
                continue
            hits = []
            if ql in str(c.get("name", "")).lower():
                hits.append({"kind": "系统", "text": c.get("name")})
            for n in c.get("nodes", []):
                pins = n.get("pins") or []
                hitpin = next((p for p in pins if ql in str(p).lower()), None)
                if hitpin:
                    hits.append({"kind": "针脚", "text": f'{n.get("label")} · {hitpin}'})
                elif ql in str(n.get("label", "")).lower():
                    hits.append({"kind": "环节", "text": n.get("label")})
                elif ql in str(n.get("detail", "")).lower():
                    hits.append({"kind": "说明", "text": f'{n.get("label")}：{n.get("detail","")[:60]}'})
            for h in c.get("diagnosis_hint", []) or []:
                if ql in h.lower():
                    hits.append({"kind": "诊断", "text": h})
            if hits:
                res["circuits"].append({
                    "id": c.get("id"), "system": c.get("system"),
                    "name": c.get("name"), "confidence": c.get("confidence"),
                    "hits": hits[:8], "total": len(hits),
                })

    for p in pages_of(pack):
        if ql in str(p.get("title", "")).lower():
            res["pages"].append({
                "id": p["id"], "title": p["title"], "page": p["page"],
                "image": p["image"].split("/")[-1], "kind": p.get("kind"),
            })
    res["pages"] = res["pages"][:20]

    sf = pack_path(pack) / "data" / "symptoms.json"
    if sf.exists():
        for s in json.loads(sf.read_text("utf-8")).get("symptoms", []):
            bag = [s.get("label", ""), " ".join(s.get("aka", []) or []),
                   s.get("first_question", "")]
            for b in s.get("branches", []) or []:
                bag.append(b.get("when", ""))
                bag.append(b.get("verdict", ""))
                bag.append(b.get("check", ""))
            if ql in " ".join(bag).lower():
                res["symptoms"].append({
                    "id": s.get("id"), "label": s.get("label"),
                    "aka": s.get("aka", []),
                })

    if manual:
        res["manual"] = search_manual(pack, q)
        # 标注来源文档，让用户分清"维修手册正文"和"电路图"
        pid = pack or CONF["default"]
        titles = {m.get("doc_id"): m.get("title") or m.get("doc_id")
                  for m in pack_meta(pid).get("manuals", [])}
        for h in res["manual"]:
            h["doc_title"] = titles.get(h.get("doc"), h.get("doc"))

    res["total"] = (len(res["circuits"]) + len(res["pages"]) +
                    len(res["symptoms"]) + len(res["manual"]))
    res["manual_pages"] = len(load_ocr(pack))
    res["manual_stats"] = ocr_stats(pack)
    return res


@app.get("/api/fulltext")
def api_fulltext(q: str = Query(..., min_length=1), pack: str | None = Query(None),
                 limit: int = 40):
    """只搜手册全文。给 AI 和"翻书"场景用。"""
    return {"query": q, "hits": search_manual(pack, q, limit=limit),
            "indexed_pages": len(load_ocr(pack))}


def _verified_marks(pid: str | None = None) -> dict:
    """读取实车核对记录（与 /api/verified 同源）。"""
    f = pack_path(pid) / "data" / "verified.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text("utf-8"))
    except Exception:
        return {}


@app.get("/api/verified")
def api_verified(pack: str | None = Query(None)):
    """实车核对标记。单独存一个文件，不污染 circuits 原始数据。"""
    f = pack_path(pack) / "data" / "verified.json"
    if not f.exists():
        return {"marks": {}, "total": 0}
    d = json.loads(f.read_text("utf-8"))
    total = sum(len(v) for v in d.values())
    return {"marks": d, "total": total}


class VerifyReq(BaseModel):
    circuit_id: str
    node_id: str
    verified: bool = True
    note: str = ""


@app.post("/api/verify")
def api_verify(req: VerifyReq, pack: str | None = Query(None)):
    f = pack_path(pack) / "data" / "verified.json"
    d = json.loads(f.read_text("utf-8")) if f.exists() else {}
    d.setdefault(req.circuit_id, {})
    if req.verified:
        d[req.circuit_id][req.node_id] = {
            "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "note": req.note.strip(),
        }
    else:
        d[req.circuit_id].pop(req.node_id, None)
        if not d[req.circuit_id]:
            d.pop(req.circuit_id)
    f.write_text(json.dumps(d, ensure_ascii=False, indent=1), "utf-8")
    total = sum(len(v) for v in d.values())
    return {"ok": True, "total": total,
            "count": len(d.get(req.circuit_id, {}))}


def _pick_circuit(circuits, key: str):
    for c in circuits:
        if key in (c.get("system"), c.get("id"), c.get("name")):
            return c
    return None


@app.get("/report")
def report_page(system: str = Query(..., alias="sys"),
                pack: str | None = Query(None)):
    """单系统 A4 打印页。"""
    c = _pick_circuit(api_circuits(pack)["circuits"], system)
    if not c:
        raise HTTPException(404, "system not found")
    html = report.render_html(c, _verified_marks(pack))
    return HTMLResponse(html)


@app.get("/api/report.txt")
def api_report_txt(system: str | None = Query(None, alias="sys"),
                   full: int = 0, download: int = 0,
                   pack: str | None = Query(None)):
    """纯文本报告。不带 sys 或 full=1 时导出全量。"""
    circuits = api_circuits(pack)["circuits"]
    ver = _verified_marks(pack)
    if full or not system:
        body = report.render_all_text(circuits, ver, pack_path(pack).name)
        fname = f"WrenchAtlas-full-{datetime.now():%Y%m%d-%H%M}.txt"
    else:
        c = _pick_circuit(circuits, system)
        if not c:
            raise HTTPException(404, "system not found")
        body = report.render_text(c, ver)
        fname = f"WrenchAtlas-{c.get('system','report')}-{datetime.now():%Y%m%d-%H%M}.txt"
    headers = {"Content-Disposition": f'attachment; filename="{fname}"'} if download else {}
    return PlainTextResponse(body, headers=headers)


@app.get("/api/pages")
def api_pages(pack: str | None = Query(None)):
    pid = pack or CONF["default"]
    return {"pack": pack_meta(pid), "pages": pages_of(pack), "pack_id": pid}


@app.get("/api/trace")
def api_trace(page: str = Query(...), x: int = Query(...), y: int = Query(...),
              pack: str | None = Query(None)):
    if not page.endswith(".png"):
        page += ".png"
    labels, shape, adj = get_labels(page, pack)
    h, w = shape
    if not (0 <= x < w and 0 <= y < h):
        raise HTTPException(400, "point out of range")
    label, hit = nearest_hit(labels, x, y, radius=100)
    if label == 0:
        return JSONResponse({"found": False})
    seg_ids = collect_segments(adj, label)
    lut = np.zeros(65536, dtype=bool)
    lut[list(seg_ids)] = True
    sel = lut[labels]
    m = make_mask(sel)
    if not m:
        return JSONResponse({"found": False})
    return JSONResponse({"found": True, "hit": list(hit),
                         "segments": len(seg_ids), **m})


@app.get("/media/{kind}/{name}")
def media(kind: str, name: str, pack: str | None = Query(None)):
    if kind not in ("pages", "thumbs"):
        raise HTTPException(404)
    base = (pack_path(pack) / kind).resolve()
    path = (base / name).resolve()
    if not str(path).startswith(str(base)) or not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/viewer")
def viewer():
    return FileResponse(STATIC / "viewer.html")


@app.get("/flow")
def flow():
    return FileResponse(STATIC / "flow.html")


@app.get("/symptom")
def symptom():
    return FileResponse(STATIC / "symptom.html")


@app.get("/search")
def search_page():
    return FileResponse(STATIC / "search.html")


@app.get("/checklist")
def checklist():
    return FileResponse(STATIC / "checklist.html")


def local_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return ips


def port_busy(port: int) -> bool:
    s = socket.socket()
    try:
        s.bind(("0.0.0.0", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default=None,
                    help="默认车型包 id 或路径。省略则自动选第一个可用的")
    ap.add_argument("--port", type=int, default=3000)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    url = f"http://127.0.0.1:{args.port}"

    if port_busy(args.port):
        print(f"\n端口 {args.port} 已被占用 —— 服务可能已经在运行了。")
        print(f"直接打开：{url}\n")
        if not args.no_browser:
            import webbrowser
            webbrowser.open(url)
        return

    # 扫描全部车型包 —— 多车型并存的核心
    packs = discover_packs(ROOT)
    if not packs:
        print("\n[错误] packs/ 下没有找到任何车型包（需有 pack.json）")
        print("用 builder/new_pack.py 建一个：")
        print("  python builder/new_pack.py --id brand-model-year "
              "--make Brand --model Model --year 2020\n")
        return
    CONF["packs"] = packs

    # 默认包解析：--pack 可以是 id，也可以是路径
    default = None
    if args.pack:
        if args.pack in packs:
            default = args.pack
        else:
            p = Path(args.pack)
            p = (ROOT / p).resolve() if not p.is_absolute() else p
            if p.name in packs:
                default = p.name

    # 没指定时按"数据完整度"挑，不按字母序
    #   pack.json 显式标注 default:true 的最优先，其次比 circuits 数量
    def completeness(pid: str):
        cdir = packs[pid] / "data" / "circuits"
        n = len(list(cdir.glob("*.json"))) if cdir.exists() else 0
        try:
            meta = json.loads((packs[pid] / "pack.json").read_text("utf-8"))
        except Exception:
            meta = {}
        return (bool(meta.get("default")), n)

    if default is None:
        default = max(packs, key=completeness)
    CONF["default"] = default

    usable = []
    for pid, p in packs.items():
        if (p / "data" / "pages.json").exists():
            usable.append(pid)
        else:
            print(f"[提示] {pid} 还没有页面索引，跳过（先跑 builder/index.py）")
    if not usable:
        print("\n[错误] 所有车型包都缺 data/pages.json")
        print("先运行 builder/enhance.py 和 builder/index.py\n")
        return
    if default not in usable:
        default = usable[0]
        CONF["default"] = default

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    print("\n" + "=" * 58)
    print("  WrenchAtlas 已启动")
    print(f"  车型包 {len(usable)} 个：")
    for pid in usable:
        m = pack_meta(pid)
        mark = " ←默认" if pid == default else ""
        print(f"    {pid:<24} {m.get('make','')} {m.get('model','')} "
              f"{m.get('year','')} {m.get('engine','')}  "
              f"{len(pages_of(pid))} 页{mark}")
    print(f"  本机:   {url}")
    for ip in local_ips():
        print(f"  手机:   http://{ip}:{args.port}   （同一 WiFi）")
    print("=" * 58)

    # 缺数据时的明确提示 —— 不要让人对着 404 的图猜
    dflt = pack_path(default)
    n_idx = len(pages_of(default))
    pdir = dflt / "pages"
    n_img = len(list(pdir.glob("*.png"))) if pdir.exists() else 0
    if n_idx and not n_img:
        print("  [提示] 有页面索引但没有页图，网站里所有图片会打不开。")
        print("         页图需自己从手册生成（版权原因仓库不提供）：")
        print(f"         python builder/enhance.py --src <手册目录> --out {dflt.as_posix()}/pages")
        print()
    ocr_dir = dflt / "data" / "ocr"
    n_ocr = len([f for f in ocr_dir.glob("*.json") if not f.name.startswith("_")]) if ocr_dir.exists() else 0
    if not n_ocr:
        print("  [提示] 没有全文索引，搜索只返回结构化结果（全文区为空）。")
        print("         要搜整本手册：python builder/ocr.py --src <手册目录> "
              f"--pack {dflt.as_posix()} --doc-id <id>")
        print()
    print("  关闭此窗口即停止服务\n")

    if not args.no_browser:
        import threading
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
