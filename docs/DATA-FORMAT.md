# 数据格式规范

> 版本 v0.1 · M0 阶段草案，M6 前会随实现补全

一个车型 = `packs/` 下一个目录 = 一个 **Vehicle Pack**。引擎只认这份格式，不认车型。

---

## 包的最小结构

```
packs/<pack-id>/
├── pack.json            车型元数据（必填）
├── colors.json          线色代号表（可选，缺省用通用表）
├── data/
│   ├── pages.json       页面锚点索引（必填）
│   ├── specs.json       规格库（可选）
│   ├── circuits/        电路拓扑，一回路一文件
│   └── diag/            诊断，一主题一文件
└── pages/               渲染页图（gitignore，本地生成）
```

`pack-id` 命名：`<品牌>-<车型>-<年款>`，小写连字符。例：`suzuki-sx4-2010`。

---

## pack.json

```json
{
  "schema_version": "0.1",
  "id": "suzuki-sx4-2010",
  "make": "Suzuki",
  "make_cn": "长安铃木",
  "model": "SX4",
  "year": 2010,
  "engine": "M18A",
  "engine_displacement": "1.8",
  "transmission": "MT",
  "market": "CN",
  "manuals": [
    {
      "doc_id": "sx4-2010",
      "title": "2010 长安天语 SX4 电路图",
      "role": "wiring",
      "path": "raw/sx4-2010/",
      "pages": 114
    }
  ],
  "built_at": "2026-10-24",
  "notes": "电路图来源：2010 长安版；正文手册来源：2007 版，规格引用需按 M18A 核对"
}
```

**`engine` 与 `notes` 不是装饰**。规格与诊断数据要能回答"这条适用于哪个发动机"，这是 1.6/1.8 混用风险的唯一防线。

---

## pages.json

页面锚点。所有溯源都指向这里。

```json
{
  "pages": [
    {
      "id": "sx4-2010::wiring-10::p1",
      "doc_id": "sx4-2010",
      "file": "06-系统电路图/10-挡风玻璃雨刮器和清洗器.pdf",
      "page": 1,
      "kind": "wiring",
      "system": "wiper",
      "title": "挡风玻璃雨刮器和清洗器线路图",
      "image": "pages/wiring-10-p1.png",
      "size": [4560, 3613],
      "dpi": 300
    }
  ]
}
```

- `id` 格式固定：`<doc_id>::<短名>::p<页码>`，全项目唯一
- `kind`：`manual` | `wiring` | `connector` | `harness` | `ground`
- `size` 是渲染像素尺寸，交互层的坐标基准

---

## circuits/*.json

```json
{
  "id": "wiper-main",
  "system": "wiper",
  "name": "前雨刮主回路",
  "source_page": "sx4-2010::wiring-10::p1",
  "confidence": "read-clear",
  "nodes": [
    { "id": "E323.9", "connector": "E323", "pin": "9", "role": "source",
      "bbox": [1520, 240, 1680, 300], "note": "" }
  ],
  "wires": [
    { "from": "E323.9", "to": "E64.3", "color": "L", "gauge": "0.85" }
  ],
  "grounds": ["G334"]
}
```

规则：

1. **节点 id 必须是 `<连接器>.<针脚>`**，全包唯一。这是连线的前提
2. `bbox` 为 `[x1, y1, x2, y2]` 像素坐标，基于 `source_page` 的 `size`
3. `verified` 已废弃，改用 `confidence`（见下节）
4. `role` 取值见 5.3

---

## circuits 的两种类型

### 类型 A · `pin-level`（针脚级）

逐针脚记录谁连谁，用于精确追线。上面那段示例即是。**当前项目未使用**——因为像素级拆线在扫描件上不可靠（详见 DESIGN.md 第 12 节）。

### 类型 B · `signal-flow`（信号流图）★ 当前使用

把整个系统概括成 5–10 个功能环节，服务于"判断哪一环断了"。这是目前全部数据的类型。

```json
{
  "id": "ignition",
  "system": "ignition",
  "name": "点火系统",
  "type": "signal-flow",
  "confidence": "read-clear",
  "confidence_note": "判读说明",
  "source_page": "sx4-2010::06-系统电路图-03-点火系统::p1",
  "variant_warning": "ECM 引脚有非欧4/欧4 两套，选错会量错线",
  "topology_type": "wasted-spark",
  "nodes": [
    {
      "id": "coil1",
      "label": "点火线圈 #1 · C101",
      "sub": "管 1 缸 + 4 缸",
      "role": "load",
      "pins": ["C101.1", "C101.3", "C101.2"],
      "confidence": "read-clear",
      "detail": "1=控制（绿线→ECM）、3=电源、2=搭铁。次级供两缸。",
      "uncertain": "可选：具体哪里不确定"
    }
  ],
  "edges": [
    {"from": "ecm", "to": "coil1", "color": "绿",
     "via": "C01 6(非欧4) / C01 53(欧4) → C101.1", "note": "点火控制"}
  ],
  "diagnosis_hint": ["1&4 缸同时失火 → 判定 C101 线圈坏"],
  "injection_map": {"P0301": {"cylinder": 1, "ecm_pin": "C01 1"}}
}
```

