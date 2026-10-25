# -*- coding: utf-8 -*-
"""
WrenchAtlas · 跨系统连接器反查

扫描所有 circuits 的 pins 字段，建立「连接器/压接点 → 出现在哪些系统」的反向索引。
这东西的价值：一个连接器/搭铁点出问题时，能立刻知道它同时影响哪几个系统。

用法: python builder/connectors.py [--pack ...] [--min 2]
"""
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

# 连接器号形态：字母1~2个 + 数字，允许中间有空格（如 "E382 G334 14" 里的两段）
TOKEN = re.compile(r"\b([A-Z]{1,3})[\s-]?(\d{1,4})\b")


def norm(a: str, b: str) -> str:
    return f"{a}{b}"


def scan(pack: Path):
    """返回 {连接器: [ {system, node, pins} ... ]}"""
    idx = defaultdict(list)
    cdir = pack / "data" / "circuits"
    for f in sorted(cdir.glob("*.json")):
        c = json.loads(f.read_text("utf-8"))
        sysname, sysid = c.get("name", f.stem), c.get("system", f.stem)
        for n in c.get("nodes", []):
            for pin in n.get("pins", []) or []:
                seen = set()
                for m in TOKEN.finditer(str(pin).upper()):
                    key = norm(m.group(1), m.group(2))
                    if key in seen:
                        continue
                    seen.add(key)
                    idx[key].append({
                        "system": sysid, "system_name": sysname,
                        "node": n.get("label", ""), "pin": pin,
                    })
    return idx


def _pick_pack(arg):
    """--pack 支持 id / 路径；不传则选 circuits 最多的车型包。"""
    root = Path(__file__).resolve().parent.parent / "packs"
    if arg:
        p = Path(arg)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent.parent / arg
        return p
    cands = []
    if root.exists():
        for d in sorted(root.iterdir()):
            if d.is_dir() and not d.name.startswith("_") and (d / "pack.json").exists():
                c = d / "data" / "circuits"
                cands.append((len(list(c.glob("*.json"))) if c.exists() else 0, d))
    if not cands:
        return root / "suzuki-sx4-2010"
    return max(cands, key=lambda x: x[0])[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default=None, help="车型包 id 或路径，省略则选数据最多的")
    ap.add_argument("--min", type=int, default=2, help="只显示出现在 >=N 个系统的")
    args = ap.parse_args()

    pack = _pick_pack(args.pack)

    idx = scan(pack)
    # 统计跨系统数
    rows = []
    for k, hits in idx.items():
        systems = {h["system"] for h in hits}
        rows.append((len(systems), len(hits), k, systems, hits))
    rows.sort(reverse=True)

    cross = [r for r in rows if r[0] >= args.min]
    print(f"共扫描到 {len(rows)} 个连接器/针脚标识")
    print(f"其中出现在 >= {args.min} 个系统的有 {len(cross)} 个\n")
    print("跨系统连接器（按涉及系统数排序）:")
    for nsys, nhit, key, systems, hits in cross[:30]:
        names = sorted({h['system_name'] for h in hits})
        print(f"  {key:<10} {nsys} 个系统 · {nhit} 处")
        print(f"     {' / '.join(names)}")

    print("\n出现最多的单个连接器（按引用次数）:")
    by_hits = sorted(rows, key=lambda r: -r[1])[:12]
    for nsys, nhit, key, systems, hits in by_hits:
        print(f"  {key:<10} 引用 {nhit} 次 · 覆盖 {nsys} 个系统")


if __name__ == "__main__":
    main()
