"""One-off migration: normalize legacy ``data/experiment.jsonl`` into the canonical log schema.

What it does
------------
1. Splits rows into runs — a new run starts whenever ``iteration`` resets
   (each experiment run re-counts from 1), matching the session logic of
   ``scripts/generate_history_report.py``.
2. Infers the attack tool from the param shape when ``params.tool`` is
   missing (167 of 526 legacy rows).
3. Normalizes every row through ``src.tools.log_tool.canonicalize_entry``:
   alias spellings → canonical names, measured outcomes stripped into
   ``results``, unknown keys preserved under ``params.extras``.
4. Writes the result next to the original — the input file is NEVER touched.

Usage:
    uv run python scripts/normalize_experiment_log.py \
        [data/experiment.jsonl] [data/experiment.normalized.jsonl]
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.tools.log_tool import canonicalize_entry  # noqa: E402

# Fields that only appear in rows the LLM fabricated (not any registered tool).
_HALLUCINATION_KEYS = {
    "conn_per_sec", "bytes_received", "dl_bytes", "dl_threads", "dl_err",
    "dl_conn", "syn_pps", "syn_sent", "udp_pkts", "egress_gbps", "combined",
    "conn", "flood", "pct", "tx_pps",
}

_PKTGEN_LIKE_KEYS = {"pktSize", "rate", "dport", "duration_ms", "duration"}
_MIXED_KEYS = {"streams", "traffic_type", "traffic_spec", "traffic_spec_json", "type"}
_SCAPY_KEYS = {"packet_size", "flow_count", "iat_jitter_ms", "dst_port", "effective_pps"}
_TREX_KEYS = {"pkt_size", "pps_per_port", "tx_gbps", "port_util_pct",
              "attack_type", "stream_mix", "src_ip_range"}


def infer_tool(params: dict) -> str | None:
    """Guess the attack tool from the param shape (legacy rows without tool)."""
    keys = set(params or {})
    if "sequences" in keys:
        return "pktgen_packet_sequence"
    if "scan_field" in keys:
        return "pktgen_range_scan"
    if "arp_type" in keys:
        return "pktgen_arp_flood"
    if "tcp_flags" in keys or "flags" in keys:
        return "pktgen_tcp_flood"

    proto = str(params.get("protocol") or params.get("proto") or "").lower()
    if keys & _PKTGEN_LIKE_KEYS:
        if "icmp" in proto:
            return "pktgen_icmp_flood"
        if "tcp" in proto or "syn" in proto:
            return "pktgen_tcp_flood"
        if "arp" in proto:
            return "pktgen_arp_flood"
        return "pktgen_udp_flood"

    if keys & _TREX_KEYS:
        return "trex_stl"
    if keys & _MIXED_KEYS:
        return "mixed_traffic_send"
    if keys & _SCAPY_KEYS:
        return "traffic_send"
    if keys & _HALLUCINATION_KEYS:
        return None  # LLM-fabricated row; no real tool matches
    return None


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def split_runs(rows: list[dict]) -> list[list[dict]]:
    """Split rows into runs on iteration reset (each run re-counts from 1)."""
    runs: list[list[dict]] = []
    prev_iter: int | None = None
    for row in rows:
        iteration = row.get("iteration")
        if prev_iter is None or (
            isinstance(iteration, int) and iteration <= prev_iter
        ):
            runs.append([])
        runs[-1].append(row)
        if isinstance(iteration, int):
            prev_iter = iteration
    return runs


def run_id_for(run: list[dict], index: int) -> str:
    ts = _parse_ts(run[0].get("timestamp"))
    stamp = ts.strftime("%Y%m%dT%H%M%S") if ts else f"run{index:03d}"
    return f"legacy-{stamp}-{index + 1:02d}"


def normalize_file(input_path: Path, output_path: Path) -> dict[str, Any]:
    rows: list[dict] = []
    bad_lines = 0
    for lineno, line in enumerate(input_path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            bad_lines += 1
            print(f"  [warn] skipping unparseable line {lineno}")

    runs = split_runs(rows)

    inferred = Counter()
    explicit = Counter()
    unknown = 0
    out_lines: list[str] = []

    for idx, run in enumerate(runs):
        run_id = run_id_for(run, idx)
        for row in run:
            params = row.get("params")
            if not isinstance(params, dict):
                params = {}
            tool = params.get("tool")
            if tool:
                explicit[tool] += 1
            else:
                tool = infer_tool(params)
                if tool:
                    inferred[tool] += 1
                else:
                    unknown += 1

            entry = {
                "run_id": run_id,
                "iteration": row.get("iteration"),
                "tool": tool,
                "params": params,
                "rtt": row.get("rtt"),
                "loss": row.get("loss"),
                "timestamp": row.get("timestamp"),
            }
            out_lines.append(json.dumps(canonicalize_entry(entry), ensure_ascii=False))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    return {
        "rows": len(rows),
        "bad_lines": bad_lines,
        "runs": len(runs),
        "explicit_tool": dict(explicit),
        "inferred_tool": dict(inferred),
        "unknown_tool": unknown,
        "output": output_path,
    }


def main() -> None:
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/experiment.jsonl")
    output_path = (
        Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/experiment.normalized.jsonl")
    )

    if not input_path.exists():
        print(f"Input not found: {input_path}")
        sys.exit(1)

    report = normalize_file(input_path, output_path)

    print(f"Normalized {report['rows']} rows → {report['output']}")
    print(f"  runs detected (iteration reset): {report['runs']}")
    print(f"  bad lines skipped: {report['bad_lines']}")
    print(f"  rows with explicit params.tool: {sum(report['explicit_tool'].values())}")
    print(f"  tool inferred from param shape:  {sum(report['inferred_tool'].values())}")
    for tool, n in sorted(report["inferred_tool"].items(), key=lambda kv: -kv[1]):
        print(f"    {tool}: {n}")
    print(f"  rows left as tool=unknown (LLM-fabricated params): {report['unknown_tool']}")


if __name__ == "__main__":
    main()
