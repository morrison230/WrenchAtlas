# 车型包模板

这是手动复制用的骨架。**更推荐用脚手架**，它会按你的车型把 pack.json 填好：

```bash
cd <项目根目录>
python \
  builder/new_pack.py --id toyota-corolla-2014 --make Toyota --model Corolla --year 2014 --engine 1ZR
```

## 手动复制的话

```bash
cp -r packs/_template packs/你的车型id
```

然后把 `pack.json` 的 `id` 改掉（必须等于目录名），再按下面的顺序填。

## 填表顺序

| 顺序 | 文件 | 填什么 |
|---|---|---|
| 1 | `pack.json` | 厂牌、车型、年份、发动机。`manuals` 里登记你手上的手册 |
| 2 | `system-map.json` | 手册里的中文标题 → 标准系统标识（见 `docs/SYSTEM-TAXONOMY.md`） |
| 3 | 跑 `builder/enhance.py` | 手册 PDF → 增强页图，放进 `pages/` |
| 4 | 跑 `builder/index.py` | 页图 → `data/pages.json` + `thumbs/` |
| 5 | `data/circuits/*.json` | 一个系统一个文件，照 `suzuki-sx4-2010` 的结构写 |
| 6 | `data/symptoms.json` | 症状问诊树 |
| 7 | `builder/validate.py` | 自检 |

`data/pages.json` 和 `data/verified.json` 不用手填——前者由 `index.py` 生成，后者由网站点击产生。

## 三条不能破的规矩

1. **`pages/` 和 `thumbs/` 永远不进 git**（原厂图有版权，`.gitignore` 已拦）
2. **判读不确定就标 `read-uncertain`**，不许为了让图好看改成 `read-clear`
3. **`source_page` 必须真实存在**于 `data/pages.json`，否则网站找不到来源页

## 完整说明

每个文件里都有 TODO 注释。深入说明见：

- `docs/DATA-FORMAT.md` — 字段定义
- `docs/SYSTEM-TAXONOMY.md` — 系统标识词表
- `docs/MULTI-VEHICLE.md` — 加车型的完整流程与踩坑记录
