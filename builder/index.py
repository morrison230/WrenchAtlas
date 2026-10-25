# -*- coding: utf-8 -*-
"""
WrenchAtlas · 页面索引与缩略图生成（L0 配套）
扫描 pages/ 下的增强图，产出 data/pages.json + thumbs/ 缩略图。

用法: python index.py --pack packs/suzuki-sx4-2010 --doc-id sx4-2010
"""
import argparse
import json
import re
from pathlib import Path

from PIL import Image

KIND_BY_PREFIX = {
    "01-": "overview",
    "02-": "power",
    "03-": "ground",
    "04-": "harness",
    "05-": "connector",
    "06-": "wiring",
}

# 兜底词表：车型包没带 system-map.json 时用这套（SX4 2010 手册的标题）
# 换车型请在 packs/<id>/system-map.json 里覆盖，不要改这段
SYSTEM_SLUG = {
    "起动系统": "starting", "充电系统": "charging", "点火系统": "ignition",
    "冷却系统": "cooling", "发动机和空调控制系统": "engine-ecm",
    "AT控制系统": "at-control", "发动机电子芯片防盗系统": "immobilizer",
    "车体电器控制系统": "body-electrical", "CAN线路图": "can",
    "挡风玻璃雨刮器和清洗器": "wiper-front", "后雨刮器和清洗器": "wiper-rear",
    "后除霜器线路图": "defogger", "电动后视镜": "mirror", "电动门锁": "door-lock",
    "喇叭线路": "horn", "无钥匙启动系统": "keyless", "组合仪表": "meter",
    "前照灯系统": "headlamp", "示宽、车尾和牌照灯系统": "tail-lamp",
    "前雾灯": "fog-lamp-front", "照明灯": "illumination",
    "室内照明系统": "interior-lamp", "转向信号灯和危险警告灯": "turn-signal",
    "制动灯": "stop-lamp", "倒车灯": "backup-lamp", "后雾灯": "fog-lamp-rear",
    "加热和暖风": "heater", "自动AC系统": "ac-auto", "安全气囊": "airbag",
    "防抱死制动系统": "abs", "电动助力转向系统": "eps", "音响系统": "audio",
    "多信息显示器": "mid", "天窗线路图": "sunroof", "导航音响系统": "navi",
    "连接器": "connector-list",
    "概述": "overview",
    "电源供电": "power-supply",
    "接地点": "ground-points",
    "线束布置": "harness-layout",
    "连接器布置图": "connector-layout",
}


def load_system_map(pack: Path):
    """读车型包自带的词表。返回 (topics, kinds)。

    车型包里有 system-map.json 就用它，没有则回落到内置兜底表。
    这样换车型只改数据包，builder 不用动。
    """
    f = pack / "system-map.json"
    if f.exists():
        try:
            d = json.loads(f.read_text("utf-8"))
            topics = d.get("topics") or {}
            kinds = d.get("kinds") or KIND_BY_PREFIX
            if topics:
                print(f"词表: {f}（{len(topics)} 个系统标题 / {len(kinds)} 个类型前缀）")
            else:
                print(f"词表: {f} 的 topics 为空 → 回落内置兜底表"
                      f"（{len(SYSTEM_SLUG)} 个标题）")
                topics = SYSTEM_SLUG
            return topics, kinds
        except Exception as e:
            print(f"[警告] {f} 解析失败，改用内置兜底表: {e}")
    else:
        print(f"词表: 内置兜底表（建议在 {f} 提供车型专属词表）")
    return SYSTEM_SLUG, KIND_BY_PREFIX


def parse_stem(stem: str):
    """06-系统电路图__05-发动机和空调控制系统__p001 -> (子目录, 主题, 页码)"""
    m = re.match(r"^(?P<body>.+)__p(?P<page>\d+)$", stem)
    if not m:
        return None
    body, page = m.group("body"), int(m.group("page"))
    parts = body.split("__")
    if len(parts) == 1:
        return ("", parts[0], page)
    return (parts[0], parts[1], page)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True)
    ap.add_argument("--doc-id", required=True)
    ap.add_argument("--thumb-width", type=int, default=420)
    args = ap.parse_args()

    pack = Path(args.pack)
    pages_dir = pack / "pages"
    thumbs_dir = pack / "thumbs"
    data_dir = pack / "data"
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    slug_by_topic, kind_by_prefix = load_system_map(pack)

    records = []
    for img_path in sorted(pages_dir.glob("*.png")):
        parsed = parse_stem(img_path.stem)
        if not parsed:
            continue
        subdir, topic, page_no = parsed

        with Image.open(img_path) as im:
            w, h = im.size
            thumb = thumbs_dir / (img_path.stem + ".jpg")
            if not thumb.exists():
                ratio = args.thumb_width / w
                im.convert("RGB").resize(
                    (args.thumb_width, max(1, int(h * ratio))), Image.LANCZOS
                ).save(thumb, quality=82, optimize=True)

        prefix = (subdir or topic)[:3]
        kind = kind_by_prefix.get(prefix, "wiring" if subdir else "manual")
        topic_clean = re.sub(r"^\d+-\s*", "", topic).strip()
        system = slug_by_topic.get(topic_clean) or slug_by_topic.get(
            re.sub(r"^\d+-\s*", "", subdir).strip(), "")
        short = (subdir + "-" if subdir else "") + topic

        records.append({
            "id": f"{args.doc_id}::{short}::p{page_no}",
            "doc_id": args.doc_id,
            "file": (f"{subdir}/{topic}.pdf" if subdir else f"{topic}.pdf"),
            "page": page_no,
            "kind": kind,
            "system": system,
            "title": topic_clean or topic,
            "image": f"pages/{img_path.name}",
            "thumb": f"thumbs/{img_path.stem}.jpg",
            "size": [w, h],
        })

    out = data_dir / "pages.json"
    out.write_text(
        json.dumps({"schema_version": "0.1", "pages": records},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    kinds = {}
    for r in records:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    print(f"索引 {len(records)} 页 -> {out}")
    print("类型分布:", kinds)
    print("未映射系统:", sorted({r['title'] for r in records if not r['system']}))


if __name__ == "__main__":
    main()
