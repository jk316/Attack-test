#!/usr/bin/env python3
"""TRex 客户端库 API 探测脚本 — 把已安装客户端库的真实签名 dump 成 Markdown。

目的（trex-code-learning P1）：
  让智能体「从代码学习」TRex 用法，取代对 API 的模糊记忆。在装有与 daemon
  版本匹配的 TRex 客户端库的解释器里运行本脚本（本实验床为 trex311，
  见 experiment.json → trex.python），输出关键类/方法的 inspect.signature +
  docstring 首行，作为 docs/trex-api-reference.md 的权威来源。

用法:
    python3 scripts/trex_api_probe.py                          # 输出到 stdout
    python3 scripts/trex_api_probe.py -o docs/trex-api-reference.md
    python3 scripts/trex_api_probe.py --expect 3.08            # 版本对齐检查
    python3 scripts/trex_api_probe.py --connect 10.99.80.222:4501  # 顺带读 daemon 版本

特性:
  - 仅依赖 stdlib，可在任何 Python 3.8+ 解释器里运行；
  - 自动识别 v3 布局（trex.stl.api / trex.astf.api，实验床 3.08 用这个）
    与 v2 布局（trex_stl_lib.api / trex_astf_lib.api）；
  - 在未安装客户端库的解释器里优雅降级：输出清晰诊断并以退出码 1 结束；
  - 探测目标中找不到的符号会进「未找到」一节——这是版本不匹配的信号。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import importlib
import importlib.metadata
import inspect
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

# ── 探测目标（版本无关的符号清单）─────────────────────────────────

_STL_CLASSES = [
    "STLStream", "STLPktBuilder", "STLVmFlowVar", "STLVmWrFlowVar",
    "STLVmFixChecksumHw", "STLVmFixIpv4", "STLFlowStats",
]

_STL_CLIENT_METHODS = [
    "connect", "disconnect", "acquire", "release", "reset", "clear_stats",
    "add_streams", "start", "stop", "pause", "resume", "wait_on_traffic",
    "get_stats", "get_port_attr", "set_service_mode", "set_l3_mode",
    "set_l2_mode", "resolve", "arp", "ping_rpc_server", "get_server_version",
    "get_server_system_info", "is_connected", "push_remote", "load_profile",
]

_ASTF_CLASSES = [
    "ASTFProfile", "ASTFTemplate", "ASTFTCPClientTemplate",
    "ASTFTCPServerTemplate", "ASTFUDPClientTemplate", "ASTFUDPServerTemplate",
    "ASTFIPGen", "ASTFIPGenGlobal", "ASTFIPGenDist", "ASTFCapInfo",
]

_ASTF_CLIENT_METHODS = [
    "connect", "disconnect", "acquire", "release", "reset", "clear_stats",
    "load_profile", "start", "stop", "get_stats", "get_port_attr",
    "set_service_mode", "set_l3_mode", "set_l2_mode", "resolve",
    "get_server_version", "get_server_system_info", "is_connected",
]

_ASTF_PROGRAM_METHODS = [
    "send", "recv", "connect", "accept", "close", "reset", "delay",
    "send_msg", "recv_msg", "set_var", "get_var", "wait_for_flow",
]

# pip dist 名候选（任一命中即采信）
_VERSION_DISTS = ["trex", "trex_stl_lib", "trex_astf_lib", "trex-astf-lib"]

_LAYOUTS = [
    {
        "key": "v3",
        "stl": "trex.stl.api",
        "astf": "trex.astf.api",
        "note": "TRex 3.x 布局（实验床 3.08 用这个）",
    },
    {
        "key": "v2",
        "stl": "trex_stl_lib.api",
        "astf": "trex_astf_lib.api",
        "note": "TRex 2.x 布局（与 3.08 daemon 不匹配，仅作参考）",
    },
]


def detect_layout() -> dict[str, Any]:
    """尝试导入 v3 / v2 两种客户端库布局，返回可导入的模块。

    任何导入异常都当作「该布局不存在」处理；本机（无 trex 库）返回空布局。
    """
    for layout in _LAYOUTS:
        stl = astf = None
        try:
            stl = importlib.import_module(layout["stl"])
        except Exception:
            stl = None
        try:
            astf = importlib.import_module(layout["astf"])
        except Exception:
            astf = None
        if stl is not None or astf is not None:
            return {
                "layout": layout["key"],
                "note": layout["note"],
                "stl_module": layout["stl"] if stl is not None else None,
                "astf_module": layout["astf"] if astf is not None else None,
                "stl": stl,
                "astf": astf,
            }
    return {
        "layout": None,
        "note": "未找到任何 TRex 客户端库",
        "stl_module": None,
        "astf_module": None,
        "stl": None,
        "astf": None,
    }


def _signature(obj: Any) -> str:
    """优先取类/函数的构造签名，失败回退 __init__，再失败给出占位。"""
    try:
        return str(inspect.signature(obj))
    except (TypeError, ValueError):
        pass
    init = getattr(obj, "__init__", None)
    if init is not None:
        try:
            return str(inspect.signature(init))
        except (TypeError, ValueError):
            pass
    return "(签名不可用)"


def _doc_first_line(obj: Any, max_chars: int = 200) -> str:
    doc = (getattr(obj, "__doc__", None) or "").strip()
    if not doc:
        return ""
    line = doc.splitlines()[0].strip()
    return line if len(line) <= max_chars else line[:max_chars] + "…"


def _probe(module: Any, class_specs: list[tuple[str, list[str] | None]]) -> tuple[list[dict], list[str]]:
    """按符号清单探测模块。返回 (rows, missing)。"""
    rows: list[dict] = []
    missing: list[str] = []
    for name, methods in class_specs:
        cls = getattr(module, name, None)
        if cls is None:
            missing.append(name)
            continue
        entry: dict[str, Any] = {
            "name": name,
            "sig": _signature(cls),
            "doc": _doc_first_line(cls),
            "methods": [],
        }
        for mname in methods or []:
            meth = getattr(cls, mname, None)
            if meth is None:
                missing.append(f"{name}.{mname}")
                continue
            entry["methods"].append({
                "name": mname,
                "sig": _signature(meth),
                "doc": _doc_first_line(meth),
            })
        rows.append(entry)
    return rows, missing


def _module_index(module: Any, max_chars: int = 500) -> str:
    """模块级 ASTF*/STL* 符号索引（用于发现能力，截断保护）。"""
    if module is None:
        return ""
    names = sorted(
        n for n in dir(module)
        if not n.startswith("_") and (n.startswith("ASTF") or n.startswith("STL"))
    )
    text = ", ".join(names)
    if len(text) > max_chars:
        return text[:max_chars] + f"… (+{len(names)} 个符号)"
    return text


def collect_versions(layout: dict[str, Any]) -> list[tuple[str, str]]:
    """收集一切能找到的版本证据：pip dist + 模块属性。"""
    out: list[tuple[str, str]] = []
    for dist in _VERSION_DISTS:
        try:
            out.append((f"pip dist {dist}", importlib.metadata.version(dist)))
        except importlib.metadata.PackageNotFoundError:
            pass
    for key, mod in (("stl", layout["stl"]), ("astf", layout["astf"])):
        if mod is None:
            continue
        for attr in ("__version__", "VERSION", "version"):
            val = getattr(mod, attr, None)
            if isinstance(val, str):
                out.append((f"{key} 模块 {attr}", val))
    return out


_CONNECT_PROBE_CODE = """\
import sys
modname, host, port, key = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
mod = __import__(modname, fromlist=["*"])
cls = getattr(mod, key)
c = cls(server=host, sync_port=port)
c.connect()
for mname in ("get_server_version", "get_server_system_info"):
    meth = getattr(c, mname, None)
    if meth is None:
        continue
    print(meth())
    break
