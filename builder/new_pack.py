# -*- coding: utf-8 -*-
"""
新建车型数据包脚手架。

这是平台化的入口：任何人拿到一份合法持有的维修手册，都能用这条命令
起一个空包，然后按 README 的步骤把数据填进去。

用法:
  python builder/new_pack.py --id toyota-corolla-2014 --make Toyota --model Corolla --year 2014 --engine 1ZR
  python builder/new_pack.py --id honda-civic-2016 --make Honda --model Civic --year 2016 --engine L15B7 --out D:/packs

生成的结构与 suzuki-sx4-2010 完全同构，网站和 Skill 不需要改任何代码就能读。
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")


def fail(msg: str) -> None:
    print(f"[错误] {msg}", file=sys.stderr)
    sys.exit(1)


PACK_JSON = """{{
  "schema_version": "0.1",
  "id": "{pack_id}",
  "make": "{make}",
  "make_cn": "",
  "model": "{model}",
  "model_cn": "",
  "year": {year},
  "engine": "{engine}",
  "engine_displacement": "",
  "transmission": "",
  "market": "CN",
  "manuals": [
    {{
      "doc_id": "{pack_id}",
      "title": "{make} {model} {year} 维修手册",
      "role": "wiring",
      "path": "raw/{pack_id}/",
      "pages": 0,
      "note": "TODO: 填入手册信息。role 取值 wiring（电路图）/ manual（维修手册正文）"
    }}
  ],
  "variants": [],
  "built_at": "",
  "notes": "TODO: 填这台车的特殊情况。规格若抄自不同排量的手册，务必在 specs 里标 source_engine。"
}}
"""

SYSTEM_MAP = """{
  "schema_version": "0.1",
  "description": "本车手册的文件夹/文件名中文标题 → 跨车型标准系统标识。换车型只改这份文件，builder 不用动。",
  "topics": {
  },
  "kinds": {
    "01-": "overview",
    "02-": "power",
    "03-": "ground",
    "04-": "harness",
    "05-": "connector",
    "06-": "wiring"
  }
}
"""

SYMPTOMS = """{
  "schema_version": "0.1",
  "description": "症状问诊树。通用骨架见 skill/symptoms-shared.json，这里只填本车专属的分支与 systems 引用。",
  "symptoms": []
}
"""

PAGES = """{
  "schema_version": "0.1",
  "pages": []
}
"""

SPECS = """{
  "schema_version": "0.1",
  "specs": []
}
"""

VERIFIED = "{}\n"

README = """# {pack_id}

{make} {model} {year}{engine_part} 的 WrenchAtlas 数据包。

## 这个包里有什么

```
{pack_id}/
├── pack.json          车型元信息（先填这个）
├── system-map.json    手册标题 → 标准系统标识（第二填这个）
├── README.md          本文件
├── data/
│   ├── pages.json     页面索引（由 builder/index.py 自动生成，不用手填）
│   ├── symptoms.json  症状问诊树
│   ├── verified.json  实车核对记录（网站点出来的，不用手填）
│   ├── specs.json     规格数据（扭矩、间隙、油液）
│   └── circuits/      各系统的拓扑 JSON（核心工作在这里）
├── pages/             增强后的页图（**不入 git**，见 .gitignore）
└── thumbs/            缩略图（**不入 git**）
```

## 三步把空包变成能用的包

### 1. 填 `pack.json`

至少填：`make` / `model` / `year` / `engine`。
`variants` 字段用来描述本车的配置差异（手动/自动、国四/国五、高低配），格式：

```json
"variants": [
  {{ "id": "AT", "label": "自动挡", "note": "档位传感器串在起动回路里" }},
  {{ "id": "MT", "label": "手动挡" }}
]
```

拓扑里的节点和连线可以用 `"applies_to": "AT"` 挂到某个变体上，前端会提示"仅自动挡"。

### 2. 填 `system-map.json`

把手册里的中文标题对到标准系统标识：

```json
"topics": {{
  "起动系统": "starting",
  "充电系统": "charging"
}}
```

**标准标识优先用 `docs/SYSTEM-TAXONOMY.md` 里的通用词表**，这样不同车型的数据能互相对照。
实在没有对应的，自己起一个（小写英文 + 连字符），但要记在包的 README 里。

### 3. 跑工具链

