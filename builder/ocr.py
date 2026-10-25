# -*- coding: utf-8 -*-
"""
全文 OCR 管道：把扫描版手册变成可检索文本。

用 Windows 内置 OCR（Windows.Media.Ocr），不依赖第三方大包：
  · 零下载，系统自带简体中文识别
  · 实测 200–750ms/页，1600 页约 20 分钟

**定位：只用来建索引，不做数据来源。**
实测数字类识别不可靠（"M10" 可能成 "MIO"，表格里的规格数字尤其差），
所以产物只用于"这个问题在第几页"——真正的规格数值必须人工看原图。

用法:
  python builder/ocr.py --src <手册目录> --pack packs/<车型> --doc-id <doc_id>
  python builder/ocr.py --src <目录> --pack packs/x --doc-id x --limit 10   # 试跑
  python builder/ocr.py --src <目录> --pack packs/x --doc-id x --skip-existing
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pymupdf
from PIL import Image

# Windows 控制台默认 GBK，输出 ✓ 之类的符号会直接抛 UnicodeEncodeError。
# 这里强制把 stdout/stderr 转成 UTF-8，让新人在任何终端都能跑。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError, ValueError):
    pass

HERE = Path(__file__).resolve().parent
PS1 = HERE / "ocr_win.ps1"
ROOT = HERE.parent

# 每批渲染多少页送去 OCR。太大占内存和磁盘，太小 PowerShell 启动开销占比高。
BATCH = 40

CJK = r"\u4e00-\u9fff\u3400-\u4dbf"


def clean_text(t: str) -> str:
    """清理 Windows OCR 的中文输出。

    主要问题是每个汉字之间插空格（"注 意 事 项"），以及全角标点前后带空格。
    英文/数字之间的空格必须保留（"MTR 10A"），所以只处理汉字相邻的情况。
    """
    if not t:
        return ""
    s = t.replace("\r\n", "\n").replace("\r", "\n")
    # 汉字之间的空格去掉，反复跑到不变为止（"注 意 事 项" 要跑 3 遍）
    pat = re.compile(rf"(?<=[{CJK}])\s+(?=[{CJK}])")
    for _ in range(6):
        new = pat.sub("", s)
        if new == s:
            break
        s = new
    # 汉字与全角标点之间
    s = re.sub(rf"(?<=[{CJK}])\s+(?=[，。、；：！？）】」』…])", "", s)
    s = re.sub(rf"(?<=[（【「『])\s+(?=[{CJK}])", "", s)
    # 折叠多余空格，但保留单个空格
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def render_batch(doc, pages, out_dir: Path, dpi: int) -> list[str]:
    """渲染指定页到 out_dir，返回文件名列表。"""
    names = []
    for pno in pages:
        name = f"p{pno:04d}.png"
        target = out_dir / name
        if not target.exists():
            pix = doc[pno - 1].get_pixmap(dpi=dpi)
            pix.save(target)
        names.append(name)
    return names


def run_ocr(dir_path: Path, files: list[str]) -> dict:
    """调 PowerShell 做 OCR，返回 {文件名: 文本}。"""
    job = Path(tempfile.gettempdir()) / "wa_ocr_job.json"
    job.write_text(json.dumps({"dir": str(dir_path), "files": files},
                              ensure_ascii=False), "utf-8")
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PS1)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out = r.stdout or ""
    if "NO_OCR_ENGINE" in out:
        raise RuntimeError(
            "系统没有可用的 OCR 引擎。Windows 设置 → 时间和语言 → 语言 → "
            "添加「中文(简体)」的「光学字符识别」可选功能。")
    res_file = dir_path / "_ocr_result.json"
    if not res_file.exists():
        raise RuntimeError(f"OCR 未产出结果。stdout={out[:300]} stderr={(r.stderr or '')[:300]}")
    data = json.loads(res_file.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        data = [data]
    return {x["file"]: (x.get("text") or "") if x.get("ok") else "" for x in data}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="手册目录或单个 PDF")
    ap.add_argument("--pack", required=True, help="车型包目录，如 packs/suzuki-sx4-2010")
    ap.add_argument("--doc-id", required=True, help="文档标识，如 sx4-2007-manual")
    ap.add_argument("--dpi", type=int, default=200, help="渲染精度，200 够 OCR，300 更准但更慢")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 页（试跑用）")
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--batch", type=int, default=BATCH)
    args = ap.parse_args()

    pack = Path(args.pack)
    if not pack.is_absolute():
        pack = ROOT / pack
    out_dir = pack / "data" / "ocr"
    out_dir.mkdir(parents=True, exist_ok=True)
    index_file = out_dir / f"{args.doc_id}.json"

    index = {}
    if index_file.exists() and args.skip_existing:
        index = json.loads(index_file.read_text("utf-8"))
        print(f"已有索引 {len(index)} 页，续跑")

    src = Path(args.src)
    # 递归扫描：手册分册常在子目录里（01-发动机/、05-变速器/ …）
    pdfs = sorted(src.rglob("*.pdf")) if src.is_dir() else [src]
    if not pdfs:
        print(f"[错误] {src} 下没有 PDF")
        sys.exit(1)
    print(f"发现 {len(pdfs)} 个 PDF")

    tmp = Path(tempfile.gettempdir()) / "wa_ocr_pages"
    tmp.mkdir(exist_ok=True)

    total_pages = 0
    done_pages = 0
    t0 = time.time()
    rows = []

    for pdf in pdfs:
        doc = pymupdf.open(pdf)
        n = doc.page_count
        total_pages += n
        pages = list(range(1, n + 1))
        # 页 id：<doc_id>::<相对路径去扩展>::p<页码>，带子目录避免同名文件冲突
        if src.is_dir():
            stem = str(pdf.relative_to(src).with_suffix("")).replace("\\", "/")
        else:
            stem = pdf.stem
        todo = []
        for pno in pages:
            pid = f"{args.doc_id}::{stem}::p{pno}"
            if args.skip_existing and pid in index:
                continue
            todo.append(pno)
            if args.limit and (done_pages + len(todo)) >= args.limit:
                break
        if args.limit:
            done_pages += len(todo)
            if done_pages >= args.limit:
                todo = todo[: args.limit - (done_pages - len(todo))]
        if not todo:
            doc.close()
            if args.limit and done_pages >= args.limit:
                break
            continue

        print(f"  {pdf.name}  共 {n} 页，待处理 {len(todo)} 页")
        for i in range(0, len(todo), args.batch):
            chunk = todo[i:i + args.batch]
            files = render_batch(doc, chunk, tmp, args.dpi)
            texts = run_ocr(tmp, files)
            for pno, fn in zip(chunk, files):
                raw = texts.get(fn, "")
                txt = clean_text(raw)
                pid = f"{args.doc_id}::{stem}::p{pno}"
                index[pid] = {"doc": args.doc_id, "file": pdf.name, "page": pno,
                              "text": txt, "chars": len(txt)}
                rows.append((pid, len(txt)))
            # 清掉这一批的图，别把硬盘撑爆
            for fn in files:
                try:
                    (tmp / fn).unlink()
                except OSError:
                    pass
            done = sum(1 for _ in rows)
            elapsed = time.time() - t0
            print(f"    批次 {i // args.batch + 1}: 已完成 {done} 页，"
                  f"{elapsed:.0f}s，均 {elapsed / max(done, 1):.2f}s/页")
            index_file.write_text(json.dumps(index, ensure_ascii=False, indent=0),
                                  "utf-8")
        doc.close()

    index_file.write_text(json.dumps(index, ensure_ascii=False, indent=0), "utf-8")
    empty = [pid for pid, n in rows if n < 10]
    print()
    print(f"完成：{len(index)} 页索引 -> {index_file}")
    print(f"总耗时 {time.time() - t0:.0f}s")
    if empty:
        print(f"⚠ {len(empty)} 页几乎没识别出字（可能是纯图页）：{empty[:5]}")
    print()
    print("下一步：")
    print(f"  python builder/ocrindex.py --pack {args.pack}   # 建全文检索索引")


if __name__ == "__main__":
    main()
