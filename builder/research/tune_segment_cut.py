# -*- coding: utf-8 -*-
"""切线段实验：用距离变换找交叉点，在交叉处分断，得到「单根线」级别的段"""
import numpy as np
import cv2
from PIL import Image
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

PAGES = ROOT / "packs" / "suzuki-sx4-2010" / "pages"
OUT = ROOT / "_trace_test"
NAME = "06-系统电路图__10-挡风玻璃雨刮器和清洗器__p001.png"

arr = np.array(Image.open(PAGES / NAME).convert("RGB"))
gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
mask = (gray < 200).astype(np.uint8)
mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))

dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
vals = dist[mask > 0]
print("距变统计: 中位=%.2f  p90=%.2f  p99=%.2f  max=%.2f" % (
    np.median(vals), np.percentile(vals, 90), np.percentile(vals, 99), vals.max()))

for th in (1.6, 1.9, 2.2, 2.6):
    joints = ((dist > th).astype(np.uint8))
    jr = int((joints > 0).sum())
    jd = cv2.dilate(joints, np.ones((9, 9), np.uint8))
    seg = (mask & (~jd.astype(bool))).astype(np.uint8)
    seg = cv2.morphologyEx(seg, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    n, lab = cv2.connectedComponents(seg, connectivity=8)
    areas = np.bincount(lab.ravel())[1:]
    areas = areas[areas > 20]
    print(f"  th={th}: 交叉点像素={jr:>6}  段数={len(areas):>5}  "
          f"最大段={int(areas.max()) if len(areas) else 0:>7} 中位段={int(np.median(areas)) if len(areas) else 0}")

# 取 th=1.9 渲染可视化：每段一色
th = 1.9
joints = (dist > th).astype(np.uint8)
jd = cv2.dilate(joints, np.ones((9, 9), np.uint8))
seg = (mask & (~jd.astype(bool))).astype(np.uint8)
seg = cv2.morphologyEx(seg, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
n, lab = cv2.connectedComponents(seg, connectivity=8)
areas = np.bincount(lab.ravel())
rng = np.random.default_rng(7)
colors = rng.integers(40, 255, size=(n, 3)).astype(np.uint8)
canvas = np.full(arr.shape, 255, np.uint8)
for i in range(1, n):
    if areas[i] > 20:
        canvas[lab == i] = colors[i]
canvas[jd > 0] = (210, 210, 210)

def save(img, name, w=1400):
    im = Image.fromarray(img)
    im = im.resize((w, int(im.height * w / im.width)), Image.LANCZOS)
    im.save(OUT / name)
    print("  ->", name)

save(canvas, "SEG_切割结果.png")
