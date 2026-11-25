#!/usr/bin/env python3
"""Generate an attack-detail summary (HTML / JSON) from a daily agent log.

Reads ``data/agent-YYYY-MM-DD.log`` (the verbose LLM I/O log) and extracts each
live ``run_python_file`` execution's ping metrics (``rtt_during``) and HTTP
business-health metrics (``http_during``), plus best-effort download-size
heuristics from the script's stdout. Also captures the ping/HTTP baseline from
the first ``read_ping_stats`` / ``read_http_stats`` results.

Log format note (see src/main.py ``VerboseCallback``): the ``  [N] tool:`` line
is truncated to 500 chars (INFO), but the ``    content:`` line is the full
untruncated content (DEBUG) — this script parses the latter.

Usage:
    uv run python scripts/generate_attack_summary.py [LOG] [--json] [--out OUT.html]
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"
_OUTPUT_DIR = _PROJECT_ROOT / "output"

_CONTENT_PREFIX = "    content: "
_RUN_RE = re.compile(r"^TRex script (\S+) (succeeded|timed out|failed)")
_THREADS_RE = re.compile(r"download threads started: (\d+)")
_MB_RE = re.compile(r"approx_MB_downloaded: ([\d.]+)")
_DL_STATS_RE = re.compile(r"(?:DL STATS|SUMMARY): (\{.*?\})")
# AI thinking: DeepSeek reasoning_content lives in the `kwargs={...}` line; the
# LLM's formal output (Chinese diagnosis/reflection) lives in the `  [N] ai:` line.
_REASONING_RE = re.compile(r'"reasoning_content"\s*:\s*"((?:[^"\\]|\\.)*)"')
_AI_RE = re.compile(r"^\s+\[\d+\]\s+ai:\s*(.*)$")


def _latest_daily_log() -> Path:
    logs = sorted(_DATA_DIR.glob("agent-20*.log"))
    if not logs:
        raise SystemExit("no data/agent-YYYY-MM-DD.log found under data/")
    return logs[-1]


def _classify(d: dict) -> str | None:
    """Classify a tool-result dict by shape. Returns a category or None."""
    if d.get("mode") == "live":
        return "attack"
    if d.get("monitor_active"):
        return "http_baseline" if "url" in d else "ping_baseline"
    return None


def _parse_stdout(stdout: str) -> dict:
    """Best-effort extraction of download-size hints from free-form stdout."""
    info: dict = {}
    m = _THREADS_RE.search(stdout)
    if m:
        info["threads"] = int(m.group(1))
    m = _MB_RE.search(stdout)
    if m:
        info["mb_downloaded"] = float(m.group(1))
    m = _DL_STATS_RE.search(stdout)
    if m:
        try:
            stats = ast.literal_eval(m.group(1))
            for key in ("bytes", "ok", "err", "reqs", "errors"):
                if key in stats:
                    info[key] = stats[key]
        except (ValueError, SyntaxError):
            pass
    return info


def _rtt(d: dict) -> dict:
    rtt = d.get("rtt_during") or {}
    return {
        "avg_ms": rtt.get("avg_rtt_ms"),
        "max_ms": rtt.get("max_rtt_ms"),
        "loss_pct": rtt.get("loss_pct"),
    }


def _http(d: dict) -> dict:
    h = d.get("http_during") or {}
    return {
        "success_rate": h.get("success_rate"),
        "ttfb_ms": h.get("avg_ttfb_ms"),
        "five_xx_rate": h.get("five_xx_rate"),
    }


def _rtt_samples(d: dict) -> list:
    """攻击窗口内的 ping 探针时间序列（每个 {ts, rtt_ms, sent, received}）。"""
    rtt = d.get("rtt_during") or {}
    return rtt.get("samples") or []


def _http_samples(d: dict) -> list:
    """攻击窗口内的 HTTP 请求时间序列（每个 {ts, ttfb_ms, total_ms, status_code, success, error_type}）。"""
    h = d.get("http_during") or {}
    return h.get("samples") or []


def _decode_reasoning(raw: str) -> str:
    """把 kwargs 里 JSON 转义的 reasoning_content 还原为可读文本。"""
    try:
        return json.loads('"' + raw + '"')
    except (json.JSONDecodeError, ValueError):
        return raw


def _decode_ai(raw: str) -> str:
    """把 ai 行里的 \\n 转义还原为换行，并去掉 tool_calls= 后缀。"""
    text = re.split(r"\s*tool_calls=", raw, maxsplit=1)[0]
    return text.replace("\\n", "\n").strip()


def _summarize(text: str | None, limit: int) -> str:
    """截断到 limit 字符的简略版；空则「—」。"""
    if not text:
        return "—"
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "…"


def parse_log(path: Path) -> dict:
    """Parse a daily agent log into baseline + per-attack records.

    Also captures each attack's AI thinking (the ``reasoning_content`` emitted
    right before its ``run_python_file`` call) and reflection (the ``ai:``
    message right after its result).
    """
    baseline_ping: dict | None = None
    baseline_http: dict | None = None
    attacks: list[dict] = []
    last_script: str | None = None
    current_reasoning: str | None = None
    pending_idx: int | None = None

    with open(path, encoding="utf-8") as f:
        for line in f:
            # AI thinking（reasoning_content in kwargs line）
            m = _REASONING_RE.search(line)
            if m:
                current_reasoning = _decode_reasoning(m.group(1))
                continue

            # AI reflection（ai: message）
            m = _AI_RE.match(line)
            if m:
                ai_text = _decode_ai(m.group(1))
                if pending_idx is not None and ai_text:
                    attacks[pending_idx]["reflection"] = ai_text
                    pending_idx = None
                continue

            # script name marker
            m = _RUN_RE.match(line)
            if m:
                last_script = m.group(1)
                continue

            if not line.startswith(_CONTENT_PREFIX):
                continue
            payload = line[len(_CONTENT_PREFIX):].strip()
            try:
                d = json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(d, dict):
                continue

            kind = _classify(d)
            if kind == "ping_baseline" and baseline_ping is None:
                baseline_ping = {
                    "avg_ms": d.get("avg_rtt_ms"),
                    "max_ms": d.get("max_rtt_ms"),
                    "loss_pct": d.get("loss_pct"),
                }
            elif kind == "http_baseline" and baseline_http is None:
                baseline_http = {
                    "success_rate": d.get("success_rate"),
                    "ttfb_ms": d.get("avg_ttfb_ms"),
                    "five_xx_rate": d.get("five_xx_rate"),
                }
            elif kind == "attack":
                attacks.append({
                    "filename": last_script,
                    "elapsed_s": d.get("elapsed_s"),
                    "returncode": d.get("returncode"),
                    "error": d.get("error"),
                    "ping": _rtt(d),
                    "http": _http(d),
                    "size": _parse_stdout(d.get("stdout") or ""),
                    "reasoning": current_reasoning,
                    "reflection": None,
                    "rtt_samples": _rtt_samples(d),
                    "http_samples": _http_samples(d),
                })
                pending_idx = len(attacks) - 1

    return {
        "baseline_ping": baseline_ping,
        "baseline_http": baseline_http,
        "attacks": attacks,
    }


# ── HTML rendering ─────────────────────────────────────────────────

def _fmt(v, nd: int = 3) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{nd}f}".rstrip("0").rstrip(".")
    return str(v)


def _pct(v) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.0f}%"


def _size_str(size: dict) -> str:
    parts = []
    if "threads" in size:
        parts.append(f"{size['threads']} 线程")
    if "mb_downloaded" in size:
        parts.append(f"{size['mb_downloaded']:.1f} MB")
    if "bytes" in size:
        parts.append(f"{size['bytes']:,} B")
    return " · ".join(parts) if parts else "—"


_CSS = """
  :root {
    --bg:#0d1017; --surface:#141824; --surface2:#1a2030; --line:#252c3d;
    --fg:#e7ebf2; --fg-muted:#9aa6b8; --fg-faint:#66707f; --accent:#e3a83c;
    --accent-soft:rgba(227,168,60,.14); --ok:#4cc38a; --bad:#e5695b;
    --font-display:"Space Grotesk",system-ui,sans-serif;
    --font-body:"Inter",system-ui,sans-serif;
    --font-mono:"JetBrains Mono",ui-monospace,monospace;
    color-scheme:dark;
  }
  @media (prefers-color-scheme:light){ :root:not([data-theme="dark"]){
    --bg:#f4f6fa; --surface:#fff; --surface2:#edf0f6; --line:#dde3ec;
    --fg:#1a2029; --fg-muted:#566070; --fg-faint:#8b94a3; --accent:#a86f14;
    --accent-soft:rgba(168,111,20,.12); --ok:#1f8a5b; --bad:#c24435;
    color-scheme:light;
  }}
  :root[data-theme="light"]{
    --bg:#f4f6fa; --surface:#fff; --surface2:#edf0f6; --line:#dde3ec;
    --fg:#1a2029; --fg-muted:#566070; --fg-faint:#8b94a3; --accent:#a86f14;
    --accent-soft:rgba(168,111,20,.12); --ok:#1f8a5b; --bad:#c24435;
    color-scheme:light;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);font-family:var(--font-body);
       line-height:1.55;padding:44px 16px 72px}
  .wrap{max-width:1120px;margin:0 auto}
  .eyebrow{font-family:var(--font-mono);font-size:12px;letter-spacing:.12em;
           text-transform:uppercase;color:var(--accent);margin:0 0 10px}
  h1{font-family:var(--font-display);font-size:32px;line-height:1.1;
     letter-spacing:-.02em;margin:0 0 8px}
  .lede{color:var(--fg-muted);font-size:14px;margin:0 0 24px;max-width:70ch}
  .tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:0 0 28px}
  .tile{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
  .tile .k{font-size:11px;letter-spacing:.04em;color:var(--fg-muted);
           text-transform:uppercase;margin-bottom:8px}
  .tile .v{font-family:var(--font-mono);font-size:24px;font-weight:500;
           font-variant-numeric:tabular-nums;letter-spacing:-.02em;line-height:1.1}
  .tile .v small{font-size:14px;color:var(--fg-muted);font-weight:400}
  .tile .s{font-size:12px;color:var(--fg-faint);margin-top:6px}
  .tile.accent{border-color:var(--accent-soft)}
  .tile.accent .v{color:var(--accent)}
  .section-head{display:flex;align-items:baseline;justify-content:space-between;
                gap:12px;flex-wrap:wrap;margin:0 0 12px}
  .section-head h2{font-family:var(--font-display);font-size:19px;margin:0;letter-spacing:-.01em}
  .section-head .legend{font-size:12px;color:var(--fg-faint)}
  .table-scroll{overflow-x:auto;border:1px solid var(--line);border-radius:14px}
  table{border-collapse:collapse;width:100%;min-width:840px;font-size:13px}
  thead th{font-family:var(--font-mono);font-size:11px;text-transform:uppercase;
           letter-spacing:.06em;color:var(--fg-muted);text-align:left;
           padding:11px 14px;background:var(--surface2);border-bottom:1px solid var(--line);
           position:sticky;top:0}
  tbody td{padding:11px 14px;border-bottom:1px solid var(--line);vertical-align:top;
           background:var(--surface)}
  tbody tr:last-child td{border-bottom:none}
  tbody tr:hover td{background:var(--surface2)}
  .fn{font-family:var(--font-mono);color:var(--accent)}
  .num{font-family:var(--font-mono);font-variant-numeric:tabular-nums}
  tr.diag td{color:var(--fg-faint)}
  tr.diag td.fn{color:var(--fg-muted)}
  .cards{display:flex;flex-direction:column;gap:14px}
  .card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
  .card-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-bottom:10px;flex-wrap:wrap}
  .card-head .fn{font-family:var(--font-mono);color:var(--accent);font-size:14px}
  .card-head .meta{font-family:var(--font-mono);font-size:12px;color:var(--fg-faint);font-variant-numeric:tabular-nums}
  .card-metrics{display:flex;gap:24px;flex-wrap:wrap;margin-bottom:4px}
  .card-metrics .m .k{font-size:11px;color:var(--fg-muted);text-transform:uppercase;letter-spacing:.04em;margin-right:6px}
  .card-metrics .m .v{font-family:var(--font-mono);font-size:13px;font-variant-numeric:tabular-nums}
  .think,.reflect{font-size:13px;line-height:1.5;margin-top:8px}
  .think .tag,.reflect .tag{display:inline-block;font-size:11px;font-weight:600;letter-spacing:.04em;padding:2px 8px;border-radius:5px;margin-right:8px;vertical-align:top}
  .think .tag{background:rgba(90,140,255,.16);color:#7aa2ff}
  .reflect .tag{background:var(--accent-soft);color:var(--accent)}
  .think .txt,.reflect .txt{color:var(--fg-muted)}
  tr.clickable{cursor:pointer}
  tr.clickable:hover td{background:var(--surface2)}
  .back{padding:6px 14px;border-radius:6px;cursor:pointer;border:1px solid var(--line);
        background:var(--surface);color:var(--fg);font-size:13px;margin-bottom:16px}
  .back:hover{background:var(--surface2)}
  .charts{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}
  .panel{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:14px}
  .panel h2{font-family:var(--font-display);font-size:15px;margin:0 0 10px}
  .chart{width:100%;height:300px}
  @media(max-width:760px){.tiles{grid-template-columns:repeat(2,1fr)}}
  @media(max-width:420px){.tiles{grid-template-columns:1fr}}
  @media(max-width:900px){.charts{grid-template-columns:1fr}}
"""


def render_html(result: dict, source: Path) -> str:
    base_ping = result["baseline_ping"] or {}
    base_http = result["baseline_http"] or {}
    attacks = result["attacks"]

    rtt_vals = [a["ping"]["avg_ms"] for a in attacks if a["ping"]["avg_ms"] is not None]
    mb_vals = [
        (a["size"].get("mb_downloaded"), a["size"].get("threads"))
        for a in attacks if a["size"].get("mb_downloaded") is not None
    ]
    max_mb = max((m for m, _ in mb_vals), default=None)
    max_threads = next((t for m, t in mb_vals if m == max_mb), None) if max_mb is not None else None

    rtt_range = f"{rtt_vals[0]:.3f}–{rtt_vals[-1]:.3f}" if rtt_vals else "—"
    peak = f"{max_mb:.1f}" if max_mb is not None else "—"

    tiles = (
        f'<div class="tile accent"><div class="k">Ping RTT 基线</div>'
        f'<div class="v">{_fmt(base_ping.get("avg_ms"))}<small> ms</small></div>'
        f'<div class="s">丢包 {_pct(base_ping.get("loss_pct"))}</div></div>'
        f'<div class="tile"><div class="k">Live 执行</div>'
        f'<div class="v">{len(attacks)}</div>'
        f'<div class="s">{len(rtt_vals)} 次有 ping 指标</div></div>'
        f'<div class="tile"><div class="k">RTT 全程范围</div>'
        f'<div class="v">{rtt_range}<small> ms</small></div>'
        f'<div class="s">点击行看逐点曲线</div></div>'
        f'<div class="tile"><div class="k">峰值下载</div>'
        f'<div class="v">{peak}<small> MB</small></div>'
        f'<div class="s">{max_threads or "—"} 线程</div></div>'
    )

    data = {"attacks": attacks}
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")

    html = f"""<!doctype html>
<meta charset="utf-8">
<title>攻击明细</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Space+Grotesk:wght@500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>{_CSS}</style>
<div class="wrap">
  <p class="eyebrow">闭环网络实验 · 攻击明细</p>
  <h1>TRex 攻击复盘</h1>
  <p class="lede">来源 <b>{source.name}</b> · 点击任意一行下钻，看该轮 AI 思考/反思 + RTT/HTTP 逐点动态曲线。</p>

  <div id="overviewView">
    <div class="tiles">{tiles}</div>
    <div class="section-head">
      <h2>每次执行明细</h2>
      <span class="legend">点击行下钻 · Ping 单位 ms · HTTP 为成功率/TTFB/5xx</span>
    </div>
    <div class="table-scroll">
      <table>
        <thead><tr>
          <th>#</th><th>脚本</th><th>时长</th><th>Ping avg / max / 丢包</th><th>HTTP 成功率 / TTFB / 5xx</th><th>规模</th>
        </tr></thead>
        <tbody id="attackBody"></tbody>
      </table>
    </div>
  </div>

  <div id="detailView" style="display:none">
    <button class="back" onclick="showOverview()">← 返回总览</button>
    <div id="detailHead"></div>
    <div class="charts">
      <div class="panel"><h2>RTT 动态曲线</h2><div id="chartRtt" class="chart"></div></div>
      <div class="panel"><h2>HTTP 动态曲线</h2><div id="chartHttp" class="chart"></div></div>
    </div>
  </div>
</div>

<script>
const DATA = {data_json};
const charts = {{}};
function initChart(id) {{ if(!charts[id]) charts[id] = echarts.init(document.getElementById(id)); return charts[id]; }}
function resizeAll() {{ Object.values(charts).forEach(c => c.resize()); }}

function fmt(v, nd) {{
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') return v.toFixed(nd === undefined ? 3 : nd).replace(/\\.0+$/, '').replace(/(\\.\\d*?)0+$/, '$1');
  return String(v);
}}
function pct(v) {{ return v == null ? '—' : Math.round(v * 100) + '%'; }}
function sizeStr(s) {{
  const parts = [];
  if (s.threads) parts.push(s.threads + ' 线程');
  if (s.mb_downloaded != null) parts.push(s.mb_downloaded.toFixed(1) + ' MB');
  if (s.bytes != null) parts.push(s.bytes.toLocaleString() + ' B');
  return parts.length ? parts.join(' · ') : '—';
}}

// 总览：攻击列表
function renderList() {{
  const tb = document.getElementById('attackBody');
  tb.innerHTML = DATA.attacks.map((a, i) => {{
    const p = a.ping || {{}}, h = a.http || {{}};
    const diag = p.avg_ms == null;
    return `<tr class="clickable" onclick="showDetail(${{i}})">
      <td class="num">${{i + 1}}</td>
      <td class="fn">${{a.filename || '—'}}</td>
      <td class="num">${{fmt(a.elapsed_s, 1)}}s</td>
      <td class="num">${{fmt(p.avg_ms)}} / ${{fmt(p.max_ms)}} / ${{pct(p.loss_pct)}}</td>
      <td class="num">${{pct(h.success_rate)}} / ${{fmt(h.ttfb_ms)}} / ${{pct(h.five_xx_rate)}}</td>
      <td>${{sizeStr(a.size || {{}})}}</td>
    </tr>`;
  }}).join('');
}}

// 详情：思考/反思 + 曲线
function showDetail(i) {{
  const a = DATA.attacks[i];
  document.getElementById('overviewView').style.display = 'none';
  document.getElementById('detailView').style.display = 'block';

  const think = (a.reasoning || '').slice(0, 400);
  const refl = (a.reflection || '').slice(0, 600);
  document.getElementById('detailHead').innerHTML = `
    <div class="section-head"><h2>#${{i + 1}} ${{a.filename || '—'}}</h2>
      <span class="legend">${{fmt(a.elapsed_s, 1)}}s${{a.returncode ? ' · 退出码 ' + a.returncode : ''}}</span></div>
    <div class="think"><span class="tag">思考</span><span class="txt">${{think || '—'}}</span></div>
    <div class="reflect"><span class="tag">反思</span><span class="txt">${{refl || '—'}}</span></div>`;

  renderRtt(a);
  renderHttp(a);
  setTimeout(resizeAll, 50);
}}

function showOverview() {{
  document.getElementById('overviewView').style.display = 'block';
  document.getElementById('detailView').style.display = 'none';
  setTimeout(resizeAll, 50);
}}

function renderRtt(a) {{
  const samples = a.rtt_samples || [];
  const ch = initChart('chartRtt');
  if (!samples.length) {{ ch.clear(); return; }}
  const t0 = samples[0].ts;
  ch.setOption({{
    tooltip: {{trigger:'axis', formatter: ps => {{
      const s = samples[ps[0].dataIndex];
      return `RTT ${{fmt(s.rtt_ms)}} ms<br>sent ${{s.sent}} / recv ${{s.received}}`;
    }}}},
    grid: {{left:50, right:20, top:20, bottom:40}},
    xAxis: {{type:'value', name:'相对时间 (s)'}},
    yAxis: {{type:'value', name:'RTT (ms)'}},
    series: [{{type:'line', data: samples.map(s => [s.ts - t0, s.rtt_ms]), smooth:true,
      lineStyle:{{color:'#4da3ff'}}, itemStyle:{{color:'#4da3ff'}}, areaStyle:{{color:'rgba(77,163,255,.12)'}}}}]
  }});
}}

function httpColor(s) {{
  if (s.success === false) return '#8892a6';           // 失败（超时/连接拒绝）
  if (s.status_code != null && s.status_code >= 500) return '#e5695b';  // 5xx
  return '#4cc38a';                                    // 成功
}}
function renderHttp(a) {{
  const samples = a.http_samples || [];
  const ch = initChart('chartHttp');
  if (!samples.length) {{ ch.clear(); return; }}
  const t0 = samples[0].ts;
  const make = (key) => samples.map(s => ({{
    value: [s.ts - t0, s[key]],
    itemStyle: {{color: httpColor(s)}},
    status_code: s.status_code, error_type: s.error_type, success: s.success,
  }}));
  ch.setOption({{
    tooltip: {{trigger:'item', formatter: p => {{
      const d = p.data;
      return `${{p.seriesName}} ${{fmt(d.value[1])}} ms<br>status ${{d.status_code ?? '—'}}${{d.error_type ? ' · ' + d.error_type : ''}}`;
    }}}},
    grid: {{left:50, right:20, top:20, bottom:40}},
    xAxis: {{type:'value', name:'相对时间 (s)'}},
    yAxis: {{type:'value', name:'ms'}},
    legend: {{textStyle:{{color:'#9aa6b8'}}}},
    series: [
      {{name:'TTFB', type:'line', data: make('ttfb_ms'), showSymbol:true}},
      {{name:'Total', type:'line', data: make('total_ms'), showSymbol:true}},
    ]
  }});
}}

renderList();
window.addEventListener('resize', resizeAll);
</script>
</body>
</html>
"""
    return html


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate an attack-detail summary from a daily agent log.")
    ap.add_argument("log", nargs="?", help="path to data/agent-YYYY-MM-DD.log (default: latest)")
    ap.add_argument("--json", action="store_true", help="print structured JSON instead of HTML")
    ap.add_argument("--out", help="output HTML path (default: output/attack_summary_<date>.html)")
    args = ap.parse_args()

    path = Path(args.log) if args.log else _latest_daily_log()
    result = parse_log(path)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return

    html = render_html(result, path)
    if args.out:
        out = Path(args.out)
    else:
        stem = path.stem  # agent-2026-11-24
        date = stem[len("agent-"):] if stem.startswith("agent-") else stem
        out = _OUTPUT_DIR / f"attack_summary_{date}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({len(result['attacks'])} attacks)")


if __name__ == "__main__":
    main()
