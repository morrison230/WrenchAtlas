# -*- coding: utf-8 -*-
"""
WrenchAtlas · 页面渲染与增强（L0）
把扫描页渲染成图，并做保真型增强：白场拉伸 + 对比度 + 锐化。
只调像素表现，不改任何内容（不增删线条、不改文字）。

用法:
  python enhance.py --src <目录> --out <目录> [--dpi 300] [--limit 5]
                    [--white 45] [--contrast 1.6] [--unsharp 150]
"""
import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageEnhance, ImageFilter


def white_point(arr: np.ndarray, floor: int) -> np.ndarray:
    """把 floor 以上的亮度线性拉到纯白，去掉扫描底灰。"""
    if floor <= 0:
        return arr
    a = arr.astype(np.float32)
    a = (a - floor) * (255.0 / (255.0 - floor))
    return np.clip(a, 0, 255).astype(np.uint8)


def enhance(img: Image.Image, white: int, contrast: float, unsharp: int) -> Image.Image:
    arr = np.asarray(img)
    arr = white_point(arr, white)
    out = Image.fromarray(arr)
    if contrast and contrast != 1.0:
        out = ImageEnhance.Contrast(out).enhance(contrast)
    if unsharp:
        out = out.filter(ImageFilter.UnsharpMask(radius=2.0, percent=unsharp, threshold=3))
    return out


def render_page(doc, pno: int, dpi: int) -> Image.Image:
    pix = doc[pno].get_pixmap(dpi=dpi)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="手册目录或单个 PDF")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--white", type=int, default=45, help="白场阈值 0-200")
    ap.add_argument("--contrast", type=float, default=1.6)
    ap.add_argument("--unsharp", type=int, default=150)
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 页，0=全部")
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--suffix", default="", help="输出文件名后缀")
    args = ap.parse_args()

    src = Path(args.src)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    if src.is_file():
        pdfs = [src]
    else:
        pdfs = sorted(src.rglob("*.pdf"))

    total = 0
    done = 0
    t0 = time.time()
    for pdf in pdfs:
        doc = pymupdf.open(str(pdf))
        rel = pdf.relative_to(src) if not src.is_file() else Path(pdf.name)
        stem = str(rel.with_suffix("")).replace("\\", "__").replace("/", "__")
        for pno in range(doc.page_count):
            if args.limit and total >= args.limit:
                doc.close()
                break
            dst = outdir / f"{stem}__p{pno + 1:03d}{args.suffix}.png"
            total += 1
            if args.skip_existing and dst.exists():
                continue
            img = render_page(doc, pno, args.dpi)
            img = enhance(img, args.white, args.contrast, args.unsharp)
            img.save(dst, optimize=True)
            done += 1
            if done % 10 == 0 or done <= 3:
                el = time.time() - t0
                print(f"  [{done}/{total}] {stem} p{pno+1}  {img.size[0]}x{img.size[1]}  "
                      f"{el:.1f}s  ~{el/max(done,1):.2f}s/页", flush=True)
        else:
            doc.close()
            continue
        break
    doc.close() if not doc.is_closed else None
    print(f"\n完成 {done} 页 / 扫描 {total} 页，耗时 {time.time()-t0:.1f}s -> {outdir}")


if __name__ == "__main__":
    main()
