"""CLI entry point for the closed-loop network experiment agent."""
import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger("agent")

# Console preview length for message content in [LLM INPUT] lines.
# Full untruncated content always goes to data/agent.log at DEBUG.
MSG_PREVIEW_LEN = 500

# Ensure the project root is on sys.path so `src` is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.graph import build_graph  # noqa: E402
from src.agent.state import (  # noqa: E402
    apply_observation,
    check_stop_condition,
)
from src.pktgen.adapter import get_pktgen_host, get_pktgen_port  # noqa: E402
from src.trex.config import get_trex_host, get_trex_port, get_trex_scripts_dir  # noqa: E402
from src.tools.log_tool import generate_run_id  # noqa: E402
from src.tools.monitor_lifecycle import (  # noqa: E402
    start_experiment_monitors,
    stop_experiment_monitors,
)
from src.tools.ping_rtt_tool import is_allowlisted  # noqa: E402
from langgraph.types import Command  # noqa: E402
from langchain_core.callbacks import BaseCallbackHandler  # noqa: E402
from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402

# ── Callback: log LLM I/O via logging module ────────────────────────
class VerboseCallback(BaseCallbackHandler):
    """Log LLM prompts and responses. Level: INFO=tool calls/structure, DEBUG=full content."""

    def __init__(self):
        super().__init__()
        self._last_msg_count = 0

    @staticmethod
    def _flat_tool_calls(msg) -> list[str]:
        tc_list = getattr(msg, "tool_calls", None) or []
        return [tc.get("name", "?") for tc in tc_list]

    def on_chat_model_start(self, serialized, messages, **kwargs):
        msgs = messages[0]
        last = self._last_msg_count
        new_msgs = msgs[last:]
        logger.info("=" * 60)
        logger.info("[LLM INPUT] 总消息: %d, 本轮新增: %d", len(msgs), len(new_msgs))
        for i, msg in enumerate(new_msgs):
            idx = last + i
            role = getattr(msg, "type", "unknown")
            raw_content = str(getattr(msg, "content", ""))
            content_preview = raw_content[:MSG_PREVIEW_LEN].replace("\n", "\\n")
            if len(raw_content) > MSG_PREVIEW_LEN:
                content_preview += f"… (+{len(raw_content) - MSG_PREVIEW_LEN} chars, see data/agent.log)"
            tc = self._flat_tool_calls(msg)
            extra_info = f" tool_calls={tc}" if tc else ""
            logger.info("  [%d] %s: %s %s", idx, role, content_preview, extra_info)
            logger.debug("    content: %s", str(getattr(msg, "content", "")))
            extra = getattr(msg, "additional_kwargs", None) or {}
            if extra:
                logger.debug("    kwargs=%s", json.dumps(extra, ensure_ascii=False, default=str))
        self._last_msg_count = len(msgs)

    def on_chat_model_end(self, response, **kwargs):
        msg = response.generations[0][0].message
        tc = self._flat_tool_calls(msg)
        logger.info("[LLM OUTPUT] tool_calls=%s", tc)
        for t in getattr(msg, "tool_calls", None) or []:
            logger.debug("  args: %s", json.dumps(t.get("args", {}), ensure_ascii=False)[:MSG_PREVIEW_LEN])
        content = getattr(msg, "content", "")
        if content:
            logger.debug("  content: %s", content[:MSG_PREVIEW_LEN])
        extra = getattr(msg, "additional_kwargs", None) or {}
        if extra:
            logger.debug("  kwargs=%s", json.dumps(extra, ensure_ascii=False, default=str)[:MSG_PREVIEW_LEN])
        logger.info("=" * 60)

    # def on_tool_start(self, serialized, input_str, **kwargs):
    #     logger.info("[TOOL] %s — start", serialized.get("name", "?"))

    # def on_tool_end(self, output, **kwargs):
    #     logger.info("[TOOL] done")


CONFIG_PATH = Path(__file__).resolve().parent.parent / "experiment.json"
HTTP_PROBE_PATH = Path(__file__).resolve().parent.parent / "http_probe.json"

DEFAULTS: dict = {
    "target_ip": "10.99.80.160",
    "pcap_path": "",
    "log_path": "data/experiment.jsonl",
    "max_iters": 20,
    "no_improve_limit": 5,
}


# Config sections that a named profile may override (nested, deep-merged).
_SECTION_KEYS = ("attack", "pktgen", "trex")


