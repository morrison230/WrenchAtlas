# -*- coding: utf-8 -*-
"""WrenchAtlas OBD 报告导入解析器。

输入：Android 采集工具导出的 wrenchatlas.obd_probe.v1 JSON（只读标准 OBD）。
输出：按 ECU（CAN ID）分桶解析后的结构化会话。

三条铁律（来自 2026-10-25 实车交接，违反任何一条都算 bug）：
1. 多 ECU 响应必须先按 CAN ID 分桶、再作 ISO-TP 重组——
   绝不把 7E8 / 7E9 的交织行直接拼接（Android 端 payload() 取首个命中，
   两颗 ECU 会互相污染；导入端必须做得更对）。
2. NO DATA / 超时 / 不支持一律保持原样——不许解释成 0 或故障。
3. 标准 OBD 只覆盖发动机/排放层，绝不表述为「全车模块扫描」；
   ABS/SRS/BCM/四驱等厂家专用模块不在范围内。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SCHEMA = "wrenchatlas.obd_probe.v1"

# ---------- 基础工具 ----------

_CAN3 = re.compile(r"^[0-9A-F]{3}$")          # 11 位 CAN ID
_CAN8 = re.compile(r"^[0-9A-F]{8}$")          # 29 位 CAN ID
_HEX = re.compile(r"^[0-9A-F]+$")

_NOT_DATA = ("NODATA", "NO DATA")
_ERR_MARKS = ("UNABLE", "CAN ERROR", "BUS INIT", "STOPPED", "FB ERROR", "?")
# 注意：SEARCHING... 不算错误——ELM 首次响应前常先输出它，后面跟着真数据。


def _classify(response: str) -> str:
    """把一条原始响应归类：ok / no_data / error。NO DATA 永远不当 0。"""
    up = (response or "").upper()
    if any(m in up for m in _NOT_DATA):
        return "no_data"
    if any(m in up for m in _ERR_MARKS):
        return "error"
    return "ok"


def _split_frames(response: str, request: str = ""):
    """从原始文本拆出 (can_id|None, [bytes]) 帧。

    ELM 三种形态都要支持：
      7E8 06 41 00 BE 3E B8 11    （头与数据同行，空格分隔）
      7E8\r064100BE3EB811         （头单独一行，数据是无空格 hex 串）
      064100BE3EB811              （AT H0/ATE0 关头：数据行自带 ISO-TP PCI）
    处理坑位：
    · 命令回显（ATE1 默认开）：紧凑后与 request 相同的行丢弃
    · 【重要】不要从无空格 hex 串里「偷」前 3 位当 CAN ID——
      那里是 ISO-TP 的 PCI 字节（0x06=单帧长6）。曾因此把 0100 的响应
      拆成 8 个假 ECU，教训写进注释防止回归。
    """
    req_compact = re.sub(r"[^0-9A-Fa-f]", "", request or "").upper()
    out = []
    pending_id = None
    for raw in re.split(r"[\r\n>]+", (response or "").upper()):
        s = raw.strip()
        if not s:
            continue
        tokens = s.split()
        if req_compact and "".join(tokens) == req_compact:
            pending_id = None
            continue                                    # 命令回显
        if all(_HEX.match(t) for t in tokens):
            if len(tokens) >= 2 and _CAN3.match(tokens[0]):
                pending_id = tokens[0]
                blob = "".join(tokens[1:])
            elif len(tokens) == 1 and _CAN3.match(tokens[0]):
                pending_id = tokens[0]                  # 头单独成行
                continue
            else:
                blob = "".join(tokens)
                cid, pending_id = pending_id, None
            if len(blob) % 2:
                continue
            data = [int(blob[i:i + 2], 16) for i in range(0, len(blob), 2)]
            out.append((cid, data))
        # 非 hex 行（SEARCHING... / NO DATA 等）不处理，也不清 pending_id
    return out


def _isotp_reassemble(frames):
    """同一 CAN ID 的帧流 → 完整报文列表。

    只处理标准 ISO-TP：单帧(0) / 首帧(1) / 续帧(2)。流控帧(3)来自
    测试端方向，忽略。无法安全重组时报文带 `raw_only` 标记，调用方
    只能展示原始帧（交接文档：宁缺毋错）。
    """
    msgs, pending = [], None
    for data in frames:
        if not data:
            continue
        pci = data[0] >> 4
        if pci == 0:
            ln = data[0] & 0x0F
            body = data[1:1 + ln] if 0 < ln <= 7 else data[1:]
            msgs.append(bytes(body))
            pending = None
        elif pci == 1:
            ln = ((data[0] & 0x0F) << 8) | data[1]
            pending = {"need": ln, "buf": bytes(data[2:]), "seq": 0}
            if len(pending["buf"]) >= ln:
                msgs.append(pending["buf"][:ln])
                pending = None
        elif pci == 2 and pending is not None:
            pending["seq"] += 1
            pending["buf"] += bytes(data[1:])
            if len(pending["buf"]) >= pending["need"]:
                msgs.append(pending["buf"][:pending["need"]])
                pending = None
        # pci == 3（流控）：忽略
    if pending is not None:                      # 残缺多帧：宁缺毋错
        msgs.append({"raw_only": True, "got": len(pending["buf"]),
                     "need": pending["need"]})
    return msgs


# ---------- Mode 01 PID 表 ----------

def _u16(a, b):
    return (a << 8) | b


def _pct_signed(x):
    return round((x - 128) * 100.0 / 128, 1)


# pid → (名称, 单位, 解码函数)。只收录与问诊相关的标准 PID；
# 未收录的 PID 仍显示原始帧（不丢数据、不瞎解）。
PID_TABLE = {
    0x04: ("计算负荷", "%", lambda d: round(d[0] * 100 / 255, 1)),
    0x05: ("冷却液温度", "℃", lambda d: d[0] - 40),
    0x06: ("短期燃油修正 B1", "%", lambda d: _pct_signed(d[0])),
    0x07: ("长期燃油修正 B1", "%", lambda d: _pct_signed(d[0])),
    0x08: ("短期燃油修正 B2", "%", lambda d: _pct_signed(d[0])),
    0x09: ("长期燃油修正 B2", "%", lambda d: _pct_signed(d[0])),
    0x0A: ("燃油压力", "kPa", lambda d: d[0] * 3),
    0x0B: ("进气歧管绝对压力", "kPa", lambda d: d[0]),
    0x0C: ("发动机转速", "rpm", lambda d: round(_u16(d[0], d[1]) / 4, 0)),
    0x0D: ("车速", "km/h", lambda d: d[0]),
    0x0E: ("点火提前角", "°", lambda d: round((d[0] - 128) / 2, 1)),
    0x0F: ("进气温度", "℃", lambda d: d[0] - 40),
    0x10: ("空气流量 MAF", "g/s", lambda d: round(_u16(d[0], d[1]) / 100, 2)),
    0x11: ("绝对节气门位置", "%", lambda d: round(d[0] * 100 / 255, 1)),
    0x1F: ("起动后运行时间", "s", lambda d: _u16(d[0], d[1])),
    0x21: ("MIL 后行驶距离", "km", lambda d: _u16(d[0], d[1])),
    0x2F: ("燃油液位", "%", lambda d: round(d[0] * 100 / 255, 1)),
    0x31: ("清码后行驶距离", "km", lambda d: _u16(d[0], d[1])),
    0x33: ("大气压力", "kPa", lambda d: d[0]),
    0x42: ("控制模块电压", "V", lambda d: round(_u16(d[0], d[1]) / 1000, 2)),
    0x43: ("绝对负荷", "%", lambda d: round(_u16(d[0], d[1]) * 100 / 255, 1)),
    0x45: ("相对节气门位置", "%", lambda d: round(d[0] * 100 / 255, 1)),
    0x46: ("环境温度", "℃", lambda d: d[0] - 40),
    0x4C: ("指令节气门位置", "%", lambda d: round(d[0] * 100 / 255, 1)),
    0x51: ("燃油类型", "", lambda d: {1: "汽油", 2: "甲醇", 3: "乙醇", 4: "柴油",
                                    5: "LPG", 6: "CNG", 8: "汽油+电动"}.get(d[0], f"码 {d[0]}")),
    0x5C: ("机油温度", "℃", lambda d: d[0] - 40),
    0x5E: ("燃油消耗率", "L/h", lambda d: round(_u16(d[0], d[1]) / 20, 2)),
}
# 氧传感器 0x14–0x1B：电压 A/200 V，短时修正 (B-128)*100/128 %
for _i in range(0x14, 0x1C):
    _bank = (_i - 0x14) // 2 + 1
    _sen = (_i - 0x14) % 2 + 1
    PID_TABLE[_i] = (f"氧传感器 B{_bank}S{_sen}", "V",
                     lambda d, _i=_i: round(d[0] / 200, 2))

_BITMAP_BASES = (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0)

FUEL_SYS = {0: "开环", 1: "闭环", 2: "开环-发动机未暖", 4: "闭环-有故障回退",
            8: "闭环-燃油不足", 16: "开环-发动机过热"}


def _decode_pid(pid, data):
    if pid in _BITMAP_BASES and len(data) >= 4:
        bits = [hex(pid)[2:].upper().zfill(2) + f"{pid + b + 1:02X}"
                for b in range(32)
                if (data[b // 8] & (0x80 >> (b % 8))) and pid + b + 1 <= 0xFF]
        return ("支持位图", "", bits)
    if pid == 0x01 and data:
        return ("排放监控状态", "",
                f"MIL {'亮' if data[0] & 0x80 else '灭'} · 确认故障码计数 {data[0] & 0x7F}")
    if pid == 0x03 and data:
        return ("燃油系统状态", "", FUEL_SYS.get(data[0], f"码 {data[0]}"))
    fn = PID_TABLE.get(pid)
    if fn and data:                       # 单字节 PID（水温/修正等）只有 1 字节数据
        name, unit, dec = fn
        try:
            return (name, unit, dec(data))
        except Exception:
            return None
    return None


# ---------- DTC ----------

_DTC_SYS = {0: "P", 1: "C", 2: "B", 3: "U"}


def _decode_dtc(hi, lo):
    sys_ = _DTC_SYS[(hi >> 6) & 0x03]
    d2 = (hi >> 4) & 0x03
    d3 = hi & 0x0F
    d45 = lo
    return f"{sys_}{d2}{d3}{d45:02X}"


def _parse_dtc_response(msg: bytes, service: int):
    """43/47/4A 响应 → DTC 列表。全零 = 无故障码（不是「读取失败」）。"""
    out = []
    i = 0
    while i + 1 < len(msg):
        hi, lo = msg[i], msg[i + 1]
        if hi == 0 and lo == 0:
            i += 2
            continue
        out.append(_decode_dtc(hi, lo))
        i += 2
    return out


# ---------- 主解析 ----------

def parse_report(report: dict) -> dict:
    """wrenchatlas.obd_probe.v1 → 按 ECU 分桶的解析结果。"""
    if report.get("schema") != SCHEMA:
        raise ValueError(f"schema 不是 {SCHEMA}，拒绝导入")
    queries = report.get("queries") or []

    # 1) 每条查询按 CAN ID 分桶
    buckets: dict[str, list] = {}     # can_id -> [(request, msgs, status, time)]
    no_id: list = []
    for q in queries:
        status = _classify(q.get("response", ""))
        req = q.get("request") or ""
        frames = _split_frames(q.get("response", ""), req) if status == "ok" else []
        by_id: dict[str | None, list] = {}
        for cid, data in frames:
            if len(data) < 3 and cid is None:
                continue                                    # 回显碎片/噪声
            by_id.setdefault(cid, []).append(data)
        if not by_id:
            if not req.upper().startswith("AT"):        # AT 命令本就无 CAN 报文
                no_id.append(q)
            continue
        for cid, fr in by_id.items():
            key = cid or "??"
            buckets.setdefault(key, []).append({
                "request": q.get("request"), "time": q.get("time"),
                "status": status, "msgs": _isotp_reassemble(fr),
            })

    # 2) 逐 ECU 解码
    ecus = {}
    for cid in sorted(buckets):
        live, dtc, pend, perm, ident, unknown = {}, [], [], [], {}, []
        for entry in buckets[cid]:
            req = (entry["request"] or "").upper()
            for msg in entry["msgs"]:
                if isinstance(msg, dict):       # 重组失败的原始帧
                    unknown.append({"request": req, **msg})
                    continue
                data = list(msg)
                # 在报文里找服务响应字节（可能有厂家前缀）
                svc_idx = None
                for i, b in enumerate(data[:-1]):
                    if req.startswith("01") and b == 0x41 and data[i + 1] == int(req[2:4], 16):
                        svc_idx = i
                    elif req in ("03", "07", "0A") and b == {"03": 0x43, "07": 0x47, "0A": 0x4A}[req]:
                        svc_idx = i
                    elif req.startswith("09") and b == 0x49 and data[i + 1] == int(req[2:4], 16):
                        svc_idx = i
                    elif req.startswith("02") and b == 0x42:
                        svc_idx = i
                if svc_idx is None:
                    continue
                body = data[svc_idx:]
                try:
                    if req.startswith("01"):
                        pid = int(req[2:4], 16)
                        dec = _decode_pid(pid, body[2:])
                        if dec:
                            name, unit, val = dec
                            (live if pid not in _BITMAP_BASES else ident)[name] = {
                                "value": val, "unit": unit, "pid": f"{pid:02X}"}
                    elif req in ("03", "07", "0A"):
                        codes = _parse_dtc_response(body[1:], int(req, 16))
                        tgt = {"03": dtc, "07": pend, "0A": perm}[req]
                        tgt.extend(c for c in codes if c not in tgt)
                    elif req.startswith("0902"):
                        m = bytes(body)
                        k = m.find(b"490201")
                        if k >= 0 and len(m) >= k + 3 + 20:
                            ident["VIN"] = {"value": m[k + 3:k + 20].decode(
                                "ascii", "replace"), "unit": "", "pid": "09-02"}
                    elif req.startswith("0904"):
                        ident.setdefault("标定 ID", {"value": bytes(body[2:]).hex().upper(),
                                                   "unit": "", "pid": "09-04"})
                    elif req.startswith("02"):
                        pass  # 冻结帧：只保留原始帧，不解读
                except Exception:
                    unknown.append({"request": req, "raw": bytes(body).hex().upper()})
        ecus[cid] = {"live": live, "dtc_confirmed": dtc, "dtc_pending": pend,
                     "dtc_permanent": perm, "identity": ident, "unparsed": unknown}

    # 3) 会话元数据
    cap = report.get("capture") or {}
    dev = report.get("device") or {}
    return {
        "schema": SCHEMA,
        "exported_at": report.get("exported_at"),
        "capture": {"status": cap.get("status"), "summary": cap.get("summary"),
                    "started_at": cap.get("started_at"),
                    "advertised_pids": cap.get("advertised_mode01_pids") or [],
                    "skipped": cap.get("skipped_due_to_time_budget") or []},
        "adapter": {"name": dev.get("name"), "address": dev.get("address"),
                    "transport": dev.get("transport"),
                    "protocol": dev.get("adapter_protocol_response"),
                    "voltage": dev.get("adapter_voltage_response"),
                    "write_uuid": dev.get("selected_write_uuid"),
                    "notify_uuid": dev.get("selected_notify_uuid")},
        "phone": report.get("phone") or {},
        "ecus": ecus,
        "no_response_queries": [
            {"request": q.get("request"), "time": q.get("time"),
             "status": _classify(q.get("response", ""))}
            for q in no_id],
        "scope_note": "标准 OBD（发动机/排放层）读取。不包含 ABS / SRS / BCM / 四驱等"
                      "厂家专用模块，不构成全车模块扫描。",
    }


def store_report(pack_root: Path, report: dict) -> str:
    """落盘原始报告，返回 session id。目录 gitignore，避免 VIN 入库。"""
    sid = Path(report.get("exported_at") or "").name or "session"
    ts = sid  # exported_at 含时区，用时间戳更稳
    import time
    ts = time.strftime("%Y%m%d-%H%M%S")
    out_dir = pack_root / "data" / "obd"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"obd-report-{ts}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return ts


def list_sessions(pack_root: Path) -> list:
    out = []
    for f in sorted((pack_root / "data" / "obd").glob("obd-report-*.json")):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
            parse = None
            try:
                parse = parse_report(r)
            except Exception:
                pass
            out.append({"sid": f.stem.replace("obd-report-", ""),
                        "exported_at": r.get("exported_at"),
                        "status": (r.get("capture") or {}).get("status"),
                        "adapter": (r.get("device") or {}).get("name"),
                        "protocol": (r.get("device") or {}).get("adapter_protocol_response"),
                        "ecus": list((parse or {}).get("ecus", {}).keys()),
                        "queries": len(r.get("queries") or [])})
        except Exception:
            continue
    return out


def load_session(pack_root: Path, sid: str) -> dict | None:
    f = pack_root / "data" / "obd" / f"obd-report-{sid}.json"
    if not f.exists():
        return None
    return parse_report(json.loads(f.read_text(encoding="utf-8")))


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    r = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    p = parse_report(r)
    print(f"会话 {r.get('exported_at')} · 协议 {p['adapter']['protocol']}")
    for cid, e in p["ecus"].items():
        print(f"\nECU {cid}: 实时参数 {len(e['live'])} 项 · "
              f"DTC 确认 {e['dtc_confirmed'] or '无'} · 待定 {e['dtc_pending'] or '无'}")
        for k, v in list(e["live"].items())[:8]:
            print(f"   {k}: {v['value']} {v['unit']}")
        if e["identity"]:
            print("   身份:", {k: v["value"] for k, v in e["identity"].items()})
