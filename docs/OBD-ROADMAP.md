# OBD 接入功能线（独立于症状/电路校核推进）

> 状态与阶段划分记录于 2026-10-25。实车能力基线见
> 《OBD-实车验证交接给阿沃.md》（2026-10-25，BFN「车卫士旗舰版」BLE 盒子 + Android 采集工具实测）。
> 本功能线**独立推进**，不阻塞症状扩覆盖与只读 MCP；但共用同一条纪律：
> 每个判断标注来源（`实车 OBD 观测` / `手册电路` / `推断`），三者不许混用。

## 硬边界（每阶段都必须守住）

1. **标准 OBD ≠ 全车模块诊断**。Mode 01/02/03/07/09/0A 只覆盖发动机/排放层。
   ABS、SRS/气囊、BCM、四驱等厂家专用模块**不在范围内**，任何 UI 与文案
   不得把它们显示为「已扫描」「正常」。
2. **只读**。不提供 Mode 04 清码、Mode 08 执行器测试、编程、任意 AT/OBD 命令。
3. **NO DATA / 超时 / 不支持保持原样**，绝不解释成 0 或故障。
4. **多 ECU 必须按 CAN ID 分桶再 ISO-TP 重组**，不许把 7E8/7E9 交织行直接拼接。
   重组不完整时只展示原始帧（宁缺毋错）。
5. **VIN 等车辆身份信息不入库**：报告落盘 `packs/*/data/obd/`，已 gitignore。

## 阶段 0：实车能力基线（2026-10-25 完成，老莫实车实测）

- BLE GATT 服务 `FFF0`：`FFF1` 收（Notify + CCCD）/ `FFF2` 发（Write）。
- `ATI` → `ELM327 v1.5`；`ATDP` → `AUTO, ISO 15765-4 (CAN 11/500)`；`ATRV` ≈ 14.1–14.2V。
- 功能寻址响应 ECU：`7E8`（完整发动机实时参数）+ `7E9`（部分标准查询）——
  前端按「多个响应 ECU」展示，不混成一条读数。
- Mode 03 = `4300`（无确认码）、07 = `4700`（无待定码）、0A = `NO DATA`；
  冻结帧 `020200` 全零（无可用冻结帧，不是「传感器为零」）；
  09 支持位图有响应，VIN/CVN/ECU 名 `NO DATA`，标定 ID 多帧响应。
- 完整 schema 与字段定义见 Android 工具源码 `ObdCodec.java` / `MainActivity.java`
  （`source.zip`，schema 名 `wrenchatlas.obd_probe.v1`）。

## 阶段 1：导入 Android 采集 JSON 报告（2026-10-25 完成）

**链路**：手机导出 JSON → WrenchAtlas「导入 OBD 报告」→ 按 ECU 解析展示。

组件：
- `builder/obd_import.py`：解析核心（CLI 可单独跑）
  - 帧拆分：兼容「头数据同行」「头单独一行」「关头纯 hex」三种 ELM 输出；
    处理命令回显；**不从无空格 hex 串里偷 CAN ID**（那里是 ISO-TP 的 PCI，
    曾因此把 0100 的响应拆成 8 个假 ECU——教训写在函数注释里防回归）
  - ISO-TP 重组：单帧/首帧/续帧；流控帧忽略；残缺多帧标记 raw_only
  - Mode 01 解码：转速/水温/燃油修正/MAF/节气门/电压/氧传感器等约 30 个
    标准 PID；未收录的 PID 保留原始帧不瞎解
  - Mode 03/07/0A DTC 解码（全零 = 无故障码，与「读取失败」区分）
  - Mode 09 标定 ID / VIN（交织多帧按 CAN ID 分桶重组后提取）
- `web/server.py`：`POST /api/obd/import`、`GET /api/obd/sessions`、
  `GET /api/obd/sessions/{sid}`、`GET /obd` 页面
- `web/static/obd.html`：能力边界声明置顶 → 导入（文件/粘贴/合成样本）→
  会话列表 → 会话详情（每 ECU 卡片：实时参数表 + 三类 DTC + 身份 +
  未解码原始报文可展开 + 无响应清单）；`#s=<sid>` 深链可分享
- 测试样本：`tests/fixtures/obd/obd-report-SYNTHETIC-sample.json`（**合成样本，
  明确标注非实车数据**；内容按交接文档事实构造，含 7E8/7E9 交织多帧
  0904 响应，专门验证 CAN ID 分桶）
- 页面演示数据：`web/static/obd-demo.json`（同上合成样本）

已知限制：
- 解码未覆盖全部标准 PID（未收录的显示原始帧，不丢数据）
- 冻结帧（Mode 02）只存原始帧，不解读
- Android 端 `readings` 每键覆盖（同名只留最后一次）；导入端以 `queries`
  原始响应为准逐帧重解，不受该限制影响

## 阶段 2：本地直连采集代理（待启动，未开工）

前提：阶段 1 数据链稳定（真机报告导入解析验证过几轮）。

- 形态：Android Companion（现有 OBD Probe 工具演进）
- 链路：`BFN 盒子 → BLE GATT(FFF2/FFF1) → Android Companion → JSON/局域网 API → WrenchAtlas`
- 只读白名单沿用：`ATI` `ATDP` `ATRV` + Mode 01、02 第 0 帧、03、07、09 指定身份、0A
- 对多 ECU 先按 CAN ID 分桶再重组（与导入端同一套规则）
- 未验证事项（来自交接文档）：厂家专用诊断、跨车型参数集、Suzuki 专用
  服务能否取 VIN、长时间动态工况记录

## 与其他功能线的关系

- 问诊页/报告引用 OBD 数值时，必须标注来源 `实车 OBD 观测`，与
  `手册电路`、`推断` 并列，不做自动推断混合。
- 只读 MCP（独立待办）后续可直接复用 `builder/obd_import.py` 的解析结果。
