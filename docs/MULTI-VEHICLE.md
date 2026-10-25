# 加一款新车：完整流程

> 版本 v0.1 · 2026-10-25
>
> 这份文档是为"第二款车"写的。第一款车（SX4）是摸出来的，第二款车应该按流程走。

## 一句话流程

```
建包 → 填元信息 → 填词表 → 转页图 → 建索引 → 录拓扑 → 自检 → 起服务
```

## 第 0 步：确认你合法持有手册

**这是前提，不是免责套话。** 没有合法来源的手册，后面每一步都是在堆积风险。

工具本身不含任何手册内容，`pages/` 已被 gitignore —— 但这些设计保护不了"你从哪弄来的资料"。

## 第 1 步：建包

```bash
cd <项目根目录>
PY=python          # 确保 python 在 PATH；不在则写绝对路径

"$PY" builder/new_pack.py \
  --id toyota-corolla-2014 \
  --make Toyota --model Corolla --year 2014 --engine 1ZR
```

**`--id` 的命名规矩**：`厂牌-车型-年份`，全小写连字符。这个 id 会成为目录名、API 参数、localStorage 的键，改名成本很高。

生成后检查：`packs/toyota-corolla-2014/` 下应该有 pack.json、system-map.json、README.md、data/、pages/、thumbs/。

## 第 2 步：填 `pack.json`

必填：`make` / `model` / `year` / `engine`。
建议填：`make_cn` / `model_cn`（中文名，界面上好看）。

**`variants` 是关键字段**。同一款车不同配置的电路可能完全不同，必须显式建模：

```json
"variants": [
  { "id": "AT", "label": "自动挡", "note": "档位传感器串在起动回路" },
  { "id": "MT", "label": "手动挡" },
  { "id": "CN4", "label": "国四排放", "note": "ECM 引脚用 Ⓑ 组" },
  { "id": "CN3", "label": "国三排放", "note": "ECM 引脚用 Ⓐ 组" }
]
```

拓扑里用 `"applies_to": "AT"` 挂到变体上。前端会标"仅自动挡"。

> **为什么不用自由文本**：SX4 那版用了 `engine_coverage: "图上标注 ③M16A ④M18A"` 这种写法，
> 人能看懂，程序看不出结构。同时有 4 个配置时会彻底失控。第二款车开始请用 `variants`。

## 第 3 步：填 `system-map.json`

把手册里的中文标题对到标准标识：

```json
"topics": {
  "起动系统": "starting",
  "充电系统": "charging",
  "点火系统": "ignition"
}
```

**先查 `docs/SYSTEM-TAXONOMY.md`**，能对上就别自创。同一功能在不同厂牌叫法不同（"充电系"/"充电系统"/"发电机"），但标识统一成 `charging` 以后，跨车型才能对照。

`kinds` 是手册的章节前缀映射（`01-` → `overview` 等），手册结构不同就改这里。

**没填 `topics` 会怎样**：自动回落内置兜底表（SX4 的 41 条），很可能对不上你的手册 —— 页面索引里 `system` 字段会是空字符串。这时网站能翻页，但流图找不到来源页。所以这步不能跳。

## 第 4 步：转页图

```bash
"$PY" builder/enhance.py --src "你的手册目录" --out "packs/toyota-corolla-2014/pages"
```

- 支持目录或单个 PDF，会递归
- 默认 300dpi + 白场拉伸 + 锐化，参数可调（`--white` / `--contrast` / `--unsharp`）
- 约 3.6 秒/页。100 页约 6 分钟，可以后台跑
- `--skip-existing` 断点续跑

**文件名规则很重要**：`enhance.py` 输出的是 `<子目录>__<文件名>__p<页码>.png` 这种格式，`index.py` 靠这个解析。

如果你用别的方式生成页图，必须遵守同样的命名，否则索引建不起来。

## 第 5 步：建索引

```bash
"$PY" builder/index.py --pack "packs/toyota-corolla-2014" --doc-id toyota-corolla-2014
```

