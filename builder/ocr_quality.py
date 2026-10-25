# -*- coding: utf-8 -*-
"""
OCR 质量分级：给每页打可信度分，而不是试图改正错字。

为什么不做全自动纠错（实测过的结论）：
  · 错字率极低（全库可疑字中位 3%）
  · "低频词 → 编辑距离1的高频词" 会产生大量误判：
    708 页样本里跑出 21571 条候选，绝大多数是跨词窗口而不是错字
  · 收益 0.3%，风险是"改错了看不出来" —— 和生成式 AI 修图是同一类风险
  · 数字类错误（0.15 → 0.75）AI 根本无从判断，绝不能自动改

**所以改成标注质量，让人自己决定要不要信这页的文字。**

分级依据：该页汉字中"全库罕见字"的占比。
  · 全库字频 < 5 的字 → 罕见字。正常行文里不会出现，多半是识别错。
  · 这是相对指标，不依赖外部字表，也不需要人工词典。

产出：
  · 每页写回 quality 字段（0-100，越高越好）+ grade（good/fair/poor）
  · 输出低质量页清单，供"换源"清单使用

用法:
  python builder/ocr_quality.py --pack packs/<车型>
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

CJK = r"\u4e00-\u9fff"
RE_CJK = re.compile(f"[{CJK}]")
ROOT = Path(__file__).resolve().parent.parent

RARE_MAX = 5       # 全库出现次数 <= 此值视为罕见字
GOOD = 0.08        # 可疑字 <8% → good
FAIR = 0.20        # <20% → fair，超过 → poor
MIN_CHARS = 50     # 汉字少于此数，视为图页，单独标记


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default=None)
    args = ap.parse_args()

    packs = [d for d in (ROOT / "packs").iterdir()
             if d.is_dir() and not d.name.startswith("_") and (d / "pack.json").exists()]
    if args.pack:
        pack = Path(args.pack)
        if not pack.is_absolute():
            pack = ROOT / args.pack
    elif packs:
        pack = max(packs, key=lambda d: len(list((d / "data" / "ocr").glob("*.json")))
                   if (d / "data" / "ocr").exists() else 0)
    else:
        print("[错误] 没有车型包")
        sys.exit(1)

    ocr_dir = pack / "data" / "ocr"
    files = sorted(f for f in ocr_dir.glob("*.json") if not f.name.startswith("_"))
    if not files:
        print(f"[错误] {ocr_dir} 下没有 OCR 索引，先跑 builder/ocr.py")
        sys.exit(1)

    # 1) 全库字频
    print(f"读取 {len(files)} 个索引文件…")
    data = {}
    for f in files:
        try:
            data[f.name] = json.loads(f.read_text("utf-8"))
        except Exception as e:
            print(f"  [跳过] {f.name}: {e}")
    allc = Counter()
    for idx in data.values():
        for v in idx.values():
            allc.update(c for c in v.get("text", "") if RE_CJK.match(c))
    rare = {c for c, n in allc.items() if n <= RARE_MAX}
    print(f"全库汉字 {len(allc)} 种，罕见字（<={RARE_MAX}次）{len(rare)} 种")
    print()

    # 2) 逐页打分
    stat = Counter()
    poor_list = []
    for fname, idx in data.items():
        for pid, v in idx.items():
            t = v.get("text", "") or ""
            cjk = [c for c in t if RE_CJK.match(c)]
            n = len(cjk)
            if n == 0:
                v["quality"], v["grade"] = 0, "empty"
                stat["empty"] += 1
                continue
            bad = sum(1 for c in cjk if c in rare)
            ratio = bad / n
            q = max(0, min(100, round((1 - ratio * 4) * 100)))
            if ratio < GOOD:
                grade = "good"
            elif ratio < FAIR:
                grade = "fair"
            else:
                grade = "poor"
            if n < MIN_CHARS and grade == "good":
                grade = "sparse"       # 字太少，多半是图页
            v["quality"], v["grade"], v["bad_ratio"] = q, grade, round(ratio, 3)
            stat[grade] += 1
            if grade in ("poor", "fair"):
                poor_list.append((round(ratio, 3), fname, v.get("file"), v.get("page"), n))

    # 3) 写回
    for fname, idx in data.items():
        (ocr_dir / fname).write_text(
            json.dumps(idx, ensure_ascii=False, indent=0), "utf-8")

    total = sum(stat.values())
    print("分级结果：")
    for g in ("good", "sparse", "fair", "poor", "empty"):
        if stat.get(g):
            print(f"  {g:<7} {stat[g]:>5} 页  ({stat[g]/total*100:.1f}%)")

    # 4) 低质量清单
    poor_list.sort(reverse=True)
    out = ocr_dir / "_quality_report.json"
    out.write_text(json.dumps({
        "generated_from": [f.name for f in files],
        "stats": dict(stat),
        "total": total,
        "poor": [{"bad_ratio": r, "index": f, "file": fl, "page": p, "chars": n}
                 for r, f, fl, p, n in poor_list[:500]],
    }, ensure_ascii=False, indent=1), "utf-8")
    print(f"\n低质量清单（{len(poor_list)} 页，前 500 写入）-> {out}")
    if poor_list:
        print("最差的几页：")
        for r, f, fl, p, n in poor_list[:8]:
            print(f"  {r*100:4.0f}%  {fl} p{p}  {n} 字")


if __name__ == "__main__":
    main()
