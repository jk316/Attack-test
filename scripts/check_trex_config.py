#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TRex 配置一致性检查（本地，无网络、无流量）。

检查三件事，防止「skill 说一套、代码/配置是另一套」再次发生：

  1. 端口：skill / playbook / 脚本 / 源码中无遗留的 async=4502（或 ASYNC = 4502），
     也没有「async = sync + 1」这条误导性约定。正确值：sync=4501、async=4500。
  2. 代码副本：src/trex/config.py 与 trex_scripts/trex_common.py 的
     host / dst_mac / src_mac / start_force 默认值保持一致（防漂移）。
  3. topology.yaml：可解析；trex 段与 pktgen 段键齐全；trex.port 必须为 4501(sync)。

退出码：全部通过 = 0；任一失败 = 1。

运行（项目根目录）：
    uv run python3 scripts/check_trex_config.py
"""
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 扫描范围（相对项目根）。日志(data/)、生成物(output/)、依赖/缓存不在其中。
# trex_scripts/ 是 agent 生成脚本的沙箱：只有 trex_common.py 是权威源（tracked），
# 其余 *.py 是实验一次性产物，可能残留旧端口，不作为配置事实扫描。
SCAN_DIRS = ["skills", "docs", "scripts", "src"]
SCAN_EXTRA_FILES = ["topology.yaml", "experiment.json", "trex_scripts/trex_common.py"]
SCAN_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".sh", ".j2", ".json"}

# 端口错误模式：async 被写成 4502；或「async = sync + 1」约定。
# 注意：不会误报「4502 已关闭」这类说明性文字（它前面没有 async=）。
STALE_ASYNC = re.compile(r"async\s*[=:]\s*4502|ASYNC\s*=\s*4502|async_port\s*=\s*4502")
STALE_CONVENTION = re.compile(r"async\s*=\s*sync\s*\+\s*1")

_failures: list[str] = []


def ok(msg: str) -> None:
    print(f"[ok]   {msg}")


def fail(msg: str) -> None:
    _failures.append(msg)
    print(f"[FAIL] {msg}")


def _iter_source_files():
    self_path = Path(__file__).resolve()
    for rel in SCAN_DIRS:
        base = PROJECT_ROOT / rel
        if not base.exists():
            continue
        for p in base.rglob("*"):
            # 跳过本脚本自身：它的文档/注释里会写这些模式作为说明
            if p.is_file() and p.suffix in SCAN_SUFFIXES and p.resolve() != self_path:
                yield p
    for rel in SCAN_EXTRA_FILES:
        p = PROJECT_ROOT / rel
        if p.is_file():
            yield p


def check_ports() -> None:
    print("== 1. 端口检查（无 async=4502 / 「async=sync+1」）==")
    hits: list[str] = []
    for f in _iter_source_files():
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if STALE_ASYNC.search(line) or STALE_CONVENTION.search(line):
                hits.append(f"    {f.relative_to(PROJECT_ROOT)}:{lineno}: {line.strip()}")
    if hits:
        fail(f"发现 {len(hits)} 处遗留的 async=4502 或「async=sync+1」：")
        print("\n".join(hits))
    else:
        ok("无 async=4502 / 「async=sync+1」残留")


def check_code_copy() -> None:
    print("== 2. 代码副本一致（src/trex/config.py ↔ trex_scripts/trex_common.py）==")
    from src.trex import config as trex_config
    import trex_common

    pairs = [
        ("HOST", trex_config._DEFAULT_HOST, trex_common.TREX_SERVER),
        ("DST_MAC", trex_config._DEFAULT_DST_MAC, trex_common.DST_MAC),
        ("SRC_MAC", trex_config._DEFAULT_SRC_MAC, trex_common.SRC_MAC),
    ]
    for name, a, b in pairs:
        if a == b:
            ok(f"{name}: {a}")
        else:
            fail(f"{name} 不一致: config.py={a!r} vs trex_common.py={b!r}")
    if trex_common.START_FORCE is True:
        ok("START_FORCE: True")
    else:
        fail(f"START_FORCE 默认值应为 True，当前 {trex_common.START_FORCE!r}")


def check_topology() -> None:
    print("== 3. topology.yaml 检查 ==")
    try:
        import yaml
    except ImportError:
        fail("缺少 pyyaml，无法解析 topology.yaml")
        return

    path = PROJECT_ROOT / "topology.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        fail(f"topology.yaml 解析失败: {e}")
        return

    trex = data.get("trex") or {}
    pktgen = data.get("pktgen") or {}

    for k in ("host", "port", "dst_mac", "src_mac", "start_force"):
        if k not in trex:
            fail(f"trex 段缺键: {k}")
    for k in ("host", "port"):
        if k not in pktgen:
            fail(f"pktgen 段缺键: {k}")

    if trex.get("port") != 4501:
        fail(f"trex.port 应为 4501（sync），当前 {trex.get('port')!r}")
    else:
        ok("trex.port = 4501 (sync)")

    ok(f"trex.dst_mac = {trex.get('dst_mac')!r}  /  trex.src_mac = {trex.get('src_mac')!r}")
    ok(f"pktgen = {pktgen.get('host')!r}:{pktgen.get('port')!r}")
    top_dst = data.get("dst_mac") or {}
    ok(f"顶层 dst_mac（Pktgen 用）= {top_dst.get('portlist')!r}")


def main() -> int:
    # 让 trex_common 读到源码默认值，而不是当前环境变量的覆盖
    sys.path.insert(0, str(PROJECT_ROOT))
    sys.path.insert(0, str(PROJECT_ROOT / "trex_scripts"))
    for k in ("TREX_HOST", "TREX_DST_MAC", "TREX_SRC_MAC", "TREX_START_FORCE"):
        os.environ.pop(k, None)

    check_ports()
    check_code_copy()
    check_topology()
    print()
    if _failures:
        print(f"结果：{len(_failures)} 项失败")
        return 1
    print("结果：全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