输出会告诉你三件事：
- 索引了多少页
- 类型分布（wiring / connector / harness / …）
- **未映射的系统** —— 这里不为空就说明 `system-map.json` 没填全

## 第 6 步：录拓扑（主要工作量）

一个系统一个文件，放 `data/circuits/<system>.json`。

**不要一上来铺全量。** 先挑一个最简单的系统（通常是后雾灯或喇叭，一条线走完）跑通全链路：
网站能看到 → 能点 → 能跳原图 → 能出报告。确认没问题再往下做。

结构照 `packs/suzuki-sx4-2010/data/circuits/` 抄。核心是 `nodes`（环节）+ `edges`（连线）：
节点按 `role` 分层排版（source/fuse/switch/relay/sensor/ecu/splice/load/ground），
**role 写对，前端自动排版，不用管坐标**。

### 读图的实用技巧（SX4 那一版踩出来的）

| 技巧 | 说明 |
|---|---|
| **网格扫描** | 别猜坐标裁图。先摸清内容区边界（可能有大片空白），再切成固定大小的块，一块一屏 |
| **沿线追踪** | 找不到元件时，从已知的线开始追：`E229.4 白线 → 往下 → 找到 C141` |
| **先读真值表** | 开关档位表是电路的说明书，读到它等于拿到了半个诊断逻辑 |
| **一处不确定就标出来** | `confidence: "read-uncertain"` + `uncertain: "具体哪里不确定"` |

## 第 7 步：自检

```bash
"$PY" builder/validate.py --pack "packs/toyota-corolla-2014"
```

它会查：字段必填、role/confidence 合法、节点 id 唯一、边引用完整、`source_page` 能否解析、
同层节点是否过多、有存疑标记却没写说明。

**不为空就不要继续加系统**，先修干净。脏数据会传染。

## 第 8 步：起服务看

```bash
"$PY" web/server.py --port 3000
```

启动信息会列出所有车型包。浏览器打开后：
- 只有一个包 → 不显示切换器
- 多个包 → 顶部出现下拉，切换后所有页面保持在该车型

默认包按"circuits 数量最多"选，也可以用 `--pack <id>` 指定，或在 pack.json 里写 `"default": true`。

## 平台化验证记录

2026-10-25 做过一次双包验证（建假包 `demo-car-2020`，2 页图 + 1 个系统）：

| 验证项 | 结果 |
|---|---|
| 服务同时加载 2 个包 | ✅ 启动信息正确列出 |
| 各自的 circuits / pages 隔离 | ✅ 默认包 23 系统，demo 包 1 系统，互不串 |
| `?pack=` 切包 | ✅ `source_label`、`source_image` 都指向本包的页 |
| 图片按包取 | ✅ `/media/pages/xxx?pack=<id>` 各自返回 |
| 报告按包生成 | ✅ `/report?sys=...&pack=...` |
| 默认包选择 | ✅ 修了按字母序的 bug，改成按数据完整度 |
| 坏 pack id | ✅ 404 |
| `_template` 被误当车型 | ✅ 修了，`_` 开头目录不参与运行时 |

验证完删除该包（里面是从 SX4 复制的页图，不能留）。

## 已知的坑

| 坑 | 现象 | 解法 |
|---|---|---|
| 目录名 ≠ pack.json 的 id | 服务按 pack.json 的 id 注册，`?pack=目录名` 找不到 | 两者保持一致 |
| `system-map.json` 的 topics 为空 | 索引里 system 字段全空 | 补上映射，或至少确认兜底表能对上你的手册标题 |
| 页图命名不符 `__p<页码>` 规则 | `index.py` 跳过所有文件，索引 0 页 | 遵守命名规则 |
| `source_page` 写错 | 流图点"看原厂图"跳 404 | 从 `data/pages.json` 里复制真实 id |
| 两个包用了同一个 `system` 标识 | 正常，标识本来就是跨车型共享的 | 不要为了区分加车型前缀，那会破坏跨车型对照 |