**必填字段**：`id` `system` `name` `type` `confidence` `source_page` `nodes` `edges`
**推荐字段**：`diagnosis_hint`（诊断提示，这是全部数据里最有价值的部分）、`variant_warning`、`topology_type`、`injection_map`

---

## 5.3 role 枚举（**布局契约，改动会影响前端排版**）

前端流图页面按 `role` 自动分层，顺序为：

| 层 | role | 含义 |
|---|---|---|
| 0 | `source` | 电源（蓄电池） |
| 1 | `fuse` `sensor` | 保险丝、传感器 |
| 2 | `switch` `relay` `ecu` `splice` | 开关、继电器、ECU、压接点 |
| 3 | `load` | 负载（电机、线圈、喷油器） |
| 4 | `ground` | 搭铁 |

**新增系统只要 role 写对，无需改任何代码即可自动排版。** 若某系统布局不理想，优先检查 role 是否贴切，而不是改前端。

---

## 5.4 confidence 三级（替代已废弃的 verified 布尔值）

| 值 | 含义 | 前端表现 |
|---|---|---|
| `read-clear` | 原图清晰可读，判读确定 | 正常 |
| `read-uncertain` | 有判读不确定之处 | **节点黄边 + 圆点**，详情里显示 `uncertain` 原文 |
| `vehicle-confirmed` | 实车核对过 | 绿色徽标 |

铁律：**没有实车核对过，绝对不许写 `vehicle-confirmed`。** 宁可全部标 `read-clear` 或 `read-uncertain`。

详见 DESIGN.md 第 14 节。

---

## 5.5 变体（variants）—— 同一系统的多种配置

**这是最容易出人命的地方。** 同一页图上画两套系统（AT/MT、欧4/非欧4、仪表类型 I/II），
针脚号完全不同。选错引脚去量线，会把好件换掉。

### 定义

```json
{
  "system": "meter",
  "variants": [
    { "id": "type-1", "label": "类型 I", "note": "单色液晶，四表步进电机" },
    { "id": "type-2", "label": "类型 II", "note": "分段液晶 + 更多指示灯" }
  ],
  "variant_warning": "两种类型的仪表针脚不同。**必须先确认车上是哪一种**，否则引脚全对不上。",
  "nodes": [
    { "id": "fuse_mtr", "label": "JB MTR 10A", "role": "fuse" },
    { "id": "mcu_t1", "label": "仪表 MCU（类型 I）", "applies_to": "type-1" },
    { "id": "mcu_t2", "label": "仪表 MCU（类型 II）", "applies_to": "type-2" }
  ]
}
```

### 字段

| 字段 | 位置 | 说明 |
|---|---|---|
| `variants` | 文件根 | `[{id, label, note?}]`，id 用小写连字符 |
| `variant_warning` | 文件根 | 一句话说清「为什么必须选对」 |
| `applies_to` | 节点 / 边 | 取值必须是某个 variant 的 id |

**没有 `applies_to` 的节点 = 所有配置通用**（如保险丝、搭铁）。

### 展示规则（前端契约）

| 情况 | 表现 |
|---|---|
| 有 `variant_warning` | 页面顶部黄色警告条，**不可折叠** |
| 节点有 `applies_to` | 节点上加徽标「仅 类型 II」 |
| 边有 `applies_to` | 连线说明里加「仅 类型 II」 |
| 无 `variants` | 一切照旧，不显示任何变体 UI |

### 向后兼容

早期数据用过自由文本的 `applies_to`（如 `"AT"` / `"MT"`，没定义 `variants`）。
只要文件里没有 `variants` 字段，`applies_to` 就当纯标签显示，不做校验。

**新数据必须定义 `variants`**，`applies_to` 只能用列表里的 id。

### 校验规则（validate.py 已实现）

- 有 `variants` 时，每个 `applies_to` 必须命中某个 variant id，否则报错
- `variants` 的 id 不能重复
- `variant_warning` 存在但没有 `variants` → 警告（说明你标了差异却没定义差异在哪）

---

## verified.json

**核对标记。单独存一个文件，不改动 `circuits/*.json` 原始数据。**

```json
{
  "starting": {
    "ecm": {
      "at": "2026-10-25 00:31",
      "note": "量过 A-5 到搭铁，确认 ECM 控制线圈"
    }
  }
}
```

