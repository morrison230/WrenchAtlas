# -*- coding: utf-8 -*-
"""调参：找让连通域大小合理的预处理组合"""
import numpy as np
import cv2
from PIL import Image
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

P = ROOT / "packs" / "suzuki-sx4-2010" / "pages"
FILES = [
    "06-系统电路图__10-挡风玻璃雨刮器和清洗器__p001.png",
    "06-系统电路图__05-发动机和空调控制系统__p001.png",
]

def stats(labels, n):
    areas = np.bincount(labels.ravel())[1:]
    areas = areas[areas > 0]
    return {
        "n": len(areas),
        "max": int(areas.max()) if len(areas) else 0,
        "p90": int(np.percentile(areas, 90)) if len(areas) else 0,
        "med": int(np.median(areas)) if len(areas) else 0,
        "huge": int((areas > 20000).sum()),
    }

for fn in FILES:
    arr = np.array(Image.open(P / fn).convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    print(f"\n=== {fn[:34]} {arr.shape[1]}x{arr.shape[0]}")

    for th in (150, 180, 200):
        for close_k in (0, 3):
            mask = (gray < th).astype(np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
            if close_k:
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((close_k, close_k), np.uint8))
            n, lab = cv2.connectedComponents(mask, connectivity=8)
            st = stats(lab, n)
            tag = f"th{th} close{close_k}"
            print(f"  {tag:<14} 域数={st['n']:>6} 最大={st['max']:>7} p90={st['p90']:>6} "
                  f"中位={st['med']:>4} 超大块={st['huge']:>4}")

    # 分色：彩色与黑色分开
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
    sat = hsv[..., 1]
    colored = (sat > 55) & (gray < 230)
    dark = (sat <= 55) & (gray < 200)
    for name, m in (("彩色", colored), ("黑色", dark)):
        mm = m.astype(np.uint8)
        mm = cv2.morphologyEx(mm, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        mm = cv2.morphologyEx(mm, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        n, lab = cv2.connectedComponents(mm, connectivity=8)
        st = stats(lab, n)
        print(f"  {'分色-'+name:<14} 域数={st['n']:>6} 最大={st['max']:>7} p90={st['p90']:>6} "
              f"中位={st['med']:>4} 超大块={st['huge']:>4}")