def _read_config_file() -> dict:
    """Read experiment.json, returning {} on missing file or parse error."""
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _apply_profile(cfg: dict, data: dict, profile: str) -> dict:
    """Overlay a named profile (data['profiles'][profile]) onto cfg immutably.

    Scalar keys are replaced; nested sections are shallow-merged so a profile
    only needs to list the keys it changes.
    """
    profiles = data.get("profiles", {})
    if profile not in profiles:
        available = ", ".join(sorted(profiles)) or "(none)"
        raise SystemExit(f"未知 profile: {profile!r}，可用: {available}")
    overrides = profiles[profile]
    result = dict(cfg)
    for key in DEFAULTS:
        if key in overrides:
            result[key] = overrides[key]
    for key in _SECTION_KEYS:
        if key in overrides:
            result[key] = {**(result.get(key) or {}), **overrides[key]}
    return result


def _load_config_defaults(profile: str | None = None) -> dict:
    """Load experiment defaults from config, optionally overlaid with a named profile."""
    data = _read_config_file()
    merged = dict(DEFAULTS)
    for key in DEFAULTS:
        if key in data:
            merged[key] = data[key]
    for key in _SECTION_KEYS:
        if key in data:
            merged[key] = dict(data[key])
    if profile:
        merged = _apply_profile(merged, data, profile)
    return merged


