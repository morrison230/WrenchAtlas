# -*- coding: utf-8 -*-
"""自动定位电路图上的元件框：找闭合矩形轮廓，输出 bbox 供逐块细读"""
import sys
import numpy as np
import cv2
from pathlib import Path
from PIL import Image

d = Path(r"G:\Projects\WrenchAtlas\packs\suzuki-sx4-2010\pages")
name = sys.argv[1] if len(sys.argv) > 1 else "06-系统电路图__05-发动机和空调控制系统__p001.png"

arr = np.array(Image.open(d / name).convert("RGB"))
gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
H, W = gray.shape
print(f"图: {W}x{H}")

# 找线条
bin_ = (gray < 190).astype(np.uint8) * 255
# 闭运算把断续的框线接起来
bin_ = cv2.morphologyEx(bin_, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
cnts, _ = cv2.findContours(bin_, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

boxes = []
for c in cnts:
    x, y, w, h = cv2.boundingRect(c)
    area = w * h
    if area < 20000 or w < 60 or h < 40:
        continue
    ar = w / h
    if ar > 14 or ar < 1 / 14:      # 太细长的多半是线
        continue
    peri = cv2.arcLength(c, True)
    approx = cv2.approxPolyDP(c, 0.02 * peri, True)
    if not (4 <= len(approx) <= 8):  # 近似矩形/多边形
        continue
    boxes.append((area, x, y, w, h))

boxes.sort(reverse=True)
# 去重（大框套小框只留大的）
kept = []
for area, x, y, w, h in boxes:
    dup = False
    for _, kx, ky, kw, kh in kept:
        if x >= kx - 8 and y >= ky - 8 and x + w <= kx + kw + 8 and y + h <= ky + kh + 8:
            dup = True
            break
    if not dup:
        kept.append((area, x, y, w, h))

print(f"检出候选元件框 {len(kept)} 个（按面积降序，最多列 24）\n")
for i, (area, x, y, w, h) in enumerate(kept[:24], 1):
    print(f"  {i:>2}. bbox=({x:>4},{y:>4}) {w:>4}x{h:<4} 面积{area:>8}  裁图({x},{y})-({x+w},{y+h})")
