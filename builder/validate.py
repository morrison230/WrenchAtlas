# -*- coding: utf-8 -*-
"""
WrenchAtlas · 数据包自检

检查所有 circuits/*.json 的结构合法性、引用完整性、置信度分布，
并核对 source_page 能否在 pages.json 中解析到。

用法: python builder/validate.py --pack packs/suzuki-sx4-2010
退出码: 0 = 全部通过, 1 = 有错误
"""
import argparse
import json
import sys
from pathlib import Path

VALID_ROLE = {"source", "fuse", "sensor", "switch", "relay",
              "ecu", "splice", "load", "ground"}
VALID_CONF = {"read-clear", "read-uncertain", "vehicle-confirmed"}
REQUIRED = ["id", "system", "name", "type", "confidence", "source_page",
            "nodes", "edges"]


def calc_layout_rows(nodes):
    """复刻前端分层逻辑，检查是否有某层挤爆。"""
    LAYER = {"source": 0, "fuse": 1, "sensor": 1,
             "switch": 2, "relay": 2, "ecu": 2, "splice": 2,
             "load": 3, "ground": 4}
    g = {}
    for n in nodes:
        g.setdefault(LAYER.get(n.get("role"), 2), []).append(n)
    return {L: len(v) for L, v in sorted(g.items())}


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
    args = ap.parse_args()

    pack = _pick_pack(args.pack)

    errors, warns = [], []
    cdir = pack / "data" / "circuits"

    pages = {}
    pf = pack / "data" / "pages.json"
    if pf.exists():
        for p in json.loads(pf.read_text("utf-8")).get("pages", []):
            pages[p["id"]] = p
    else:
        errors.append("缺少 data/pages.json")

    files = sorted(cdir.glob("*.json")) if cdir.exists() else []
    if not files:
        errors.append("data/circuits/ 下没有数据文件")

    print(f"数据包: {pack}")
    print(f"页面索引: {len(pages)} 页")
    print(f"流图数据: {len(files)} 个\n")

    tot_nodes = tot_edges = tot_hints = tot_unc = 0

    for f in files:
        tag = f.stem
        try:
            c = json.loads(f.read_text("utf-8"))
        except Exception as e:
            errors.append(f"[{tag}] JSON 解析失败: {e}")
            continue

        for k in REQUIRED:
            if k not in c:
                errors.append(f"[{tag}] 缺少必填字段 {k}")
        if c.get("type") != "signal-flow":
            warns.append(f"[{tag}] type 不是 signal-flow（当前为 {c.get('type')}）")
        if c.get("confidence") not in VALID_CONF:
            errors.append(f"[{tag}] confidence 取值非法: {c.get('confidence')}")

        sp = str(c.get("source_page", "")).split(",")[0].strip()
        if sp and sp not in pages:
            errors.append(f"[{tag}] source_page 无法在 pages.json 解析: {sp}")

        ids = set()
        for n in c.get("nodes", []):
            nid = n.get("id")
            if not nid:
                errors.append(f"[{tag}] 有节点缺少 id")
                continue
            if nid in ids:
                errors.append(f"[{tag}] 节点 id 重复: {nid}")
            ids.add(nid)
            if n.get("role") not in VALID_ROLE:
                errors.append(f"[{tag}] 节点 {nid} 的 role 非法: {n.get('role')}")
            if n.get("confidence") and n["confidence"] not in VALID_CONF:
                errors.append(f"[{tag}] 节点 {nid} 的 confidence 非法")
            if not n.get("label"):
                warns.append(f"[{tag}] 节点 {nid} 缺 label")
            if not n.get("detail"):
                warns.append(f"[{tag}] 节点 {nid} 缺 detail（说明文字）")

        for e in c.get("edges", []):
            for side in ("from", "to"):
                if e.get(side) not in ids:
                    errors.append(f"[{tag}] 边引用了不存在的节点: {e.get(side)}")

        rows = calc_layout_rows(c.get("nodes", []))
        # 前端同层超过 4 个会自动换行，所以只有超过 8 个（需换 3 行）才值得提醒
        crowded = [L for L, n in rows.items() if n > 8]
        if crowded:
            warns.append(f"[{tag}] 同层节点超过 8 个（层 {crowded}），手机端可能需要多行")

        nn = len(c.get("nodes", []))
        ne = len(c.get("edges", []))
        nh = len(c.get("diagnosis_hint", []))
        nu = sum(1 for n in c.get("nodes", []) if n.get("confidence") == "read-uncertain")
        if not nh:
            warns.append(f"[{tag}] 没有 diagnosis_hint —— 这是数据最有价值的部分，建议补")
        if nu and not any(n.get("uncertain") for n in c.get("nodes", [])):
            warns.append(f"[{tag}] 有 {nu} 个存疑节点但没写 uncertain 说明")

        tot_nodes += nn; tot_edges += ne; tot_hints += nh; tot_unc += nu
        print(f"  ✓ {c.get('name', tag):<20} {nn:>2} 环节 {ne:>2} 连接 "
              f"{nh:>2} 提示" + (f" · {nu} 存疑" if nu else ""))

    print(f"\n合计: {tot_nodes} 环节 / {tot_edges} 连接 / {tot_hints} 条诊断提示 / {tot_unc} 处存疑")

    if warns:
        print(f"\n⚠ 警告 {len(warns)} 条:")
        for w in warns:
            print("   ", w)
    if errors:
        print(f"\n✗ 错误 {len(errors)} 条:")
        for e in errors:
            print("   ", e)
        sys.exit(1)
    print("\n✓ 全部通过")


if __name__ == "__main__":
    main()
