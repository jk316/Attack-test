"""Generate a self-contained HTML report from the experiment history log.

Reads ``data/experiment.jsonl`` (one JSON per line), normalizes the messy
historical ``params`` field into a uniform schema, splits records into
per-run sessions, and renders a single HTML file (ECharts via CDN, data
inlined) that shows an overview + per-session drill-down.

Usage:
    uv run python scripts/generate_history_report.py \
        [--log data/experiment.jsonl] [--out output/attack_history.html]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

# ── Category mapping ──────────────────────────────────────────────

_CATEGORY_MAP = {
    "pktgen_udp_flood": "UDP 洪水",
    "pktgen_tcp_flood": "TCP SYN 洪水",
    "pktgen_icmp_flood": "ICMP 洪水",
    "pktgen_arp_flood": "ARP 洪水",
    "pktgen_range_scan": "范围扫描",
    "pktgen_packet_sequence": "范围扫描",
    "traffic_send": "Scapy UDP",
    "mixed_traffic_send": "混合流量",
}

_MIXED_KEYS = ("streams", "traffic_type", "traffic_spec", "traffic_spec_json")


# ── Helpers ───────────────────────────────────────────────────────

def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _infer_tool(params: dict) -> str:
    """Guess the tool name when neither ``tool`` nor ``protocol`` is present."""
    if any(k in params for k in _MIXED_KEYS):
        return "mixed_traffic_send"
    if params.get("rate") is not None:
        # pktgen family (rare without an explicit tool/protocol)
        return "pktgen_udp_flood"
    return "traffic_send"


def _categorize(tool: str) -> str:
    """Map a tool name to a human-readable attack category.

    Exact match first, then prefix/keyword matching so LLM-invented or
    descriptive tool names (e.g. ``trex_stl_tcp_syn_flood``,
    ``UDP (Scapy)``, ``traffic_send_max``) still land in a sensible bucket
    instead of ``"其他"``.
    """
    if tool in _CATEGORY_MAP:
        return _CATEGORY_MAP[tool]

    t = tool.lower()

    # TRex client scripts (run via run_python_file)
    if "trex" in t:
        if "tcp" in t or "syn" in t:
            return "TRex TCP SYN"
        if "udp" in t:
            return "TRex UDP"
        if "icmp" in t:
            return "TRex ICMP"
        return "TRex 其他"

    # Suffixed standard tools (e.g. traffic_send_max)
    if t.startswith("traffic_send"):
        return "Scapy UDP"
    if t.startswith("mixed_traffic_send"):
        return "混合流量"
    if t.startswith("pktgen_"):
        if "arp" in t:
            return "ARP 洪水"
        if "scan" in t or "range" in t or "sequence" in t:
            return "范围扫描"
        if "tcp" in t:
            return "TCP SYN 洪水"
        if "icmp" in t:
            return "ICMP 洪水"
        if "udp" in t:
            return "UDP 洪水"

    # Descriptive names (e.g. "UDP (Scapy)", "Mixed (Scapy)")
    if "mixed" in t:
        return "混合流量"
    if "scapy" in t:
        return "Scapy UDP"
    if "arp" in t:
        return "ARP 洪水"
    if "scan" in t or "range" in t or "sequence" in t:
        return "范围扫描"
    if "udp" in t:
        return "UDP 洪水"
    if "tcp" in t or "syn" in t:
        return "TCP SYN 洪水"
    if "icmp" in t:
        return "ICMP 洪水"
    return "其他"


def _extract_description(params: dict) -> str:
    """Extract a human-readable description of mixed-traffic composition."""
    for key in _MIXED_KEYS:
        if key in params:
            value = params[key]
            if isinstance(value, (list, dict)):
                return json.dumps(value, ensure_ascii=False)
            return str(value)
    return ""


# ── Normalization ─────────────────────────────────────────────────

def normalize_record(record: dict) -> dict:
    """Normalize one raw JSONL record into a uniform schema."""
    params = record.get("params", {}) or {}

    tool = params.get("tool") or params.get("protocol") or _infer_tool(params)

    duration_s = _as_float(params.get("duration_s"))
    if duration_s is None and params.get("duration_ms") is not None:
        duration_s = (_as_float(params.get("duration_ms")) or 0) / 1000

    return {
        "iteration": _as_int(record.get("iteration")),
        "tool": tool,
        "category": _categorize(tool),
        "dst_ip": params.get("dst_ip"),
        "dst_port": _as_int(params.get("dst_port") or params.get("dport")),
        "pps": _as_float(params.get("pps")),
        "rate": _as_float(params.get("rate")),
        "duration_s": duration_s,
        "packet_size": _as_int(params.get("packet_size") or params.get("pktSize")),
        "description": _extract_description(params),
        "rtt": _as_float(record.get("rtt")),
        "loss": _as_float(record.get("loss")),
        "timestamp": record.get("timestamp"),
    }


def split_sessions(records: list[dict]) -> list[dict]:
    """Split records into per-run sessions and assign ``session_id``.

    A new session starts whenever ``iteration`` resets (<= the previous
    record's iteration), which is how each experiment run re-counts from 1.
    Records are first sorted by timestamp.
    """
    ordered = sorted(records, key=lambda r: r["timestamp"] or "")
    sessions: list[dict] = []
    session_id = -1
    prev_iter: int | None = None

    for rec in ordered:
        iteration = rec["iteration"]
        if prev_iter is None or (iteration is not None and iteration <= prev_iter):
            session_id += 1
            sessions.append({"id": session_id, "records": []})
        rec["session_id"] = session_id
        sessions[-1]["records"].append(rec)
        prev_iter = iteration

    return sessions


def build_session_summary(sessions: list[dict]) -> list[dict]:
    """Build one summary row per session for the session-list table."""
    result: list[dict] = []
    for session in sessions:
        recs = session["records"]
        rtts = [r["rtt"] for r in recs if r["rtt"] is not None]
        ips = list(dict.fromkeys(r["dst_ip"] for r in recs if r["dst_ip"]))
        cats = list(dict.fromkeys(r["category"] for r in recs))
        max_rtt = max(rtts) if rtts else 0.0
        max_idx = rtts.index(max_rtt) if rtts else -1
        max_attack = recs[max_idx]["category"] if max_idx >= 0 else ""
        result.append({
            "id": session["id"],
            "start_time": recs[0]["timestamp"],
            "end_time": recs[-1]["timestamp"],
            "rounds": len(recs),
            "dst_ips": ips,
            "categories": cats,
            "avg_rtt": round(sum(rtts) / len(rtts), 3) if rtts else 0.0,
            "max_rtt": max_rtt,
            "max_rtt_attack": max_attack,
        })
    return result


# ── HTML template ─────────────────────────────────────────────────

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>攻击历史可视化</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
  :root {
    --bg: #0f141b; --panel: #171e28; --panel2: #1d2633;
    --text: #dce4ef; --muted: #8b98ab; --accent: #4da3ff;
    --border: #273244; --good: #34d399; --warn: #fbbf24; --bad: #f87171;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text);
         font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; }
  header { padding: 18px 24px; border-bottom: 1px solid var(--border);
           display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
  header h1 { font-size: 18px; margin: 0; font-weight: 600; }
  .tabs { display: flex; gap: 8px; }
  .tab { padding: 6px 14px; border-radius: 6px; cursor: pointer; color: var(--muted);
         border: 1px solid var(--border); background: transparent; font-size: 13px; }
  .tab.active { background: var(--accent); color: #06121f; border-color: var(--accent); font-weight: 600; }
  main { padding: 20px 24px; max-width: 1400px; margin: 0 auto; }
  .kpi { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 18px; }
  .kpi .card { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }
  .kpi .num { font-size: 26px; font-weight: 700; margin-top: 4px; }
  .kpi .label { color: var(--muted); font-size: 12px; }
  .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; margin-bottom: 18px; }
  .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 14px; }
  .panel h2 { font-size: 14px; margin: 0 0 10px; color: var(--text); font-weight: 600; }
  .chart { width: 100%; height: 320px; }
  .scatter-row { display: flex; gap: 12px; flex-wrap: wrap; }
  .scatter-col { flex: 1; min-width: 240px; }
  .scatter-col h3 { font-size: 12px; color: var(--muted); text-align: center; margin: 0 0 6px; font-weight: 500; }
  .chart-sm { width: 100%; height: 260px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 500; position: sticky; top: 0; background: var(--panel); }
  tr.clickable { cursor: pointer; }
  tr.clickable:hover { background: var(--panel2); }
  .tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
  .muted { color: var(--muted); }
  #detailView { display: none; }
  .back-btn { padding: 6px 14px; border-radius: 6px; cursor: pointer; border: 1px solid var(--border);
              background: var(--panel); color: var(--text); font-size: 13px; }
  .back-btn:hover { background: var(--panel2); }
  .detail-head { display: flex; gap: 20px; flex-wrap: wrap; margin-bottom: 14px; }
  .detail-head .item { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; }
  .detail-head .item .label { color: var(--muted); font-size: 12px; }
  @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<header>
  <h1>攻击历史可视化</h1>
  <div class="tabs">
    <button class="tab active" id="tabOverview" onclick="showOverview()">总览</button>
    <button class="tab" id="tabDetail" onclick="showDetailLast()">会话详情</button>
  </div>
</header>
<main>
  <div id="overviewView">
    <div class="kpi" id="kpiRow"></div>
    <div class="grid">
      <div class="panel"><h2>攻击种类分布</h2><div id="chartCategory" class="chart"></div></div>
      <div class="panel"><h2>攻击效果排行（RTT）</h2><div id="chartEffect" class="chart"></div></div>
      <div class="panel"><h2>目标 IP 分布</h2><div id="chartTarget" class="chart"></div></div>
      <div class="panel"><h2>强度 vs 效果（按工具拆分）</h2>
        <div class="scatter-row">
          <div class="scatter-col"><h3>Scapy · pps</h3><div id="chartScapy" class="chart-sm"></div></div>
          <div class="scatter-col"><h3>Pktgen · rate %</h3><div id="chartPktgen" class="chart-sm"></div></div>
          <div class="scatter-col"><h3>TRex · pps</h3><div id="chartTrex" class="chart-sm"></div></div>
        </div>
      </div>
    </div>
    <div class="panel"><h2>会话列表（点击查看完整过程）</h2>
      <table id="sessionTable"><thead><tr>
        <th>#</th><th>开始时间</th><th>结束时间</th><th>轮数</th><th>目标 IP</th><th>攻击类型</th><th>平均 RTT</th><th>最大 RTT</th><th>最高 RTT 攻击</th>
      </tr></thead><tbody></tbody></table>
    </div>
  </div>

  <div id="detailView">
    <button class="back-btn" onclick="showOverview()">← 返回总览</button>
    <div class="detail-head" id="detailHead"></div>
    <div class="grid">
      <div class="panel"><h2>RTT 随轮次变化</h2><div id="chartRttLine" class="chart"></div></div>
      <div class="panel"><h2>攻击序列</h2><div id="chartAttackSeq" class="chart"></div></div>
    </div>
    <div class="panel"><h2>逐轮明细</h2>
      <table id="detailTable"><thead><tr>
        <th>轮次</th><th>工具</th><th>类别</th><th>目标</th><th>端口</th><th>pps</th><th>rate</th><th>时长(s)</th><th>包大小</th><th>RTT</th><th>描述</th>
      </tr></thead><tbody></tbody></table>
    </div>
  </div>
</main>

<script>
const DATA = __DATA_JSON__;

const CAT_COLORS = {
  'UDP 洪水': '#4da3ff', 'TCP SYN 洪水': '#f87171', 'ICMP 洪水': '#fbbf24',
  'ARP 洪水': '#a78bfa', '范围扫描': '#34d399', 'Scapy UDP': '#22d3ee',
  '混合流量': '#fb7185', 'TRex TCP SYN': '#f43f5e', 'TRex UDP': '#f59e0b',
  'TRex ICMP': '#eab308', 'TRex 其他': '#94a3b8', '其他': '#94a3b8'
};
const colorOf = c => CAT_COLORS[c] || '#94a3b8';

const records = DATA.records, sessions = DATA.sessions;
const charts = {};

function initChart(id) {
  if (!charts[id]) charts[id] = echarts.init(document.getElementById(id));
  return charts[id];
}
function resizeAll() { Object.values(charts).forEach(c => c.resize()); }

function fmtTime(ts) {
  if (!ts) return '-';
  const d = new Date(ts);
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

// ── Overview ─────────────────────────────────────────────────────
function renderKpi() {
  const rtts = records.map(r => r.rtt).filter(v => v != null);
  const avg = rtts.length ? (rtts.reduce((a,b)=>a+b,0)/rtts.length) : 0;
  const max = rtts.length ? Math.max(...rtts) : 0;
  const maxRec = records.find(r => r.rtt === max);
  const ips = new Set(records.map(r => r.dst_ip).filter(Boolean));
  const cats = new Set(records.map(r => r.category));
  const cards = [
    ['总攻击次数', records.length],
    ['会话数', sessions.length],
    ['目标 IP 数', ips.size],
    ['攻击类型数', cats.size],
    ['平均 RTT (ms)', avg.toFixed(3)],
    ['最大 RTT (ms)', max + (maxRec ? ` · ${maxRec.category}` : '')],
  ];
  document.getElementById('kpiRow').innerHTML = cards.map(c =>
    `<div class="card"><div class="label">${c[0]}</div><div class="num">${c[1]}</div></div>`
  ).join('');
}

function renderCategoryChart() {
  const cnt = {};
  records.forEach(r => cnt[r.category] = (cnt[r.category]||0)+1);
  const data = Object.entries(cnt).map(([name, value]) => ({name, value}));
  initChart('chartCategory').setOption({
    tooltip: {trigger:'item'},
    legend: {bottom: 0, textStyle: {color:'#8b98ab'}},
    series: [{type:'pie', radius:['40%','70%'], data,
      label: {color:'#dce4ef'}, itemStyle: {borderColor:'#0f141b', borderWidth:2}}]
  });
}

function renderEffectChart() {
  const byCat = {};
  records.forEach(r => {
    (byCat[r.category] = byCat[r.category] || {rtts:[], max:0});
    if (r.rtt != null) { byCat[r.category].rtts.push(r.rtt); byCat[r.category].max = Math.max(byCat[r.category].max, r.rtt); }
  });
  const cats = Object.keys(byCat).sort((a,b) => avg(byCat[b].rtts) - avg(byCat[a].rtts));
  initChart('chartEffect').setOption({
    tooltip: {trigger:'axis'},
    grid: {left: 100, right: 30, top: 20, bottom: 30},
    xAxis: {type:'value', name:'RTT (ms)'},
    yAxis: {type:'category', data: cats, axisLabel: {color:'#dce4ef'}},
    series: [
      {name:'平均 RTT', type:'bar', data: cats.map(c => avg(byCat[c].rtts).toFixed(3)),
       itemStyle: {color: c => colorOf(cats[c.dataIndex])}},
      {name:'最大 RTT', type:'bar', data: cats.map(c => byCat[c].max),
       itemStyle: {color:'#f87171', opacity:0.7}}
    ],
    legend: {textStyle:{color:'#8b98ab'}}
  });
  function avg(arr){ return arr.length ? arr.reduce((a,b)=>a+b,0)/arr.length : 0; }
}

function renderTargetChart() {
  const cnt = {};
  records.forEach(r => { if (r.dst_ip) cnt[r.dst_ip] = (cnt[r.dst_ip]||0)+1; });
  const entries = Object.entries(cnt).sort((a,b) => b[1]-a[1]);
  initChart('chartTarget').setOption({
    tooltip: {trigger:'axis'},
    grid: {left: 50, right: 30, top: 20, bottom: 40},
    xAxis: {type:'category', data: entries.map(e=>e[0]), axisLabel:{color:'#dce4ef', rotate:20}},
    yAxis: {type:'value'},
    series: [{type:'bar', data: entries.map(e=>e[1]), itemStyle:{color:'#4da3ff'}}]
  });
}

function renderScatterChart() {
  function groupOf(tool) {
    const t = (tool || '').toLowerCase();
    if (t.includes('trex')) return 'trex';
    if (t.includes('pktgen')) return 'pktgen';
    return 'scapy';
  }
  const scapy = records.filter(r => groupOf(r.tool) === 'scapy' && r.pps != null && r.rtt != null);
  const pktgen = records.filter(r => groupOf(r.tool) === 'pktgen' && r.rate != null && r.rtt != null);
  const trex = records.filter(r => groupOf(r.tool) === 'trex' && r.pps != null && r.rtt != null);

  function scatterOpt(xData, color, xName) {
    return {
      tooltip: {trigger:'item', formatter: p => `${p.data.tool}<br>${xName}: ${p.value[0]}<br>RTT: ${p.value[1]} ms`},
      grid: {left: 50, right: 20, top: 20, bottom: 40},
      xAxis: {type:'value', name:xName, nameTextStyle:{color:'#8b98ab'}},
      yAxis: {type:'value', name:'RTT (ms)', nameTextStyle:{color:'#8b98ab'}},
      series: [{type:'scatter', data:xData, itemStyle:{color}}]
    };
  }
  initChart('chartScapy').setOption(scatterOpt(scapy.map(r => ({value:[r.pps, r.rtt], tool:r.tool})), '#22d3ee', 'pps'));
  initChart('chartPktgen').setOption(scatterOpt(pktgen.map(r => ({value:[r.rate, r.rtt], tool:r.tool})), '#4da3ff', 'rate %'));
  initChart('chartTrex').setOption(scatterOpt(trex.map(r => ({value:[r.pps, r.rtt], tool:r.tool})), '#f43f5e', 'pps'));
}

function renderSessionList() {
  const tb = document.querySelector('#sessionTable tbody');
  tb.innerHTML = [...sessions].reverse().map(s => `
    <tr class="clickable" onclick="showSession(${s.id})">
      <td>${s.id + 1}</td>
      <td>${fmtTime(s.start_time)}</td>
      <td>${fmtTime(s.end_time)}</td>
      <td>${s.rounds}</td>
      <td>${s.dst_ips.join(', ')}</td>
      <td>${s.categories.map(c => `<span class="tag" style="background:${colorOf(c)}22;color:${colorOf(c)}">${c}</span>`).join(' ')}</td>
      <td>${s.avg_rtt}</td>
      <td>${s.max_rtt}</td>
      <td>${s.max_rtt_attack}</td>
    </tr>`).join('');
}

// ── Detail ───────────────────────────────────────────────────────
let currentSession = null;

function showSession(id) {
  currentSession = id;
  document.getElementById('overviewView').style.display = 'none';
  document.getElementById('detailView').style.display = 'block';
  document.getElementById('tabOverview').classList.remove('active');
  document.getElementById('tabDetail').classList.add('active');
  renderDetail(id);
}

function showDetailLast() {
  if (currentSession == null && sessions.length) showSession(sessions.length - 1);
  else if (currentSession == null) alert('暂无会话数据');
  else showSession(currentSession);
}

function showOverview() {
  document.getElementById('overviewView').style.display = 'block';
  document.getElementById('detailView').style.display = 'none';
  document.getElementById('tabDetail').classList.remove('active');
  document.getElementById('tabOverview').classList.add('active');
  // 容器从 display:none 恢复后尺寸会归零，需强制重算
  setTimeout(resizeAll, 50);
}

function renderDetail(id) {
  const s = sessions.find(x => x.id === id);
  if (!s) return;
  const recs = records.filter(r => r.session_id === id).sort((a,b) => a.iteration - b.iteration);

  document.getElementById('detailHead').innerHTML = `
    <div class="item"><div class="label">时间</div>${fmtTime(s.start_time)} ~ ${fmtTime(s.end_time)}</div>
    <div class="item"><div class="label">目标</div>${s.dst_ips.join(', ')}</div>
    <div class="item"><div class="label">轮数</div>${s.rounds}</div>
    <div class="item"><div class="label">平均 RTT</div>${s.avg_rtt} ms</div>
    <div class="item"><div class="label">最大 RTT</div>${s.max_rtt} ms (${s.max_rtt_attack})</div>`;

  // RTT line
  initChart('chartRttLine').setOption({
    tooltip: {trigger:'axis', formatter: ps => {
      const p = ps[0]; const r = recs[p.dataIndex];
      return `第${r.iteration}轮 ${r.category}<br>RTT: ${r.rtt} ms<br>${r.tool}`;
    }},
    grid: {left: 50, right: 30, top: 30, bottom: 40},
    xAxis: {type:'category', name:'轮次', data: recs.map(r => '#' + r.iteration)},
    yAxis: {type:'value', name:'RTT (ms)'},
    series: [{type:'line', data: recs.map(r => r.rtt), smooth: true,
      lineStyle: {color:'#4da3ff'}, itemStyle: {color:'#4da3ff'},
      areaStyle: {color:'rgba(77,163,255,0.15)'}}]
  });

  // Attack sequence (color blocks per round)
  initChart('chartAttackSeq').setOption({
    tooltip: {trigger:'item', formatter: p => `${p.data[1]}<br>第${p.data[0]}轮`},
    grid: {left: 50, right: 30, top: 20, bottom: 40},
    xAxis: {type:'category', name:'轮次', data: recs.map(r => '#' + r.iteration)},
    yAxis: {type:'category', data: [...new Set(recs.map(r => r.category))]},
    series: [{type:'scatter', symbolSize: 26,
      data: recs.map(r => [r.iteration, r.category]),
      itemStyle: {color: p => colorOf(p.value[1])}}]
  });

  // Detail table
  document.querySelector('#detailTable tbody').innerHTML = recs.map(r => `
    <tr>
      <td>${r.iteration}</td><td>${r.tool}</td>
      <td><span class="tag" style="background:${colorOf(r.category)}22;color:${colorOf(r.category)}">${r.category}</span></td>
      <td>${r.dst_ip || '-'}</td><td>${r.dst_port ?? '-'}</td>
      <td>${r.pps ?? '-'}</td><td>${r.rate ?? '-'}</td>
      <td>${r.duration_s ?? '-'}</td><td>${r.packet_size ?? '-'}</td>
      <td>${r.rtt ?? '-'}</td><td class="muted">${(r.description || '').slice(0, 60)}</td>
    </tr>`).join('');

  setTimeout(resizeAll, 50);
}

// ── Boot ─────────────────────────────────────────────────────────
renderKpi();
renderCategoryChart();
renderEffectChart();
renderTargetChart();
renderScatterChart();
renderSessionList();
window.addEventListener('resize', resizeAll);
</script>
</body>
</html>
"""


# ── Rendering ────────────────────────────────────────────────────

def render_html(records: list[dict], sessions: list[dict]) -> str:
    data = {"records": records, "sessions": sessions}
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return _HTML_TEMPLATE.replace("__DATA_JSON__", data_json)


def load_records(log_path: Path) -> list[dict]:
    records: list[dict] = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate attack history HTML report")
    parser.add_argument("--log", default="data/experiment.jsonl",
                        help="Path to the JSONL experiment log (default: data/experiment.jsonl)")
    parser.add_argument("--out", default="output/attack_history.html",
                        help="Output HTML path (default: output/attack_history.html)")
    args = parser.parse_args()

    log_path = Path(args.log)
    if not log_path.exists():
        raise SystemExit(f"log file not found: {log_path}")

    raw = load_records(log_path)
    records = [normalize_record(r) for r in raw]
    sessions = build_session_summary(split_sessions(records))

    html = render_html(records, sessions)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    print(f"生成报告: {out_path}")
    print(f"  记录数: {len(records)}")
    print(f"  会话数: {len(sessions)}")


if __name__ == "__main__":
    main()