else:
    print("connected-but-no-version-api")
"""


def probe_server_version(layout: dict[str, Any], host: str, port: int) -> tuple[str, str]:
    """best-effort 连接 daemon 读版本（先 ASTF 后 STL 客户端）。返回 (文本, 状态)。

    每次尝试都放在独立子进程里跑，父进程用 subprocess timeout 硬杀：
    TRex RPC 层可能无视 socket 超时和信号，只有杀进程才能保证主探测
    绝不挂起（子进程被杀后 OS 自动关闭其 socket）。
    """
    pairs = [
        ("ASTFClient", layout.get("astf_module")),
        ("STLClient", layout.get("stl_module")),
    ]
    attempts: list[str] = []
    for key, modname in pairs:
        if not modname:
            continue
        try:
            proc = subprocess.run(
                [sys.executable, "-c", _CONNECT_PROBE_CODE, modname, host, str(port), key],
                capture_output=True, text=True, timeout=15,
            )
        except subprocess.TimeoutExpired:
            attempts.append(f"{key}: 连接/查询超时（15s，子进程已杀）")
            continue
        except OSError as e:
            attempts.append(f"{key}: 无法启动子进程: {e}")
            continue
        if proc.returncode == 0 and proc.stdout.strip():
            out = proc.stdout.strip().splitlines()[0][:300]
            return f"{key}: {out}", "ok"
        err = (proc.stderr or "").strip().splitlines()
        detail = err[-1][:200] if err else (proc.stdout.strip()[:200] or "无输出")
        attempts.append(f"{key}: 失败(rc={proc.returncode}) {detail}")
    return ("; ".join(attempts) or "无可用客户端", "error")


def _render_symbols(section: dict, module_path: str | None) -> list[str]:
    lines: list[str] = []
    if module_path:
        lines.append(f"模块: `{module_path}`")
    index = section.get("index") or ""
    if index:
        lines.append("")
        lines.append("模块级符号索引（ASTF*/STL*）：")
        lines.append(f"`{index}`")
    for row in section["rows"]:
        lines.append("")
        lines.append(f"#### {row['name']}")
        lines.append(f"签名: `{row['sig']}`")
        if row["doc"]:
            lines.append(f"{row['doc']}")
        if row["methods"]:
            lines.append("")
            lines.append("关键方法：")
        for meth in row["methods"]:
            doc = f" — {meth['doc']}" if meth["doc"] else ""
            lines.append(f"- `{meth['name']}{meth['sig']}`{doc}")
    return lines


def render_report(ctx: dict[str, Any]) -> str:
    """把探测上下文渲染成 Markdown 参考文档。"""
    layout = ctx["layout"]
    lines: list[str] = [
        "# TRex 客户端库 API 参考（自动探测生成）",
        "",
        f"> 生成时间: {ctx['generated_at']} · 解释器: `{ctx['interpreter']}` · "
        f"Python: {ctx['python']}",
        "",
        "## 1. 版本与布局",
        "",
        f"- 布局: **{layout['layout'] or '未找到'}** — {layout['note']}",
    ]
    for key, mod_path in (("stl", layout["stl_module"]), ("astf", layout["astf_module"])):
        if mod_path:
            mod = layout[key]
            file_path = getattr(mod, "__file__", None)
            if file_path:
                lines.append(f"- {key} 模块路径: `{file_path}`")
    lines.append("- 版本证据:")
    if ctx["versions"]:
        for label, value in ctx["versions"]:
            lines.append(f"  - {label}: `{value}`")
    else:
        lines.append("  - （无）")
    if ctx["expect"]:
        if ctx["expect_ok"] is True:
            lines.append(f"- 期望版本检查: ✓ 证据中含 `{ctx['expect']}`")
        elif ctx["expect_ok"] is False:
            lines.append(f"- 期望版本检查: ⚠ 证据中未找到 `{ctx['expect']}`（可能与 daemon 不匹配）")
        else:
            lines.append(f"- 期望版本检查: —（无版本证据，无法比对 `{ctx['expect']}`）")
    if ctx["server"]:
        status = {"ok": "✓", "warn": "⚠", "error": "✗"}.get(ctx["server_status"], "?")
        lines.append(f"- daemon 版本（--connect）: {status} {ctx['server']}")
    lines.append("")

    if layout["layout"] is None:
        lines += [
            "## 诊断",
            "",
            "此解释器未找到任何 TRex 客户端库（已尝试 v3 布局 `trex.stl.api` / `trex.astf.api` "
            "与 v2 布局 `trex_stl_lib.api` / `trex_astf_lib.api`）。",
            "",
            "> ⚠️ 请在装有与 daemon 版本匹配的客户端库的解释器里运行本脚本。",
            "> 本实验床：`experiment.json → trex.python`（当前为 "
            "`/root/miniconda3/envs/trex311/bin/python`）。",
            "",
        ]
        return "\n".join(lines)

    lines += ["## 2. STL API（无状态）", ""]
    lines += _render_symbols(ctx["stl_section"], layout["stl_module"])
    lines += ["", "## 3. ASTF API（有状态）", ""]
    lines += _render_symbols(ctx["astf_section"], layout["astf_module"])
    lines += ["", "## 4. 未找到的符号（版本/布局不匹配信号）", ""]
    stl_missing = ctx["stl_section"]["missing"]
    astf_missing = ctx["astf_section"]["missing"]
    all_missing = [f"STL: {m}" for m in stl_missing] + [f"ASTF: {m}" for m in astf_missing]
    if all_missing:
        for m in all_missing:
            lines.append(f"- {m}")
    else:
        lines.append("- 无（探测清单全部命中）")
    lines += [
        "",
        "> 本文件由 `scripts/trex_api_probe.py` 自动生成，请勿手改；重新运行覆盖即可。",
        "> 用法/环境事实见 `docs/trex-astf-playbook.md` 与 `trex_scripts/trex_common.py`。",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="把 TRex 客户端库的关键 API 签名 dump 成 Markdown 参考文档。"
    )
    parser.add_argument("-o", "--out", help="输出文件路径（默认 stdout）")
    parser.add_argument("--expect", help="期望版本子串（如 3.08），用于对齐检查")
    parser.add_argument("--connect", help="顺带连接 daemon 读版本，形如 host:port")
    args = parser.parse_args(argv)

    layout = detect_layout()
    versions = collect_versions(layout)
    server = ""
    server_status = "error"
    if args.connect:
        host_port = args.connect.rsplit(":", 1)
        host = host_port[0]
        try:
            port = int(host_port[1]) if len(host_port) == 2 else 4501
        except ValueError:
            port = 4501
        server, server_status = probe_server_version(layout, host, port)

    expect_ok = None
    if args.expect:
        evidence = [v for _, v in versions] + ([server] if server else [])
        expect_ok = any(args.expect in e for e in evidence)

    stl_section = {"rows": [], "missing": [], "index": ""}
    astf_section = {"rows": [], "missing": [], "index": ""}
    if layout["stl"] is not None:
        stl_rows, stl_missing = _probe(
            layout["stl"],
            [("STLClient", _STL_CLIENT_METHODS)] + [(c, None) for c in _STL_CLASSES],
        )
        stl_section = {
            "rows": stl_rows,
            "missing": stl_missing,
            "index": _module_index(layout["stl"]),
        }
    if layout["astf"] is not None:
        astf_rows, astf_missing = _probe(
            layout["astf"],
            [("ASTFClient", _ASTF_CLIENT_METHODS), ("ASTFProgram", _ASTF_PROGRAM_METHODS)]
            + [(c, None) for c in _ASTF_CLASSES],
        )
        astf_section = {
            "rows": astf_rows,
            "missing": astf_missing,
            "index": _module_index(layout["astf"]),
        }

    ctx = {
        "generated_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "interpreter": sys.executable,
        "python": platform.python_version(),
        "layout": layout,
        "versions": versions,
        "expect": args.expect,
        "expect_ok": expect_ok,
        "server": server,
        "server_status": server_status,
        "stl_section": stl_section,
        "astf_section": astf_section,
    }
    report = render_report(ctx)

    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"已写入 {args.out}", file=sys.stderr)
    else:
        print(report)
    return 0 if layout["layout"] is not None else 1


if __name__ == "__main__":
    sys.exit(main())
