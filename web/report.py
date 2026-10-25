"""
诊断报告生成器。

两种形态：
  1. 纯文本（手机上读、存文件、打印后手写勾选）
  2. HTML（A4 打印友好，黑白打印机也认得清）

设计铁律（与 SKILL.md 一致）：
  · 必带来源页码，没页码等于没依据
  · 必标置信度，不许暗示"已验证"
  · 存疑项单列一节，不许藏在正文里
  · 末尾固定免责，不许省

本模块不读写文件、不发请求，纯粹由数据生成字符串，方便单测。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

CONF_TEXT = {
    "read-clear": "原图清晰可读",
    "read-uncertain": "存疑 · 需核对",
    "vehicle-confirmed": "实车核对过",
}

ROLE_TEXT = {
    "source": "电源",
    "fuse": "保险丝",
    "switch": "开关",
    "relay": "继电器",
    "sensor": "传感器",
    "ecu": "控制单元",
    "splice": "接点",
    "load": "负载",
    "ground": "搭铁",
}

DISCLAIMER = (
    "本报告由 WrenchAtlas 依据原厂电路图人工判读生成，不含原厂手册内容。"
    "数据未经全部实车核对，维修请以原厂手册与专业判断为准。"
)

W = 60  # 纯文本行宽（显示宽度，中文占 2）


def _rule(ch: str = "─") -> str:
    return ch * W


def _disp(s: str) -> int:
    """显示宽度：中文与全角符号占两格。"""
    return sum(2 if ord(c) > 0x2E80 else 1 for c in s)


def _pad(s: str, width: int) -> str:
    """右侧补齐到指定显示宽度（width 指总显示宽度）。"""
    return s + " " * max(0, width - _disp(s))


def _clip(s: str, width: int) -> str:
    """截断到指定显示宽度，超出补省略号。"""
    if _disp(s) <= width:
        return s
    out, cw = "", 0
    for ch in s:
        w = 2 if ord(ch) > 0x2E80 else 1
        if cw + w > width - 1:
            break
        out += ch
        cw += w
    return out + "…"


BREAK_AT = "，。、；：！？）」』】…·,.;:!?)"
NO_LINE_START = "，。、；：！？）」』】…·%,.;:!?)"   # 不可出现在行首


def _is_word_char(ch: str) -> bool:
    """ASCII 字母数字视为词内字符，不在其中间断行（保护 E225.4 这类编号）。"""
    return ch.isascii() and (ch.isalnum() or ch in "._-")


def _wrap(text: str, width: int = W, indent: str = "   ") -> list[str]:
    """按显示宽度折行，优先在标点处断开，避免把词拆碎。"""
    if not text:
        return []
    avail = width - _disp(indent)
    if avail < 12:
        avail = width
        indent = ""
    lines: list[str] = []
    pending = text.strip()
    while _disp(pending) > avail:
        cut, cw = 0, 0
        for i, ch in enumerate(pending):
            w = 2 if ord(ch) > 0x2E80 else 1
            if cw + w > avail:
                break
            cw += w
            cut = i + 1
        if cut == 0:
            break
        # 1) 在已切片段后段回退到最近的标点
        floor = max(1, int(cut * 0.55))
        for i in range(cut - 1, floor - 1, -1):
            if pending[i] in BREAK_AT:
                cut = i + 1
                break
        # 2) 不在编号/单词中间断开
        guard = cut
        while guard > 1 and cut < len(pending) \
                and _is_word_char(pending[guard - 1]) and _is_word_char(pending[guard]):
            guard -= 1
        if guard > 1 and guard < cut:
            cut = guard
        elif guard == 1 and cut > 1:
            pass  # 整个词比一行还长，只能硬切
        # 3) 行首不放收尾标点
        while cut > 1 and cut < len(pending) and pending[cut] in NO_LINE_START:
            cut -= 1
        lines.append(indent + pending[:cut].rstrip())
        pending = pending[cut:].lstrip()
    if pending:
        lines.append(indent + pending)
    return lines


def load_verified(pack: Path) -> dict:
    f = pack / "data" / "verified.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text("utf-8"))
    except Exception:
        return {}


def _marks_of(verified: dict, circuit: dict) -> dict:
    return verified.get(circuit.get("system") or circuit.get("id") or "", {}) or {}


def render_text(circuit: dict, verified: dict | None = None) -> str:
    """单个系统的纯文本报告。"""
    ver = _marks_of(verified or {}, circuit)
    nodes = circuit.get("nodes", [])
    edges = circuit.get("edges", [])
    hints = circuit.get("diagnosis_hint", [])
    notes = circuit.get("notes", [])
    ids = {n["id"]: n for n in nodes}

    done = sum(1 for n in nodes if n["id"] in ver)
    out: list[str] = []

    # ── 抬头 ──
    out.append(_rule("═"))
    out.append(f" {circuit.get('name', '未命名系统')}")
    out.append(" WrenchAtlas · 长安铃木 SX4 2010 · M18A")
    out.append(_rule("═"))

    cf = circuit.get("confidence", "read-clear")
    out.append(f"置信度    {CONF_TEXT.get(cf, cf)}")
    out.append(f"来源      {circuit.get('source_label') or circuit.get('source_page', '（未标注）')}")
    if circuit.get("engine_coverage"):
        out.extend(_wrap(f"适用      {circuit['engine_coverage']}", W, ""))
    if circuit.get("variant_warning"):
        out.extend(_wrap(f"⚠ 变体    {circuit['variant_warning']}", W, ""))
    out.append(f"核对进度  {done}/{len(nodes)} 个环节已实车核对")
    out.append(f"生成时间  {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # ── 环节 ──
    out.append("")
    out.append(_rule())
    out.append(" 环节（按信号流向，可打印后手写勾选）")
    out.append(_rule())
    for i, n in enumerate(nodes, 1):
        box = "[✓]" if n["id"] in ver else "[ ]"
        role = ROLE_TEXT.get(n.get("role", ""), n.get("role", ""))
        head = f"{box} {i}. {n.get('label', '')}"
        sub = n.get("sub", "")
        line = _pad(head, W - _disp(role) - 1) + role
        out.append(line)
        if sub:
            out.append(f"       {sub}")
        if n.get("pins"):
            out.append(f"       引脚: {' / '.join(n['pins'])}")
        if n.get("detail"):
            out.extend(_wrap(n["detail"], W, "       "))
        if n.get("confidence") == "read-uncertain":
            out.extend(_wrap(f"⚠ 存疑: {n.get('uncertain', '原图未明确')}", W, "       "))
        if n.get("applies_to"):
            out.append(f"       适用: 仅 {n['applies_to']}")
        if n["id"] in ver:
            note = ver[n["id"]].get("note") or ""
            when = ver[n["id"]].get("at", "")
            out.append(f"       ✓ 已核对 {when}{' · ' + note if note else ''}")
        out.append("")

    # ── 连线 ──
    if edges:
        out.append(_rule())
        out.append(" 连线（线色 / 途经针脚）")
        out.append(_rule())
        for e in edges:
            a = ids.get(e.get("from"), {}).get("label", e.get("from", "?"))
            b = ids.get(e.get("to"), {}).get("label", e.get("to", "?"))
            color = e.get("color", "")
            via = e.get("via", "")
            tail = f"  [{color}]" if color else ""
            out.append(f" · {a} → {b}{tail}")
            if via:
                out.extend(_wrap(f"经 {via}", W, "   "))
            if e.get("note"):
                out.extend(_wrap(e["note"], W, "   "))
            if e.get("applies_to"):
                out.append(f"   仅 {e['applies_to']}")
        out.append("")

    # ── 诊断提示 ──
    if hints:
        out.append(_rule())
        out.append(" 排查步骤（按顺序执行，每条可单独勾掉）")
        out.append(_rule())
        for i, h in enumerate(hints, 1):
            wrapped = _wrap(h, W, "       ")
            if wrapped:
                out.append(f" [ ] {i}. {wrapped[0].strip()}")
                out.extend(wrapped[1:])
            out.append("")

    # ── 存疑项 ──
    unsure = [n for n in nodes if n.get("confidence") == "read-uncertain"]
    if unsure:
        out.append(_rule("┄"))
        out.append(" ⚠ 待核对项（原图判读不确定，用前请实测）")
        out.append(_rule("┄"))
        for n in unsure:
            out.extend(_wrap(f"· {n.get('label')}（{n.get('sub', '')}）", W, " "))
            out.extend(_wrap(n.get("uncertain", "原图未明确"), W, "   "))
        out.append("")

    # ── 跨系统牵连 ──
    shared = [n for n in nodes if n.get("shared_connectors")]
    if shared:
        out.append(_rule("┄"))
        out.append(" 跨系统牵连（这些件坏了会牵连别的系统）")
        out.append(_rule("┄"))
        for n in shared:
            for s in n["shared_connectors"]:
                others = "、".join(s.get("others", []))
                out.extend(_wrap(f"· {n.get('label')} 的 {s.get('conn')} 同时用于: {others}",
                                 W, " "))
        out.append("")

    # ── 备注 ──
    if notes:
        out.append(_rule("┄"))
        out.append(" 备注")
        out.append(_rule("┄"))
        for x in notes:
            out.extend(_wrap(f"· {x}", W, " "))
        out.append("")

    out.append(_rule("═"))
    out.extend(_wrap(" " + DISCLAIMER, W, ""))
    out.append(_rule("═"))
    return "\n".join(out)


def render_all_text(circuits: list[dict], verified: dict | None = None,
                    pack_name: str = "suzuki-sx4-2010") -> str:
    """全量报告：所有系统 + 总索引 + 总进度。"""
    ver = verified or {}
    out: list[str] = []
    out.append(_rule("═"))
    out.append(" WrenchAtlas 全量诊断手册")
    out.append(f" 车型包 {pack_name} · 长安铃木 SX4 2010 · M18A")
    out.append(f" 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    out.append(_rule("═"))
    out.append("")

    # 总索引
    total_nodes = sum(len(c.get("nodes", [])) for c in circuits)
    total_done = sum(
        sum(1 for n in c.get("nodes", []) if n["id"] in _marks_of(ver, c))
        for c in circuits
    )
    total_hints = sum(len(c.get("diagnosis_hint", [])) for c in circuits)
    out.append(f" 系统 {len(circuits)} 个 · 环节 {total_nodes} 个 · "
               f"诊断提示 {total_hints} 条")
    out.append(f" 实车核对进度 {total_done}/{total_nodes}")
    out.append("")
    out.append(_rule())
    out.append(f" {'#':>2}  {_pad('系统', 24)}{'环节':>4}{'存疑':>5}{'核对':>6}")
    out.append(_rule())
    for i, c in enumerate(circuits, 1):
        nodes = c.get("nodes", [])
        un = sum(1 for n in nodes if n.get("confidence") == "read-uncertain")
        dn = sum(1 for n in nodes if n["id"] in _marks_of(ver, c))
        name = _clip(c.get("name", ""), 24)
        out.append(f" {i:>2}  {_pad(name, 24)}{len(nodes):>4}{un:>5}{dn:>6}")
    out.append(_rule())
    out.append("")

    # 各系统正文
    for i, c in enumerate(circuits, 1):
        out.append("")
        out.append(f"【{i}/{len(circuits)}】")
        out.append(render_text(c, ver))
    return "\n".join(out)


# ────────────────────────── HTML（打印版） ──────────────────────────

def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def render_html(circuit: dict, verified: dict | None = None) -> str:
    """单系统 A4 打印页。黑白打印机可用，勾选框留白给人手写。"""
    ver = _marks_of(verified or {}, circuit)
    nodes = circuit.get("nodes", [])
    edges = circuit.get("edges", [])
    hints = circuit.get("diagnosis_hint", [])
    notes = circuit.get("notes", [])
    ids = {n["id"]: n for n in nodes}
    done = sum(1 for n in nodes if n["id"] in ver)
    unsure = [n for n in nodes if n.get("confidence") == "read-uncertain"]
    shared = [n for n in nodes if n.get("shared_connectors")]
    cf = circuit.get("confidence", "read-clear")

    h: list[str] = []
    h.append(f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(circuit.get('name','诊断报告'))} · WrenchAtlas</title>
<style>
  @page{{size:A4;margin:14mm 12mm}}
  *{{box-sizing:border-box}}
  body{{margin:0;padding:20px 16px 60px;background:#fff;color:#111;
    font:14px/1.65 "Microsoft YaHei",system-ui,-apple-system,sans-serif;
    max-width:820px;margin:0 auto}}
  h1{{font-size:21px;margin:0 0 2px;letter-spacing:.5px}}
  .brand{{font-size:12px;color:#666;margin-bottom:14px}}
  .meta{{border:1px solid #d5d5d5;border-radius:6px;padding:10px 12px;
    font-size:12.5px;line-height:1.8;margin-bottom:18px}}
  .meta b{{display:inline-block;min-width:76px;color:#555;font-weight:600}}
  .meta .warn{{color:#a15c00;font-weight:600}}
  h2{{font-size:14.5px;margin:22px 0 8px;padding-bottom:4px;
    border-bottom:2px solid #222;letter-spacing:.3px}}
  h2 span{{font-weight:400;font-size:12px;color:#777;margin-left:8px}}
  .node{{border:1px solid #e0e0e0;border-radius:5px;padding:8px 10px;margin-bottom:8px;
    page-break-inside:avoid}}
  .node .hd{{display:flex;align-items:baseline;gap:8px}}
  .box{{flex:0 0 auto;width:13px;height:13px;border:1.5px solid #333;
    border-radius:2px;display:inline-block;position:relative;top:1px}}
  .box.filled{{background:#333}}
  .box.filled::after{{content:"✓";color:#fff;font-size:10px;
    position:absolute;left:1.5px;top:-3px}}
  .nm{{font-weight:600;font-size:13.5px}}
  .role{{font-size:11px;color:#888;border:1px solid #ddd;border-radius:3px;
    padding:0 5px;margin-left:auto;white-space:nowrap}}
  .sub{{font-size:12px;color:#666;margin:3px 0 0 21px}}
  .pin{{font-family:Consolas,monospace;font-size:11.5px;background:#f2f2f2;
    border-radius:3px;padding:1px 5px;margin:0 4px 4px 0;display:inline-block}}
  .pins{{margin:5px 0 0 21px}}
  .dt{{font-size:12.5px;color:#333;margin:5px 0 0 21px}}
  .uc{{font-size:12.5px;color:#a15c00;margin:5px 0 0 21px}}
  .ok{{font-size:11.5px;color:#1a7a3e;margin:4px 0 0 21px}}
  .edge{{font-size:12.5px;padding:4px 0;border-bottom:1px dotted #e5e5e5}}
  .edge:last-child{{border-bottom:0}}
  .cc{{font-family:Consolas,monospace;font-size:11px;background:#f4f4f4;
    padding:1px 4px;border-radius:3px;margin-left:6px}}
  .via{{color:#666;font-size:11.5px}}
  ol.hints{{margin:0;padding-left:22px}}
  ol.hints li{{margin-bottom:7px;font-size:13px;page-break-inside:avoid}}
  ul.plain{{margin:0;padding-left:20px;font-size:12.5px;color:#333}}
  ul.plain li{{margin-bottom:5px}}
  .foot{{margin-top:26px;padding-top:10px;border-top:1px solid #ccc;
    font-size:11px;color:#777;line-height:1.7}}
  .toolbar{{position:sticky;top:0;background:#fff;padding:8px 0 12px;
    display:flex;gap:8px;z-index:5}}
  .toolbar a,.toolbar button{{font:inherit;font-size:12.5px;padding:7px 14px;
    border:1px solid #ccc;border-radius:6px;background:#fafafa;color:#222;
    text-decoration:none;cursor:pointer}}
  .toolbar .primary{{background:#222;color:#fff;border-color:#222}}
  @media print{{
    .toolbar{{display:none}}
    body{{padding:0}}
    h2{{page-break-after:avoid}}
  }}
</style></head><body>
<div class="toolbar">
  <button class="primary" onclick="window.print()">打印 / 存 PDF</button>
  <a href="/api/report.txt?sys={_esc(circuit.get('system') or circuit.get('id',''))}">下载纯文本</a>
  <a href="/flow?sys={_esc(circuit.get('system') or circuit.get('id',''))}">← 回流图</a>
</div>
<h1>{_esc(circuit.get('name','诊断报告'))}</h1>
<div class="brand">WrenchAtlas · 长安铃木 SX4 2010 · M18A</div>
<div class="meta">
  <div><b>置信度</b>{_esc(CONF_TEXT.get(cf, cf))}</div>
  <div><b>来源</b>{_esc(circuit.get('source_label') or circuit.get('source_page','（未标注）'))}</div>""")

    if circuit.get("engine_coverage"):
        h.append(f"  <div><b>适用</b>{_esc(circuit['engine_coverage'])}</div>")
    if circuit.get("variant_warning"):
        h.append(f'  <div><b>变体</b><span class="warn">⚠ '
                 f'{_esc(circuit["variant_warning"])}</span></div>')
    h.append(f"  <div><b>核对进度</b>{done}/{len(nodes)} 个环节已实车核对</div>")
    h.append(f"  <div><b>生成于</b>{datetime.now().strftime('%Y-%m-%d %H:%M')}</div>")
    h.append("</div>")

    # 环节
    h.append(f"<h2>环节<span>{len(nodes)} 个 · 按信号流向</span></h2>")
    for i, n in enumerate(nodes, 1):
        is_done = n["id"] in ver
        role = ROLE_TEXT.get(n.get("role", ""), n.get("role", ""))
        h.append('<div class="node">')
        h.append(f'  <div class="hd"><span class="box{" filled" if is_done else ""}">'
                 f'</span><span class="nm">{i}. {_esc(n.get("label",""))}</span>'
                 f'<span class="role">{_esc(role)}</span></div>')
        if n.get("sub"):
            h.append(f'  <div class="sub">{_esc(n["sub"])}</div>')
        if n.get("pins"):
            pins = "".join(f'<span class="pin">{_esc(p)}</span>' for p in n["pins"])
            h.append(f'  <div class="pins">{pins}</div>')
        if n.get("detail"):
            h.append(f'  <div class="dt">{_esc(n["detail"])}</div>')
        if n.get("applies_to"):
            h.append(f'  <div class="dt">仅 {_esc(n["applies_to"])} 车型</div>')
        if n.get("confidence") == "read-uncertain":
            h.append(f'  <div class="uc">⚠ 存疑：'
                     f'{_esc(n.get("uncertain","原图未明确"))}</div>')
        if is_done:
            m = ver[n["id"]]
            h.append(f'  <div class="ok">✓ 已核对 {_esc(m.get("at",""))}'
                     f'{" · " + _esc(m["note"]) if m.get("note") else ""}</div>')
        h.append("</div>")

    # 连线
    if edges:
        h.append(f"<h2>连线<span>{len(edges)} 条</span></h2>")
        for e in edges:
            a = ids.get(e.get("from"), {}).get("label", e.get("from", "?"))
            b = ids.get(e.get("to"), {}).get("label", e.get("to", "?"))
            seg = f"{_esc(a)} → {_esc(b)}"
            if e.get("color"):
                seg += f'<span class="cc">{_esc(e["color"])}</span>'
            if e.get("via"):
                seg += f' <span class="via">经 {_esc(e["via"])}</span>'
            if e.get("note"):
                seg += f' <span class="via">· {_esc(e["note"])}</span>'
            if e.get("applies_to"):
                seg += f' <span class="via">· 仅 {_esc(e["applies_to"])}</span>'
            h.append(f'<div class="edge">{seg}</div>')

    # 排查步骤
    if hints:
        h.append(f"<h2>排查步骤<span>按顺序执行 · {len(hints)} 条</span></h2>")
        h.append('<ol class="hints">')
        for x in hints:
            h.append(f"  <li>{_esc(x)}</li>")
        h.append("</ol>")

    # 存疑
    if unsure:
        h.append(f"<h2>⚠ 待核对项<span>{len(unsure)} 处 · 用前请实测</span></h2>")
        h.append('<ul class="plain">')
        for n in unsure:
            h.append(f"  <li><b>{_esc(n.get('label',''))}</b>"
                     f"（{_esc(n.get('sub',''))}）：{_esc(n.get('uncertain','原图未明确'))}</li>")
        h.append("</ul>")

    # 跨系统
    if shared:
        h.append("<h2>跨系统牵连</h2>")
        h.append('<ul class="plain">')
        for n in shared:
            for s in n["shared_connectors"]:
                others = "、".join(s.get("others", []))
                h.append(f"  <li><b>{_esc(n.get('label',''))}</b> 的 "
                         f"<code>{_esc(s.get('conn',''))}</code> 同时用于："
                         f"{_esc(others)}</li>")
        h.append("</ul>")

    if notes:
        h.append("<h2>备注</h2>")
        h.append('<ul class="plain">')
        for x in notes:
            h.append(f"  <li>{_esc(x)}</li>")
        h.append("</ul>")

    h.append(f'<div class="foot">{_esc(DISCLAIMER)}</div>')
    h.append("</body></html>")
    return "\n".join(h)
