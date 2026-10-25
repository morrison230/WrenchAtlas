# -*- coding: utf-8 -*-
"""
WrenchAtlas · 诊断数据检索

给 AI 用的查询接口。不把手册塞进上下文，只按需返回命中的条目。

用法:
  python query.py --list
  python query.py "雨刮不动"
  python query.py P0301
  python query.py --system ignition
  python query.py --pack G:/Projects/WrenchAtlas/packs/suzuki-sx4-2010 "起动机不转"

数据包位置优先级: --pack > 环境变量 WRENCHATLAS_PACK > 脚本相对路径 ../../packs/suzuki-sx4-2010
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 数据包根目录候选（按顺序取第一个存在的）：
#   1. 环境变量 WRENCHATLAS_PACKS
#   2. 项目固定安装位置（skill 装到用户目录后仍能找到）
#   3. 脚本相对位置（源码树内调用）
PACK_ROOTS = [
    Path(r"G:/Projects/WrenchAtlas/packs"),
    HERE.parent.parent / "packs",
]


def pack_roots():
    env = os.environ.get("WRENCHATLAS_PACKS")
    roots = ([Path(env)] if env else []) + PACK_ROOTS
    seen, out = set(), []
    for r in roots:
        rp = r.resolve()
        if rp.exists() and rp not in seen:
            seen.add(rp)
            out.append(rp)
    return out


def available_packs() -> dict:
    """扫描所有车型包（跳过 _ 开头的模板目录）。返回 {id: Path}。"""
    out = {}
    for root in pack_roots():
        for d in sorted(root.iterdir()):
            if not d.is_dir() or d.name.startswith("_"):
                continue
            meta = d / "pack.json"
            if not meta.exists():
                continue
            try:
                pid = json.loads(meta.read_text(encoding="utf-8")).get("id") or d.name
            except Exception:
                pid = d.name
            out.setdefault(pid, d)
    return out


def pack_label(p: Path) -> str:
    """从 pack.json 拼一个可读的车型名。"""
    try:
        m = json.loads((p / "pack.json").read_text(encoding="utf-8"))
    except Exception:
        return p.name
    parts = [m.get("make_cn") or m.get("make"), m.get("model_cn") or m.get("model"),
             m.get("year"), m.get("engine")]
    return " ".join(str(x) for x in parts if x) or p.name


def _circuit_count(p: Path) -> int:
    d = p / "data" / "circuits"
    return len(list(d.glob("*.json"))) if d.exists() else 0


def resolve_pack(arg=None):
    """解析要查哪个车型包。

    优先级：--pack 参数（id 或路径）> 环境变量 WRENCHATLAS_PACK > 数据最全的包
    """
    packs = available_packs()

    if arg:
        if arg in packs:
            return packs[arg]
        p = Path(arg)
        if p.is_dir():
            return p
        raise SystemExit(f"[错误] 没有车型包 {arg}。可用：" +
                         ("、".join(packs) if packs else "（无）"))

    env = os.environ.get("WRENCHATLAS_PACK")
    if env:
        if env in packs:
            return packs[env]
        p = Path(env)
        if p.is_dir():
            return p

    if not packs:
        return PACK_ROOTS[-1] / "suzuki-sx4-2010"   # 保持旧行为，让报错更明确
    return max(packs.values(), key=_circuit_count)


def load_pack(pack: Path):
    circuits = []
    cdir = pack / "data" / "circuits"
    if cdir.exists():
        for f in sorted(cdir.glob("*.json")):
            try:
                c = json.loads(f.read_text(encoding="utf-8"))
                c["_file"] = f.name
                circuits.append(c)
            except Exception as e:
                print(f"[警告] 读取 {f.name} 失败: {e}", file=sys.stderr)
    pages = {}
    pf = pack / "data" / "pages.json"
    if pf.exists():
        for p in json.loads(pf.read_text(encoding="utf-8")).get("pages", []):
            pages[p["id"]] = p
    symptoms = []
    sf = pack / "data" / "symptoms.json"
    if sf.exists():
        symptoms = json.loads(sf.read_text(encoding="utf-8")).get("symptoms", [])
    verified = {}
    vf = pack / "data" / "verified.json"
    if vf.exists():
        try:
            verified = json.loads(vf.read_text(encoding="utf-8"))
        except Exception:
            pass
    # 注入 source_label（中文页标题），让报告与网站显示一致
    for c in circuits:
        raw = str(c.get("source_page", ""))
        p = pages.get(raw.split(",")[0].strip())
        if p:
            c["source_label"] = f'{p["title"]} p{p["page"]}（{p["file"]}）'
    return circuits, pages, symptoms, verified


def match_symptoms(symptoms, kw):
    """按症状名、口语别名、分支内容匹配。"""
    out = []
    for s in symptoms:
        bag = [s.get("label", ""), " ".join(s.get("aka", []) or []),
               s.get("first_question", ""), s.get("also_check", "")]
        for b in s.get("branches", []) or []:
            bag += [b.get("when", ""), b.get("verdict", ""), b.get("check", "")]
        blob = " ".join(bag).lower()
        if kw.lower() in blob:
            score = 0
            if kw.lower() in s.get("label", "").lower():
                score += 10
            if any(kw.lower() in a.lower() for a in (s.get("aka") or [])):
                score += 8
            score += 1
            out.append((score, s))
    out.sort(key=lambda x: -x[0])
    return out


def render_symptoms(matched):
    if not matched:
        return
    print(f"\n{'='*60}")
    print(f"【症状问诊】命中 {len(matched)} 条")
    for _, s in matched[:3]:
        print(f"\n● {s.get('label')}")
        if s.get("aka"):
            print(f"  别称: {' / '.join(s['aka'])}")
        if s.get("first_question"):
            print(f"  先问: {s['first_question']}")
        for i, b in enumerate(s.get("branches", []), 1):
            print(f"    {i}. {b.get('when')}")
            print(f"       → {b.get('verdict')}")
            print(f"       要查: {b.get('check')}")
        if s.get("also_check"):
            print(f"  另见: {s['also_check']}")


def page_of(circuit, pages):
    raw = str(circuit.get("source_page", ""))
    pid = raw.split(",")[0].strip()
    p = pages.get(pid)
    if p:
        return f'{p["title"]} p{p["page"]}（{p["file"]}）'
    return raw


def hit(text, kw):
    return kw.lower() in str(text).lower()


def search(circuits, pages, kw):
    out = []
    for c in circuits:
        score = 0
        why = []
        if hit(c.get("name", ""), kw):
            score += 10
            why.append("系统名")
        if hit(c.get("system", ""), kw):
            score += 6
            why.append("系统标识")
        for h in c.get("diagnosis_hint", []):
            if hit(h, kw):
                score += 5
                why.append(f"诊断提示: {h}")
        for n in c.get("nodes", []):
            if hit(n.get("label", ""), kw) or hit(n.get("sub", ""), kw):
                score += 3
                why.append(f"环节: {n.get('label')}")
            if hit(n.get("detail", ""), kw):
                score += 1
            for pin in n.get("pins", []):
                if hit(pin, kw):
                    score += 4
                    why.append(f"针脚: {pin}")
        for k, v in (c.get("injection_map") or {}).items():
            if hit(k, kw):
                score += 12
                why.append(f"故障码: {k} → 缸{v.get('cylinder')} {v.get('injector')} {v.get('ecm_pin')}")
        for e in c.get("edges", []):
            if hit(e.get("via", ""), kw) or hit(e.get("note", ""), kw):
                score += 2
        if score:
            out.append((score, c, why))
    out.sort(key=lambda x: -x[0])
    return out


def render(results, pages, verified=None):
    verified = verified or {}
    if not results:
        print("未命中。可先 --list 看有哪些系统，或用 --system 指定系统。")
        print("注意：数据只覆盖已录入的系统，未录入的系统请查原厂手册。")
        return
    for score, c, why in results:
        vm = verified.get(c.get("id"), {})
        print(f"\n{'='*60}")
        print(f"【{c.get('name')}】  置信度: {c.get('confidence', '?')}"
              + (f"  已核对 {len(vm)} 处" if vm else ""))
        print(f"来源页: {page_of(c, pages)}")
        if c.get("variant_warning"):
            print(f"⚠ 注意: {c['variant_warning']}")
        if why:
            print(f"命中: {' / '.join(dict.fromkeys(why))}")
        print(f"\n环节（{len(c.get('nodes', []))} 个）:")
        for n in c.get("nodes", []):
            pins = ("  " + " ".join(n.get("pins", []))) if n.get("pins") else ""
            if n.get("id") in vm:
                flag = " ✓已实车核对"
            elif n.get("confidence") == "read-uncertain":
                flag = " ⚠存疑"
            else:
                flag = ""
            print(f"  · {n.get('label')}（{n.get('sub','')}）{pins}{flag}")
            if n.get("uncertain") and n.get("id") not in vm:
                print(f"      存疑: {n['uncertain']}")
            if n.get("id") in vm and vm[n["id"]].get("note"):
                print(f"      核对备注: {vm[n['id']]['note']}")
        hints = c.get("diagnosis_hint", [])
        if hints:
            print(f"\n诊断提示（{len(hints)} 条）:")
            for i, h in enumerate(hints, 1):
                print(f"  {i}. {h}")
        im = c.get("injection_map")
        if im:
            print("\n故障码 → 引脚:")
            for k, v in im.items():
                print(f"  {k} → 缸{v.get('cylinder')} · {v.get('injector')} · {v.get('ecm_pin')} · {v.get('color')}")


def load_report_module(pack: Path):
    """动态加载 web/report.py（单一真源，避免两份生成逻辑漂移）。

    pack 形如 <repo>/packs/<车型>，据此推出 repo/web/report.py。
    找不到就返回 None，由调用方降级。
    """
    repo = pack.parent.parent
    rp = repo / "web" / "report.py"
    if not rp.exists():
        return None
    p = str(repo / "web")
    if p not in sys.path:
        sys.path.insert(0, p)
    try:
        import report  # noqa: F401
        return report
    except Exception:
        return None


def render_report(pack: Path, circuits, verified, system: str | None, out):
    """生成诊断报告并写入 out（None 表示 stdout）。"""
    rep = load_report_module(pack)
    if rep is None:
        print("[错误] 找不到 web/report.py，无法生成报告。", file=sys.stderr)
        return 1
    if system and system not in ("all", "full", "*"):
        sel = [c for c in circuits
               if system in (c.get("system"), c.get("id"), c.get("name"))]
        if not sel:
            print(f"[错误] 没有 {system} 这个系统。用 --list 查看。", file=sys.stderr)
            return 1
        body = rep.render_text(sel[0], verified)
    else:
        body = rep.render_all_text(circuits, verified, pack.name)
    if out:
        Path(out).write_text(body, "utf-8")
        n = body.count("\n") + 1
        print(f"已生成报告: {Path(out).resolve()}  ({n} 行, {len(body)} 字符)")
    else:
        print(body)
    return 0


def load_ocr(pack: Path) -> dict:
    """加载全文字库（builder/ocr.py 的产物）。没有就返回空。"""
    idx = {}
    d = pack / "data" / "ocr"
    if not d.exists():
        return idx
    for f in sorted(d.glob("*.json")):
        if f.name.startswith("_"):
            continue            # _sources.json / _quality_report.json 不是页面索引
        try:
            idx.update(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return idx


def search_fulltext(ocr: dict, q: str, limit: int = 20) -> list:
    """全文字库检索。多词 AND，按命中次数排序。"""
    terms = [t for t in q.lower().split() if t.strip()]
    if not terms or not ocr:
        return []
    out = []
    for key, v in ocr.items():
        txt = v.get("text") or ""
        if not txt:
            continue
        low = txt.lower()
        if not all(t in low for t in terms):
            continue
        pos = low.find(terms[0])
        s = max(0, pos - 60)
        e = min(len(txt), pos + 140)
        out.append({
            "id": key,
            "file": v.get("file"),
            "page": v.get("page"),
            "score": sum(low.count(t) for t in terms),
            "snippet": txt[s:e].replace("\n", " "),
        })
    out.sort(key=lambda x: (-x["score"], x["page"] or 0))
    return out[:limit]


def render_fulltext(hits: list, total: int):
    if not hits:
        print(f"\n全文字库 {total} 页，无命中。")
        return
    print(f"\n{'=' * 60}")
    print(f"【手册全文】命中 {len(hits)} 页（库内共 {total} 页）")
    print("注意：全文来自扫描件 OCR，只用于定位页码。"
          "规格数字（扭矩/间隙）不可直接采信，须看原页核对。")
    for h in hits:
        print(f"\n  · {h['file']}  第 {h['page']} 页（命中 {h['score']} 次）")
        print(f"    {h['snippet'][:180]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("keyword", nargs="?", help="症状 / 系统名 / 故障码 / 连接器号")
    ap.add_argument("--pack", help="车型包 id 或路径，如 toyota-corolla-2014")
    ap.add_argument("--list-packs", action="store_true", help="列出所有已安装的车型包")
    ap.add_argument("--list", action="store_true", help="列出当前车型包的全部系统")
    ap.add_argument("--system", help="按 system 标识精确匹配，如 ignition")
    ap.add_argument("--symptom", help="按症状 id 精确查看，如 no-crank")
    ap.add_argument("--json", action="store_true", help="输出原始 JSON")
    ap.add_argument("--report", nargs="?", const="all", metavar="SYSTEM",
                    help="生成诊断报告（纯文本）。给系统标识则单系统，all 或留空为全量")
    ap.add_argument("-o", "--out", help="报告写入文件（配合 --report）")
    ap.add_argument("--fulltext", action="store_true",
                    help="只搜手册全文（含 scan OCR），返回页码与片段")
    ap.add_argument("--no-fulltext", action="store_true",
                    help="普通查询时不附带全文命中")
    args = ap.parse_args()

    if args.list_packs:
        packs = available_packs()
        if not packs:
            print("没有找到任何车型包。")
            print("用 builder/new_pack.py 建一个，或设环境变量 WRENCHATLAS_PACKS")
            return
        cur = resolve_pack(None)
        print(f"已安装 {len(packs)} 个车型包：\n")
        for pid, p in packs.items():
            n = _circuit_count(p)
            pf = p / "data" / "pages.json"
            pages = 0
            if pf.exists():
                try:
                    pages = len(json.loads(pf.read_text(encoding="utf-8")).get("pages", []))
                except Exception:
                    pass
            mark = " ←默认" if p.resolve() == cur.resolve() else ""
            print(f"  {pid:<26} {pack_label(p)}")
            print(f"  {'':<26}   {n} 个系统 / {pages} 页 / {p}{mark}")
        return

    pack = resolve_pack(args.pack)
    if not (pack / "data" / "circuits").exists():
        print(f"[错误] 数据包不可用: {pack}")
        print("用 --pack 指定车型 id，或 --list-packs 看有哪些")
        sys.exit(1)

    circuits, pages, symptoms, verified = load_pack(pack)
    ocr = load_ocr(pack)

    if args.fulltext:
        if not args.keyword:
            print(f"全文字库: {len(ocr)} 页。用法: query.py --fulltext \"关键词\"")
            return
        render_fulltext(search_fulltext(ocr, args.keyword), len(ocr))
        return

    if args.report is not None:
        sys.exit(render_report(pack, circuits, verified, args.report, args.out))

    if args.list:
        print(f"车型包: {pack_label(pack)}  ({pack.name})")
        print(f"已录入 {len(circuits)} 个系统，{len(symptoms)} 类症状：\n")
        for c in circuits:
            unc = sum(1 for n in c.get("nodes", []) if n.get("confidence") == "read-uncertain")
            print(f"  {c.get('system',''):<16} {c.get('name')}")
            print(f"  {'':<16}   {len(c.get('nodes',[]))} 环节 / "
                  f"{len(c.get('edges',[]))} 连接 / {len(c.get('diagnosis_hint',[]))} 条提示"
                  f"{' / %d 处存疑' % unc if unc else ''}")
            print(f"  {'':<16}   来源: {page_of(c, pages)}")
        if symptoms:
            print("\n  症状入口:")
            for s in symptoms:
                print(f"    {s.get('label')}  （{len(s.get('branches',[]))} 个分支）")
        return

    if args.symptom:
        matched = [(99, s) for s in symptoms if s.get("id") == args.symptom]
        if not matched:
            print(f"没有 id={args.symptom} 的症状。可用 --list 查看。")
            sys.exit(1)
        render_symptoms(matched)
        return

    if args.system:
        sel = [c for c in circuits if c.get("system") == args.system]
        if not sel:
            print(f"没有 system={args.system} 的系统。试试 --list")
            sys.exit(1)
        if args.json:
            print(json.dumps(sel, ensure_ascii=False, indent=1))
        else:
            render([(99, c, []) for c in sel], pages, verified)
        return

    if not args.keyword:
        ap.print_help()
        return

    results = search(circuits, pages, args.keyword)
    sym = match_symptoms(symptoms, args.keyword)
    ft = [] if args.no_fulltext else search_fulltext(ocr, args.keyword, limit=8)
    if args.json:
        print(json.dumps({
            "circuits": [{"score": s, "circuit": c, "why": w} for s, c, w in results],
            "symptoms": [{"score": s, "symptom": x} for s, x in sym],
            "fulltext": ft,
        }, ensure_ascii=False, indent=1))
    else:
        render_symptoms(sym)
        if results:
            render(results, pages, verified)
        if ft:
            render_fulltext(ft, len(ocr))
        if not results and not sym and not ft:
            print(f"\n未命中（结构 {len(circuits)} 个系统 / 全文 {len(ocr)} 页）。")
            print("可 --list 看有哪些系统，--list-packs 看有哪些车型。")
            print("换个说法试试；或该内容确实没录入。")


if __name__ == "__main__":
    main()
