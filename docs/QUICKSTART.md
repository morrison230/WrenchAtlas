# 快速上手

> 给第一次拿到这个项目的人。5 分钟弄清它是干什么的、能跑成什么样。

## 它是什么

把**原厂维修手册的扫描件**变成可查、可点、可推理的知识库。

一份数据，两个用法：网页给人看，Skill 给 AI 用。

**关键前提**：这个仓库**不含任何手册内容**（PDF、页面图、OCR 文本都没有，版权原因）。
所以它和普通项目不一样——克隆下来能跑，但打开是空的。**内容得你自己生成。**

---

## 分两种情况

### 情况 A：我只想看看它长什么样（没有手册）

```bash
pip install -r requirements.txt
```

双击 `start.bat`，浏览器打开 `http://127.0.0.1:3000`。

你会看到：
- **诊断流图页能正常用** —— 36 个系统的拓扑数据在仓库里，可以点、可以看针脚、可以看诊断提示
- **手册页面是空的** —— 因为页图不在仓库里
- **全文搜索是空的** —— 因为没有 OCR 索引

控制台会明确告诉你缺什么、怎么补。

> 想理解数据结构，直接打开 `packs/suzuki-sx4-2010/data/circuits/starting.json`，
> 对着 `docs/DATA-FORMAT.md` 看，比读文档快。

### 情况 B：我有自己的手册，想建成我的车

依次跑这四条：

```bash
# 1. 建空包（把 brand-model-year 换成你的车）
python builder/new_pack.py --id toyota-corolla-2014 --make Toyota --model Corolla --year 2014 --engine 1ZR

# 2. 填两个文件
#    packs/toyota-corolla-2014/pack.json        —— 车型信息
#    packs/toyota-corolla-2014/system-map.json   —— 手册目录名 → 标准系统标识

# 3. 手册 PDF → 增强页图 → 页面索引
python builder/enhance.py --src "你的手册目录" --out "packs/toyota-corolla-2014/pages"
python builder/index.py   --pack packs/toyota-corolla-2014 --doc-id corolla-2014

# 4. 自检（必须绿了再往下）
python builder/validate.py --pack packs/toyota-corolla-2014
```

做到这里，网站就能翻页了。接下来是**最花时间的一步**：一个系统一个系统地录
`data/circuits/*.json`。格式照抄 `suzuki-sx4-2010` 的。

需要全文搜索的话，再加两步：

```bash
python builder/ocr.py         --src "你的手册目录" --pack packs/toyota-corolla-2014 --doc-id corolla-2014
python builder/ocr_sources.py --src "你的手册目录" --pack packs/toyota-corolla-2014 --doc-id corolla-2014
python builder/ocr_quality.py --pack packs/toyota-corolla-2014
```

完整八步见 [`MULTI-VEHICLE.md`](MULTI-VEHICLE.md)。

---

## 三个最容易踩的坑

**① 目录名必须等于 `pack.json` 里的 `id`**

否则服务按 id 注册，用目录名找不到包。

**② 页图命名有硬性规则**

`enhance.py` 输出的是 `<子目录>__<文件名>__p<页码>.png`。
如果你用自己的方式生成页图，必须遵守这个格式，否则 `index.py` 一行都索引不到。

**③ 判读不确定就标 `read-uncertain`**

数据格式里 `confidence` 有三档。**宁可标不确定，也不要为了图好看标成 `read-clear`**。
这个项目最核心的原则是「让人知道哪一条是读出来的、哪一条是量过的」。

---

## 术语对照

| 你会看到 | 意思 |
|---|---|
| 车型包 / pack | 一款车的全部数据，一个目录 |
| 系统 / system | 起动系统、充电系统这种功能块，标识见 `SYSTEM-TAXONOMY.md` |
| 流图 / circuit | 一个系统的结构化拓扑：环节 + 连线 + 诊断提示 |
| `read-clear` | 图清楚，读得确定 |
| `read-uncertain` | 图模糊或有歧义，存疑 |
| `vehicle-confirmed` | 实车量过（当前项目里**一条都没有**） |

---

## 还需要看什么

| 想知道 | 去哪 |
|---|---|
| 数据字段怎么填 | [`DATA-FORMAT.md`](DATA-FORMAT.md) |
| 系统该叫什么标识 | [`SYSTEM-TAXONOMY.md`](SYSTEM-TAXONOMY.md) |
| 加一款车的全流程 | [`MULTI-VEHICLE.md`](MULTI-VEHICLE.md) |
| OCR 怎么用、有什么限制 | [`FULLTEXT-OCR.md`](FULLTEXT-OCR.md) |
| 为什么这么设计 | [`DESIGN.md`](DESIGN.md) |