结构：`{ circuit_id: { node_id: { at, note } } }`。

### 它记录的是什么（重要）

**只记录「我在自己车上点过这个环节」，不等于「这个数据被验证过」。**

这两件事必须分清，否则会出现自相矛盾：文件里有 16 条记录、文档却写"实车核对 0 条"——
那种记录其实是点着玩的测试点击，说明不了任何问题。

| | 点击记录（本文件） | 实车验证结论（若要共享） |
|---|---|---|
| 内容 | 谁在什么时候勾了一下 | 什么车、什么配置、用什么方法、量到什么值、结论 |
| 可信度 | 低——只代表"我看过这个环节" | 高——可复现、可质疑 |
| 归宿 | 本地 `verified.json`，**不入库** | 写进故障说明或独立验证报告 |
| 例 | `{"at":"...","note":""}` | `M18A / AT / 万用表 A-5 对搭铁 12.4V / 线圈通` |

### 规则

1. 有记录 = 有人点过核对方框；**没有记录 = 仅原图判读**
2. **这个文件不入库**（已在 `.gitignore` 里）。别人拿到你的勾没有任何意义——
   他不知道是谁、在哪台车、用什么方法核的
3. `note` 留空的记录**没有验证价值**，只当书签用
4. 前端与 Skill 都会读取它：已核对的节点显示绿勾

### 想真正记录实车验证，怎么做

不要只勾框。在 `note` 里写全三件事：

```json
"note": "M18A+AT，2026-10-25，万用表量 A-5 对搭铁 12.4V，钥匙 ON 时线圈通 → 确认 ECM 控制该继电器"
```

**配置 + 方法 + 结果**，缺一条这条记录就不可复现。项目文档里"实车核对 0/272"
统计的正是**这种带完整三要素的记录**，不是勾选框的数量。

---

## diag/*.json

```json
{
  "id": "sym-wiper-no-action",
  "type": "symptom",
  "system": "wiper",
  "title": "雨刮完全不动作",
  "steps": [
    {
      "no": 1,
      "action": "检查保险丝 F1",
      "check": "导通",
      "yes": 2,
      "no": null,
      "ref": "sx4-2010::wiring-10::p1"
    }
  ],
  "related_circuits": ["wiper-main"],
  "source_page": "sx4-2007::manual-09::p55"
}
```

规则：

1. `type`：`dtc` | `symptom` | `procedure`
2. 每个 `step` 的 `ref` **必填**——无溯源的步骤不允许入库
3. `yes` / `no` 指向下一步 `no`，`null` = 流程终点
4. 手册里没有的诊断路径，宁可空着，不许推测填充

---

## specs.json

```json
{
  "specs": [
    {
      "id": "spark-plug-gap",
      "item": "火花塞间隙",
      "value": "1.0-1.1",
      "unit": "mm",
      "engine": "M18A",
      "source_engine": "M16A",
      "engine_mismatch": true,
      "condition": "冷态",
      "source_page": "sx4-2007::manual-01a::p42"
    }
  ]
}
```

规则：

1. `engine` **必填**：该规格适用哪台发动机（本车 M18A）
2. `source_engine` **必填**：数值抄自哪本手册对应的发动机（2007 版正文 = M16A）
3. `engine_mismatch` 由校验器自动计算：`engine !== source_engine` 时为 `true`
4. `value` 只填手册原文值，**不允许换算、不允许推算**
5. `engine_mismatch: true` 的条目，前端必须显示醒目警示，不可省略

**这一条是安全底线**：M18A 与 M16A 大量零件通用，但扭矩与间隙未必相同。抄错的扭矩能报废发动机，所以宁可每条都标红。

---

## 新增一款车

1. `cp -r packs/_template packs/<pack-id>`
2. 填 `pack.json`（车型、发动机、手册清单）
3. 用 `builder` 跑手册 → 生成 `data/pages.json` 与 `pages/*.png`
4. 逐系统录 `circuits/` 与 `diag/`（先手工，M2 后走半自动 + 校验）
5. 跑 `core` 的校验：节点 id 唯一性、`ref` 可解析、`bbox` 在页内
6. 引擎加载新包，**不改一行代码**——这是验收标准

---

## 校验清单（core 必须实现）

- [ ] 所有 `source_page` / `ref` 能在 `pages.json` 里解析到
- [ ] 节点 id 全包唯一，格式合规
- [ ] `wires` 两端的节点都存在
- [ ] `bbox` 落在该页 `size` 范围内
- [ ] `specs` 与 `diag` 的 `engine` 与包声明一致或显式列出例外
- [ ] `confidence` 三级分布统计，`read-uncertain` 逐条列出供人工复核