```bash
PY="C:/Users/Morrison/.workbuddy/binaries/python/envs/default/Scripts/python.exe"

# 手册 PDF → 增强页图（放进 pages/）
"$PY" builder/enhance.py --src "你的手册目录" --out "packs/{pack_id}/pages"

# 页图 → 页面索引 + 缩略图
"$PY" builder/index.py --pack "packs/{pack_id}" --doc-id {pack_id}

# 起服务看效果
"$PY" web/server.py --pack "packs/{pack_id}" --port 3000
```

页面能翻、能缩放了，再一个一个系统录 `data/circuits/*.json`。

## 电路拓扑怎么写

照抄 `packs/suzuki-sx4-2010/data/circuits/starting.json` 的结构。
最少要有：`id` / `system` / `name` / `source_page` / `confidence` / `nodes` / `edges`。

**三条硬规矩**：

1. `system` 必须与 `system-map.json` 里的标识一致（否则网站找不到来源页）
2. `source_page` 必须是 `pages.json` 里真实存在的页 id（格式 `<doc_id>::<文件名>::p<页码>`）
3. 判读不确定的节点，`confidence` 填 `read-uncertain` 并写 `uncertain` 说明——
   **不许为了让图好看而标成 read-clear**

写完跑一遍自检：

```bash
"$PY" builder/validate.py --pack "packs/{pack_id}"
```

## 版权红线

**这个包里不能有任何原厂手册内容**：不放 PDF，不放页图（`pages/` 已被 gitignore），
不放原文摘抄。只放你自己提炼的结构化事实——连接器编号、谁连谁、排查顺序。

`pages/` 里的图只在你本机用于对照，永远不进仓库、不外传。
"""


def main():
    ap = argparse.ArgumentParser(description="新建车型数据包")
    ap.add_argument("--id", required=True, help="车型包标识，小写字母数字连字符，如 toyota-corolla-2014")
    ap.add_argument("--make", required=True, help="厂牌英文，如 Toyota")
    ap.add_argument("--model", required=True, help="车型英文，如 Corolla")
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--engine", default="", help="发动机代号，如 1ZR / M18A")
    ap.add_argument("--out", default=str(ROOT / "packs"), help="输出到哪个目录（默认 packs/）")
    ap.add_argument("--force", action="store_true", help="目标已存在时覆盖")
    args = ap.parse_args()

    if not ID_RE.match(args.id):
        fail("--id 只能用小写字母、数字、连字符，2–61 字符。例：toyota-corolla-2014")

    out_root = Path(args.out)
    pack = out_root / args.id
    if pack.exists() and not args.force:
        fail(f"{pack} 已存在。换一个 id，或加 --force 覆盖（会保留已有的 data/circuits）")

    # 目录骨架
    for d in ["data/circuits", "data/diag", "pages", "thumbs"]:
        (pack / d).mkdir(parents=True, exist_ok=True)
    for d in ["data/circuits", "data/diag", "pages", "thumbs"]:
        gk = pack / d / ".gitkeep"
        if not gk.exists():
            gk.write_text("", "utf-8")

    engine_part = f" · {args.engine}" if args.engine else ""
    files = {
        "pack.json": PACK_JSON.format(pack_id=args.id, make=args.make,
                                      model=args.model, year=args.year,
                                      engine=args.engine),
        "system-map.json": SYSTEM_MAP,
        "README.md": README.format(pack_id=args.id, make=args.make,
                                   model=args.model, year=args.year,
                                   engine_part=engine_part),
        "data/pages.json": PAGES,
        "data/symptoms.json": SYMPTOMS,
        "data/specs.json": SPECS,
        "data/verified.json": VERIFIED,
    }
    for rel, content in files.items():
        (pack / rel).write_text(content, "utf-8")

    print(f"已创建车型包: {pack.resolve()}")
    print()
    for rel in files:
        print(f"  {rel}")
    print()
    print("下一步：")
    print(f"  1. 编辑 {pack}/pack.json 填车型信息")
    print(f"  2. 编辑 {pack}/system-map.json 填手册标题映射")
    print(f"  3. 跑 builder/enhance.py 把手册转成页图")
    print(f"  4. 跑 builder/index.py 建页面索引")
    print(f"  5. 一个系统一个系统录 data/circuits/*.json")
    print()
    print(f"  起服务预览: python web/server.py --pack {pack} --port 3000")


if __name__ == "__main__":
    main()
