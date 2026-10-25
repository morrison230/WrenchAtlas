# -*- coding: utf-8 -*-
"""
建立 OCR 索引 → 原始 PDF 的映射表。

OCR 只能告诉你"这页在第几页"，要让人点开看原页，得知道 PDF 在哪。
这张表把文件名映射到 PDF 绝对路径（本机配置，不含手册内容）。

用法:
  python builder/ocr_sources.py --src <手册目录> --pack packs/<车型> --doc-id <doc_id>
"""
import argparse
import json
import sys
from pathlib import Path

# Windows 控制台默认 GBK，输出 ✓ 之类的符号会直接抛 UnicodeEncodeError。
# 这里强制把 stdout/stderr 转成 UTF-8，让新人在任何终端都能跑。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError, ValueError):
    pass

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="手册目录或单个 PDF（与 ocr.py 的 --src 一致）")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--doc-id", required=True)
    args = ap.parse_args()

    src = Path(args.src)
    if not src.is_absolute():
        src = src.resolve()
    pack = Path(args.pack)
    if not pack.is_absolute():
        pack = ROOT / pack

    if src.is_dir():
        pdfs = sorted(src.rglob("*.pdf"))
    elif src.exists():
        pdfs = [src]
    else:
        print(f"[错误] 找不到 {src}")
        sys.exit(1)

    out_dir = pack / "data" / "ocr"
    out_dir.mkdir(parents=True, exist_ok=True)
    f = out_dir / "_sources.json"

    data = {}
    if f.exists():
        try:
            data = json.loads(f.read_text("utf-8"))
        except Exception:
            data = {}

    entry = {}
    dup = []
    for pdf in pdfs:
        rel = str(pdf.relative_to(src)).replace("\\", "/") if src.is_dir() else pdf.name
        key = pdf.name
        if key in entry and entry[key] != str(pdf):
            dup.append(key)
            key = rel          # 同名文件改用相对路径做键
        entry[key] = str(pdf)
        entry[rel] = str(pdf)

    data[args.doc_id] = {"root": str(src), "files": entry}
    f.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")

    print(f"已登记 {len(entry)} 个路径键（{len(pdfs)} 个 PDF）-> {f}")
    if dup:
        print(f"⚠ 有同名文件，已改用相对路径做键：{sorted(set(dup))}")


if __name__ == "__main__":
    main()