def _load_http_probe_config() -> dict:
    """Read http_probe.json (dial-testing config), returning {} on any error."""
    if not HTTP_PROBE_PATH.exists():
        return {}
    try:
        with open(HTTP_PROBE_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _build_http_bodies(cfg: dict) -> list[str]:
    """Expand http_probe.json's accounts + body template into a rotated pool.

    When *cfg* has an ``accounts`` section and ``body`` contains an ``{email}``
    placeholder, generates ``start..end`` (default 1..100) request bodies by
    substituting ``email_prefix{i}{email_suffix}`` and ``password``. Returns an
    empty list otherwise (fixed single-account probing).
    """
    accounts = cfg.get("accounts")
    body = cfg.get("body") or ""
    if not accounts or "{email}" not in body:
        return []
    prefix = accounts.get("email_prefix", "user")
    suffix = accounts.get("email_suffix", "@test.com")
    start = int(accounts.get("start", 1))
    end = int(accounts.get("end", 100))
    password = accounts.get("password", "123456")
    return [
        body.replace("{email}", f"{prefix}{i}{suffix}").replace("{password}", password)
        for i in range(start, end + 1)
    ]


def parse_args() -> argparse.Namespace:
    # Pre-scan --profile so the profile's defaults feed the remaining args' defaults.
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--profile", default=None)
    pre_args, _ = pre_parser.parse_known_args()

    cfg = _load_config_defaults(profile=pre_args.profile)
    parser = argparse.ArgumentParser(
        description="Closed-Loop Network Experiment Agent"
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="命名预设：一键切换整组参数（定义于 experiment.json 的 profiles）",
    )
    parser.add_argument(
        "--target-ip",
        default=cfg["target_ip"],
        help="Target IP for traffic and ping (must be in allowlist)",
    )
    parser.add_argument(
        "--pcap-path",
        default=cfg["pcap_path"],
        help="Path to PCAP/PCAPng file for baseline traffic profiling",
    )
    parser.add_argument(
        "--log-path",
        default=cfg["log_path"],
        help="Path to JSONL experiment log",
    )
    parser.add_argument(
        "--max-iters",
        type=int,
        default=None,
        help="Maximum iterations (default 20; 40 in --trex-explore mode)",
    )
    parser.add_argument(
        "--no-improve-limit",
        type=int,
        default=cfg["no_improve_limit"],
        help="Stop after N consecutive rounds without improvement (default 5)",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        default=False,
        help="自动批准所有 HITL 请求（仅限 dry-run 零流量场景；"
             "与 --pktgen-live/--trex-live 互斥——实发模式必须人工逐次审批）",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Show full untruncated message content on the console (console → DEBUG). "
             "Full content is always written to data/agent.log regardless.",
    )
    # ── Attack parameter defaults ────────────────────────────────────
    attack_cfg = cfg.get("attack", {})
    parser.add_argument(
        "--duration", type=int, default=attack_cfg.get("duration_s", 5),
        help="Attack duration in seconds (default 5)",
    )
    parser.add_argument(
        "--pps", type=int, default=attack_cfg.get("pps", 100),
        help="Packets per second for Scapy tools (default 100)",
    )
    parser.add_argument(
        "--packet-size", type=int, default=attack_cfg.get("packet_size", 64),
        help="Packet payload size in bytes (default 64)",
    )
    parser.add_argument(
        "--flow-count", type=int, default=attack_cfg.get("flow_count", 1),
        help="Number of concurrent flows (default 1)",
    )
    # ── Pktgen-DPDK options ──────────────────────────────────────────
    pktgen_cfg = cfg.get("pktgen", {})
    parser.add_argument(
        "--pktgen-live",
        action="store_true",
        default=False,
        help="Run Pktgen tools in live mode (actually send traffic to Pktgen). "
             "Default is dry-run (compile Lua scripts only).",
    )
    parser.add_argument(
        "--pktgen-host",
        default=None,
        help="Pktgen-DPDK hostname or IP (default from topology.yaml)",
    )
    parser.add_argument(
        "--pktgen-port",
        type=int,
        default=None,
        help="Pktgen-DPDK TCP control port (default from topology.yaml)",
    )
    parser.add_argument(
        "--pktgen-rate", type=float, default=pktgen_cfg.get("rate", 50),
        help="Pktgen rate as percentage 0-100 (default 50)",
    )
    parser.add_argument(
        "--pktgen-duration", type=int, default=pktgen_cfg.get("duration_ms", 10000),
        help="Pktgen duration in milliseconds (default 5000)",
    )
    # ── TRex options ─────────────────────────────────────────────────
    trex_cfg = cfg.get("trex", {})
    parser.add_argument(
        "--trex-live",
        action="store_true",
        default=False,
        help="Run TRex scripts in live mode (actually execute generated Python). "
             "Default is dry-run (write + syntax-check only).",
    )
    parser.add_argument(
        "--trex-host",
        default=None,
        help="TRex server hostname or IP (default from topology.yaml)",
    )
    parser.add_argument(
        "--trex-port",
        type=int,
        default=None,
        help="TRex server RPC port (default from topology.yaml)",
    )
    parser.add_argument(
        "--trex-timeout", type=float, default=trex_cfg.get("timeout_s", 30),
        help="Timeout in seconds for running a TRex script (default 30)",
    )
    parser.add_argument(
        "--trex-explore",
        action="store_true",
        default=False,
        help="TRex attack catalog exploration mode: the agent only generates "
             "attack scripts with Chinese annotations (dry-run, no traffic, no "
             "HITL) and saves the catalog summary to "
             "output/trex_attack_catalog_<timestamp>.md.",
    )
    parser.add_argument(
        "--catalog-target",
        type=int,
        default=10,
        help="Minimum number of attack scripts the agent must generate in "
             "--trex-explore mode (default 10)",
    )
    parser.add_argument(
        "--explore-direction",
        default="",
        help="User-specified exploration direction for --trex-explore mode, "
             "injected into the catalog prompt (free-form text, e.g. "
             '"重点探索DNS放大攻击和TCP SYN洪水")',
    )
    parser.add_argument(
        "--clean-scripts",
        action="store_true",
        default=False,
        help="仅 --trex-explore 生效：启动时清空 trex_scripts/cat_*.py 旧脚本"
             "（绝不动非 cat_ 文件）",
    )
    parser.add_argument(
        "--instruction",
        default="",
        help="用户对本次实验的额外目标/指令（自由文本，注入 user message 和 system prompt）",
    )
    args = parser.parse_args()
    if args.trex_explore and args.trex_live:
        parser.error(
            "--trex-explore 与 --trex-live 互斥：目录探索模式绝不执行流量，"
            "两者不能同时指定"
        )
    if args.catalog_target < 1:
        parser.error(
            f"--catalog-target 必须 ≥ 1（收到 {args.catalog_target}）："
            "目录探索目标脚本数至少为 1"
        )
    # 008-T014/008-1：自动批准不得与任何实发模式组合（禁止无人值守真实流量）
    if args.auto_approve and (args.pktgen_live or args.trex_live):
        parser.error(
            "--auto-approve 与 --pktgen-live/--trex-live 互斥：自动批准仅限 "
            "dry-run（零流量）场景，实发模式必须人工逐次审批"
        )
    if args.max_iters is None:
        args.max_iters = 40 if args.trex_explore else cfg["max_iters"]
    # 攻击抖动默认值（R4：无 CLI 参数；经配置链 attack.iat_jitter_ms /
    # profile 注入，供 _inject_attack_env 使用——配置单一来源）
    args.iat_jitter_ms = int(attack_cfg.get("iat_jitter_ms", 0))
    # ping 监控配置节（003-G-001/G-002：经配置链注入，无 CLI 参数）
    args.ping_monitor = dict(cfg.get("ping_monitor") or {})
    # PCAP 画像配置节（004-T003：经配置链注入，无 CLI 参数）
    args.pcap_profile = dict(cfg.get("pcap_profile") or {})
    # Pktgen 合法源地址配置节（005-T004/D9：经配置链注入，无 CLI 参数；
    # 适配器 T009 消费，覆盖 vendored 默认伪造源 192.168.1.1/24）
    args.pktgen_src_ip = str(pktgen_cfg.get("src_ip") or "")
    # 显式出现的 CLI 参数（004-T016：人工覆盖优先级——CLI > 映射 > 配置默认）
    args._explicit_flags = {
        flag.lstrip("-").replace("-", "_")
        for flag in ("--pps", "--packet-size", "--flow-count", "--duration")
        if any(a == flag or a.startswith(flag + "=") for a in sys.argv[1:])
    }
    return args


def _warn_config_over_limits(args: argparse.Namespace) -> None:
    """008-T011/008-2：配置默认值超限启动警告（字段/配置值/钳制后上限值）。

    逐项比对最终生效参数（已含 profile 覆盖）与宪法上限；超限项输出
    WARNING 到 stderr，**不报错退出**——钳制仍在工具内执行，本层只负责可见性。
    """
    checks = [
        ("attack.pps", getattr(args, "pps", 0), 20000),
        ("attack.duration_s", getattr(args, "duration", 0), 20),
        ("attack.packet_size", getattr(args, "packet_size", 0), 1024),
        ("attack.flow_count", getattr(args, "flow_count", 0), 100),
        ("attack.iat_jitter_ms", getattr(args, "iat_jitter_ms", 0), 20),
        ("pktgen.rate", getattr(args, "pktgen_rate", 0), 100),
        ("pktgen.duration_ms", getattr(args, "pktgen_duration", 0), 60000),
    ]
    for field, value, limit in checks:
        if isinstance(value, (int, float)) and value > limit:
            print(
                f"[配置警告] {field}: 配置值 {value} 超过上限，"
                f"工具内将钳制为 {limit}",
                file=sys.stderr,
            )


def _run_preflight(args: argparse.Namespace) -> None:
    """启动前预检（G3、FR-017、data-model 校验规则，research.md D3）。

    必须在 build_graph 之前调用：目标 IP 必须位于 allowlist（复用
    ``src/tools/ping_rtt_tool.py`` 的 ``is_allowlisted``，不引入第二套
    allowlist 逻辑）、``max_iters ≥ 1``、``no_improve_limit ≥ 1``。
    任一不合规打印明确中文错误并以非零退出码退出，不发起模型请求。
    """
    errors: list[str] = []
    if not is_allowlisted(args.target_ip):
        errors.append(f"目标 IP {args.target_ip!r} 不在 allowlist 中")
    if args.max_iters is None or args.max_iters < 1:
        errors.append(f"max_iters 必须 ≥ 1（当前 {args.max_iters!r}）")
    if args.no_improve_limit is None or args.no_improve_limit < 1:
        errors.append(f"no_improve_limit 必须 ≥ 1（当前 {args.no_improve_limit!r}）")
    if errors:
        for msg in errors:
            print(f"[启动预检失败] {msg}，拒绝启动。", file=sys.stderr)
        sys.exit(1)


def _build_user_message(args: argparse.Namespace) -> str:
    """Build the initial user message with experiment parameters."""
    if args.trex_explore:
        direction_line = (
            f"- 探索方向: {args.explore_direction}\n"
            if args.explore_direction
            else ""
        )
        return (
            "请开始 TRex 攻击能力探索：\n"
            f"- 目标: 枚举并生成 ≥{args.catalog_target} 类攻击脚本（文件名 cat_ 开头）\n"
            + direction_line +
            "- 模式: dry-run，只生成代码与中文注释，不发送任何流量\n"
            "请严格按照系统提示中的探索协议执行（先规划 → 再生成 → 再总结）。"
        )
    instruction_line = (
        f"- 用户指令: {getattr(args, 'instruction', '')}\n"
        if getattr(args, "instruction", "")
        else ""
    )
    pcap_line = (
        f"- PCAP文件路径: {args.pcap_path}\n"
        if args.pcap_path
        else "- PCAP文件路径: 无（使用默认初始参数）\n"
    )
    seed_line = ""
    seeds = getattr(args, "profile_seeds", None)
    if seeds:
        seed_line = (
            f"- 画像映射初始参数: dst_port={seeds['dst_port']}, "
            f"packet_size={seeds['packet_size']}, flow_count={seeds['flow_count']}, "
            f"pps={seeds['pps']}\n"
        )
    return (
        "请开始闭环网络实验：\n"
        + instruction_line +
        f"- 目标IP: {args.target_ip}\n"
        f"- 最大迭代次数: {args.max_iters}\n"
        f"- 无改善停止轮数: {args.no_improve_limit}\n"
        f"- 日志文件路径: {args.log_path}\n"
        + pcap_line
        + seed_line
        + "\n请严格按照系统提示中的实验协议执行。"
        "如果提供了PCAP文件，先用 pcap_profile 工具分析流量特征。"
    )


def _apply_mode_env(args: argparse.Namespace) -> None:
    """Apply env vars specific to the TRex explore mode (forced dry-run)."""
    if args.trex_explore:
        os.environ["TREX_DRY_RUN"] = "true"
        os.environ["CATALOG_TARGET"] = str(args.catalog_target)
        if args.explore_direction:
            os.environ["EXPLORE_DIRECTION"] = args.explore_direction


def _apply_trex_l2_env(trex_cfg: dict) -> None:
    """把 experiment.json 的 trex L2 事实注入 env（缺键不动，交由 config.py 回退）。"""
    for key in ("dst_mac", "src_mac", "start_force"):
        value = trex_cfg.get(key)
        if value is not None:
            os.environ[f"TREX_{key.upper()}"] = str(value)


def _recursion_limit(max_iters: int) -> int:
    """Graph superstep budget — must cover the prompt-level max_iters."""
    return max(25, max_iters + 5)


def _count_syntax_ok_catalog_scripts(scripts_dir: Path) -> int:
    """G1（006-T012）：对 trex_scripts/cat_*.py 逐一 parse-only 语法检查并计数。

    与 write_python_file 的语法检查口径一致（仅解析、绝不执行）；非 cat_
    前缀文件与不可读文件不参与计数。
    """
    if not scripts_dir.is_dir():
        return 0
    passed = 0
    for script in sorted(scripts_dir.glob("cat_*.py")):
        try:
            compile(script.read_text(encoding="utf-8"), str(script), "exec")
        except (SyntaxError, OSError, UnicodeDecodeError, ValueError):
            continue
        passed += 1
    return passed


def _catalog_exit_code(passed: int, catalog_target: int) -> int:
    """G1（006-T012）：达标 → 退出码 0，未达标 → 退出码 1。"""
    return 0 if passed >= catalog_target else 1


def _clean_catalog_scripts(scripts_dir: Path) -> int:
    """G2（006-T013）：仅删除 trex_scripts/cat_*.py（绝不递归、绝不动非 cat_ 文件）。

    返回删除数量；目录不存在返回 0。
    """
    if not scripts_dir.is_dir():
        return 0
    removed = 0
    for script in sorted(scripts_dir.glob("cat_*.py")):
        try:
            script.unlink()
        except OSError:
            continue
        removed += 1
    return removed


def _finalize_catalog_run(
    catalog_path: Path,
    scripts_dir: Path,
    catalog_target: int,
    content: str,
) -> int:
    """G1（006-T012）：落盘目录摘要（FR-021）并返回达标退出码。

    无论达标与否，最终总结均写入 catalog_path（空 content 不写文件，
    与既有边界口径一致）；随后统计语法通过的 cat_*.py 数量：
    ≥ catalog_target → 0，否则 1。
    """
    if content:
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        catalog_path.write_text(str(content), encoding="utf-8")
        print(f"\nAttack catalog saved to: {catalog_path}")
    else:
        print("\n（目录探索最终消息为空，未写入摘要文件）")
    passed = _count_syntax_ok_catalog_scripts(scripts_dir)
    exit_code = _catalog_exit_code(passed, catalog_target)
    print(f"[达标判定] 语法通过的 cat_*.py: {passed}（目标 ≥{catalog_target}）→ 退出码 {exit_code}")
    return exit_code


def _extract_hitl_payload(gs) -> dict | None:
    """Extract the HITL interrupt payload from a StateSnapshot, if any.

    Mirrors backend/experiment.py::_extract_hitl so the CLI operator sees the
    same details (message + params) that the web console shows.
    """
    for task in getattr(gs, "tasks", None) or []:
        for intr in getattr(task, "interrupts", None) or []:
            val = intr.value
            if isinstance(val, dict) and "message" in val:
                return val
    return None


def _extract_observation(messages) -> dict | None:
    """从工具结果消息提取本轮实测观测（G1/D5 硬裁决数据来源）。

    优先 ``rtt_during.avg_rtt_ms`` / ``rtt_during.loss_pct``（003 规格观测
    字段），回退顶层 ``avg_rtt_ms`` / ``loss_pct``（``read_ping_stats`` /
    ``ping_rtt`` 字段）。``covers_attack_window`` 取自 ``observation_window``；
    无该字段（如 read_ping_stats）默认视为可靠。返回归一化观测
    ``{avg_rtt_ms, loss_pct, covers_attack_window}`` 或 None（无可用观测）。
    """
    for msg in reversed(list(messages)):
        content = getattr(msg, "content", "")
        if not isinstance(content, str):
            continue
        stripped = content.strip()
        if not stripped.startswith("{"):
            continue
        try:
            data = json.loads(stripped)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        avg = None
        loss = None
        rtt_during = data.get("rtt_during")
        if isinstance(rtt_during, dict):
            avg = rtt_during.get("avg_rtt_ms")
            loss = rtt_during.get("loss_pct")
        if avg is None and isinstance(data.get("avg_rtt_ms"), (int, float)):
            avg = data["avg_rtt_ms"]
        if loss is None and isinstance(data.get("loss_pct"), (int, float)):
            loss = data["loss_pct"]
        if avg is None:
            continue
        covers = True
        ow = data.get("observation_window")
        if isinstance(ow, dict) and "covers_attack_window" in ow:
            covers = bool(ow["covers_attack_window"])
        return {
            "avg_rtt_ms": float(avg),
            "loss_pct": float(loss or 0.0),
            "covers_attack_window": covers,
        }
    return None


def _inject_attack_env(args: argparse.Namespace) -> None:
    """注入 Scapy 攻击默认值 env（工具在调用时读取；配置单一来源链）。

    含 ATK_IAT_JITTER_MS（R4：mixed_traffic_send 抖动参数化读取该 env）。
    """
    os.environ["ATK_DURATION_S"] = str(args.duration)
    os.environ["ATK_PPS"] = str(args.pps)
    os.environ["ATK_PACKET_SIZE"] = str(args.packet_size)
    os.environ["ATK_FLOW_COUNT"] = str(args.flow_count)
    os.environ["ATK_IAT_JITTER_MS"] = str(args.iat_jitter_ms)


def _inject_ping_monitor_env(args: argparse.Namespace) -> None:
    """注入 ping 监控默认值 env（003-G-001/G-002；工具调用时读取）。

    来源：experiment.json 的 ping_monitor 节 → env PING_MONITOR_*。
    """
    pm = dict(getattr(args, "ping_monitor", {}) or {})
    os.environ["PING_MONITOR_PROBES_PER_SEC"] = str(pm.get("probes_per_sec", 10))
    os.environ["PING_MONITOR_SUMMARY_INTERVAL_S"] = str(pm.get("summary_interval_s", 1))
    os.environ["PING_MONITOR_FALLBACK_INTERVAL_S"] = str(pm.get("fallback_interval_s", 1.0))
    os.environ["PING_MONITOR_STATS_WINDOW_S"] = str(pm.get("stats_window_s", 5.0))
    os.environ["PING_MONITOR_MAX_SAMPLES"] = str(pm.get("max_samples", 4000))


def _apply_profile_seeds(args: argparse.Namespace) -> dict | None:
    """004-T016：提供 --pcap-path 时画像映射注入未显式指定参数。

    优先级（research 决策 1）：CLI 显式参数 > 映射值 > experiment.json 默认。
    映射值仅作为「未显式指定时」的初始种子；画像失败回退配置默认并提示。
    返回映射 dict（含 dst_port 种子）或 None（未应用）。
    """
    if not args.pcap_path or args.trex_explore:
        return None
    try:
        from src.tools.pcap_profile_tool import pcap_profile_tool
        from src.tools.profile_to_params import profile_to_params
        profile = pcap_profile_tool(pcap_path=args.pcap_path)
    except Exception as e:
        print(f"[画像] 画像失败，使用配置默认参数: {e}", file=sys.stderr)
        return None
    mapped = profile_to_params(profile, defaults={
        "dst_port": 8080,
        "packet_size": args.packet_size,
        "pps": args.pps,
        "flow_count": args.flow_count,
        "duration_s": args.duration,
    })
    explicit = getattr(args, "_explicit_flags", set())
    if "pps" not in explicit:
        args.pps = mapped["pps"]
    if "packet_size" not in explicit:
        args.packet_size = mapped["packet_size"]
    if "flow_count" not in explicit:
        args.flow_count = mapped["flow_count"]
    if "duration" not in explicit:
        args.duration = mapped["duration_s"]
    args.profile_seeds = mapped
    return mapped


def _inject_pcap_profile_env(args: argparse.Namespace) -> None:
    """注入 PCAP 画像默认值 env（004-T004；工具调用时读取）。

    来源：experiment.json 的 pcap_profile 节 → env PCAP_PROFILE_*。
    """
    pp = dict(getattr(args, "pcap_profile", {}) or {})
    os.environ["PCAP_PROFILE_MAX_PACKETS"] = str(pp.get("max_packets", 50000))
    os.environ["PCAP_PROFILE_IDLE_TIMEOUT_S"] = str(pp.get("idle_timeout_s", 30))


def _agent_log_path() -> str:
    """Today's agent log path, daily-rotated: ``data/agent-YYYY-MM-DD.log``."""
    return f"data/agent-{datetime.now().strftime('%Y-%m-%d')}.log"


def main() -> int | None:
    """CLI 入口：实验模式返回 None（退出码 0），探索模式返回达标退出码 0/1。"""
    args = parse_args()

    # ── Run identity: every log_result line in this run shares this id ──
    run_id = generate_run_id()
    os.environ["DSH_RUN_ID"] = run_id

    _run_preflight(args)
    # 008-T011/008-2：配置默认值超限启动警告（load/apply_profile 之后、env 注入之前）
    _warn_config_over_limits(args)

    # G2（006-T013）：--clean-scripts 仅探索模式生效，启动时（env 注入前）
    # 清空 trex_scripts/cat_*.py 旧脚本，绝不动非 cat_ 文件。
    if args.trex_explore and args.clean_scripts:
        removed = _clean_catalog_scripts(get_trex_scripts_dir())
        if removed:
            print(f"[clean-scripts] 已删除 {removed} 个旧 cat_*.py 脚本"
                  "（仅 trex_scripts/cat_*.py）")
        else:
            print("[clean-scripts] trex_scripts/ 无旧 cat_*.py 脚本可清理")

    # 画像映射种子（004-T016）：先于 env 注入，使映射值经 env 进入工具默认
    _apply_profile_seeds(args)

    # ── Inject defaults as env vars (tools read these at call time) ──
    _inject_attack_env(args)
    _inject_ping_monitor_env(args)
    _inject_pcap_profile_env(args)
    os.environ["PKTGEN_RATE"] = str(args.pktgen_rate)
    os.environ["PKTGEN_DURATION_MS"] = str(args.pktgen_duration)
    # 合法源地址（005-T004/D9）：适配器在编译前填入，覆盖 vendored 伪造默认
    os.environ["PKTGEN_SRC_IP"] = str(args.pktgen_src_ip)

    # ── Pktgen-DPDK configuration ──
    if args.pktgen_live:
        os.environ["PKTGEN_DRY_RUN"] = "false"
    if args.pktgen_host is not None:
        os.environ["PKTGEN_HOST"] = args.pktgen_host
    if args.pktgen_port is not None:
        os.environ["PKTGEN_PORT"] = str(args.pktgen_port)

    # ── User instruction (experiment mode, injected into prompt) ──
    os.environ["INSTRUCTION"] = args.instruction

    # ── TRex configuration ──
    _apply_mode_env(args)
    if args.trex_live:
        os.environ["TREX_DRY_RUN"] = "false"
    if args.trex_host is not None:
        os.environ["TREX_HOST"] = args.trex_host
    if args.trex_port is not None:
        os.environ["TREX_PORT"] = str(args.trex_port)
    os.environ["TREX_TIMEOUT_S"] = str(args.trex_timeout)
    # trex L2 事实（dst_mac/src_mac/start_force）来自 experiment.json 的 trex 段
    trex_cfg = _load_config_defaults().get("trex", {})
    _apply_trex_l2_env(trex_cfg)

    pktgen_host = args.pktgen_host or get_pktgen_host()
    pktgen_port = args.pktgen_port or get_pktgen_port()
    trex_host = args.trex_host or get_trex_host()
    trex_port = args.trex_port or get_trex_port()

    print(f"=== Closed-Loop Experiment ===")
    print(f"Run ID:     {run_id}")
    print(f"Target:     {args.target_ip}")
    print(f"PCAP:       {args.pcap_path or '(none)'}")
    print(f"Log:        {args.log_path}")
    print(f"Max iters:  {args.max_iters}")
    print(f"Stop after: {args.no_improve_limit} rounds no improvement")
    if args.profile:
        print(f"Profile:    {args.profile}")
    if args.instruction:
        print(f"Instruction: {args.instruction}")
    pktgen_mode = "live" if args.pktgen_live else "dry-run"
    print(f"Pktgen:     {pktgen_mode} ({pktgen_host}:{pktgen_port})")
    trex_mode = "live" if args.trex_live else ("explore" if args.trex_explore else "dry-run")
    print(f"Trex:       {trex_mode} ({trex_host}:{trex_port})")
    if args.trex_explore:
        # 时间戳精确到微秒：连续多次运行的文件名互不相同（SC-006 互不覆盖）
        catalog_path = (Path("output")
                        / f"trex_attack_catalog_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.md")
        print(f"Catalog:    ≥{args.catalog_target} attack scripts → "
              f"{catalog_path} (no traffic, no HITL)")
        if args.explore_direction:
            print(f"Direction:  {args.explore_direction}")
    print()

    # ── Logging: info → console; debug → file (agent logger only) ──
    # Daily-rotated: data/agent-YYYY-MM-DD.log (new file per calendar day).
    log_file = Path(_agent_log_path())
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_fh = logging.FileHandler(log_file, encoding="utf-8")
    log_fh.setLevel(logging.DEBUG)
    log_fh.setFormatter(logging.Formatter("%(message)s"))
    log_ch = logging.StreamHandler()
    log_ch.setLevel(logging.DEBUG if args.verbose else logging.INFO)
    log_ch.setFormatter(logging.Formatter("%(message)s"))

    agent_logger = logging.getLogger("agent")
    agent_logger.setLevel(logging.DEBUG)
    agent_logger.addHandler(log_ch)
    agent_logger.addHandler(log_fh)
    agent_logger.propagate = False  # don't bubble to root, keep other libs quiet

    # ── Run boundary markers for the lessons pipeline (spec 010 FR-005) ──
    agent_logger.info("[RUN START] %s", run_id)

    verbose = VerboseCallback()
    mode = "catalog" if args.trex_explore else "experiment"
    graph = build_graph(
        max_iters=args.max_iters, no_improve_limit=args.no_improve_limit,
        mode=mode,
    )
    thread_id = str(uuid4())[:8]
    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": [verbose],
        "recursion_limit": _recursion_limit(args.max_iters),
    }

    initial_state = {"messages": [{"role": "user", "content": _build_user_message(args)}]}

    print(f"Thread: {thread_id}")
    print()

    # ── 运行时硬裁决状态（G1/D1/D5；仅实验模式生效，目录模式豁免 D6）──
    verdict_state: dict = {"best_reward": 0.0, "consecutive_no_improve": 0}
    iteration = 0
    last_approved: bool | None = None
    seen_count = 0
    forced_stop_reason: str | None = None
    catalog_exit: int | None = None

    # ── Monitor lifecycle: program-owned, auto-started (spec 009) ──
    # Catalog mode sends no traffic and needs no observation (FR-004).
    if not args.trex_explore:
        started = start_experiment_monitors(args.target_ip)
        agent_logger.info("Monitors auto-started: ping=%s", started["ping"])

    try:
        # Start the agent — runs until first interrupt (HITL on traffic_send)
        graph.invoke(initial_state, config)

        # Poll for interrupts and resume with HITL approval
        while True:
            gs = graph.get_state(config)
            if not gs or not gs.next:
                break  # graph completed

            messages = (gs.values or {}).get("messages", [])
            # ── 运行时硬裁决：结算上一轮实测观测并检查停止条件 ──
            if mode == "experiment":
                if last_approved is True:
                    iteration += 1
                    obs = _extract_observation(messages[seen_count:])
                    verdict_state = apply_observation(verdict_state, obs)
                    if check_stop_condition(
                        iteration,
                        verdict_state["consecutive_no_improve"],
                        args.max_iters,
                        args.no_improve_limit,
                    ):
                        forced_stop_reason = (
                            f"达到最大轮数 {args.max_iters}"
                            if iteration >= args.max_iters
                            else f"连续 {args.no_improve_limit} 轮无改善"
                        )
                        print(f"\n[硬裁决] {forced_stop_reason}，强制停止实验。")
                        break
                seen_count = len(messages)

            # Display the interrupt payload so the operator sees what is approved
            payload = _extract_hitl_payload(gs)
            print((payload or {}).get("message", "[HITL] Action requested"))
            if payload and payload.get("params"):
                print(json.dumps(payload["params"], ensure_ascii=False, indent=2))
            if args.auto_approve:
                approved = True
                print("  Auto-approved (--auto-approve)")
            else:
                try:
                    response = input("  Approve? (y/n): ").strip().lower()
                except EOFError:
                    print("  No input — rejecting by default")
                    response = "n"
                approved = response == "y"
                print(f"  {'Approved' if approved else 'Rejected'}")
            graph.invoke(Command(resume=approved), config)
            last_approved = approved
            print()

        # Get final state
        final_state = graph.get_state(config)
        result = final_state.values if final_state else {}

        print("=== Experiment Complete ===")

        if forced_stop_reason:
            # 硬裁决强制停止：输出系统总结（模型未主动总结）
            print(f"\n[实验总结] 因「{forced_stop_reason}」由运行时硬裁决强制停止。")
            print(
                f"共执行 {iteration} 轮；历史最优奖励 best_reward="
                f"{verdict_state.get('best_reward', 0.0):.2f}；"
                f"连续无改善 {verdict_state.get('consecutive_no_improve', 0)} 轮。"
            )
            content = ""
        else:
            # Extract final AI message for summary
            messages = result.get("messages", [])
            content = ""
            if messages:
                last_msg = messages[-1]
                content = getattr(last_msg, "content", str(last_msg))
                if content:
                    # Print the last meaningful content (excluding tool results)
                    print("\n" + str(content))
                else:
                    print("(no summary output)")

        # Catalog mode: persist the final summary as the deliverable.
        # G1（006-T012）：达标统计（parse-only 语法检查）与退出码判定——
        # 无论达标与否总结均落盘；未达标退出码 1。
        catalog_exit = None
        if args.trex_explore:
            catalog_exit = _finalize_catalog_run(
                catalog_path, get_trex_scripts_dir(), args.catalog_target, content,
            )

        print(f"\nResults logged to: {args.log_path}")
    finally:
        # Close the run boundary marker even on exception (spec 010 FR-005).
        agent_logger.info("[RUN END] %s", run_id)
        # Ensure both monitors are always cleaned up (spec 009 FR-007)
        try:
            stop_experiment_monitors()
        except Exception:
            logger.warning("Monitor cleanup failed", exc_info=True)
    return catalog_exit


if __name__ == "__main__":
    sys.exit(main())
