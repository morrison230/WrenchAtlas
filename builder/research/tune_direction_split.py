# -*- coding: utf-8 -*-
"""方向分离实验：水平线 / 垂直线各自成段"""
import numpy as np
import cv2
from PIL import Image
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

PAGES = ROOT / "packs" / "suzuki-sx4-2010" / "pages"
OUT = ROOT / "_trace_test"
CASES = [
    ("06-系统电路图__10-挡风玻璃雨刮器和清洗器__p001.png", "雨刮"),
    ("06-系统电路图__05-发动机和空调控制系统__p001.png", "发动机"),
]

for NAME, tag in CASES:
    arr = np.array(Image.open(PAGES / NAME).convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    mask = (gray < 200).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    print(f"\n=== {tag} {mask.shape[1]}x{mask.shape[0]}  笔画像素={int(mask.sum())}")

    for L in (25, 40, 60):
        h = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                             cv2.getStructuringElement(cv2.MORPH_RECT, (L, 1)))
        v = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                             cv2.getStructuringElement(cv2.MORPH_RECT, (1, L)))
        for nm, m in (("水平", h), ("垂直", v)):
            n, lab = cv2.connectedComponents(m, connectivity=8)
            areas = np.bincount(lab.ravel())[1:]
            areas = areas[areas > 30]
            print(f"  L={L:<3} {nm}: 段数={len(areas):>5} 最大={int(areas.max()) if len(areas) else 0:>7} "
                  f"p90={int(np.percentile(areas,90)) if len(areas) else 0:>6} "
                  f"中位={int(np.median(areas)) if len(areas) else 0:>4}")

    # 用 L=40 渲染
    L = 40
    h = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                         cv2.getStructuringElement(cv2.MORPH_RECT, (L, 1)))
    v = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                         cv2.getStructuringElement(cv2.MORPH_RECT, (1, L)))
    canvas = np.full(arr.shape, 255, np.uint8)
    canvas[h > 0] = (200, 60, 60)
    canvas[v > 0] = (60, 100, 200)
    both = (h > 0) & (v > 0)
    canvas[both] = (40, 150, 80)
    im = Image.fromarray(canvas)
    w = 1300
    im.resize((w, int(im.height * w / im.width)), Image.LANCZOS).save(OUT / f"DIR_{tag}.png")
    print(f"  -> DIR_{tag}.png (红=水平 蓝=垂直 绿=交叉)")
