"""TRex 生成脚本的公共辅助模块（顶层仅 stdlib，trex 库延迟 import）。

本文件与生成脚本同目录（trex_scripts/），脚本可直接：

    from trex_common import DST_MAC, SRC_MAC, START_FORCE, start_safe, make_client

已知 L2 拓扑（实测结论，重要）：
- 目标位于网关之后：TRex 端口 0 直接 ARP 解析目标 IP 会失败
  （"Could not resolve following ports: [0]"）。
- 帧必须显式发往网关 MAC（DST_MAC），源 MAC 用 TRex 端口 0 的 SRC_MAC：
      Ether(dst=DST_MAC, src=SRC_MAC)
- 端口 dest 未解析时，裸 c.start(...) 会报
  "Port 0 dest MAC is invalid and there are streams without explicit dest MAC"；
  start_safe() 内置 force=True 绕过该校验。
- 不要在脚本注释/字符串里写非 allowlist 的 IP 字面量（网关 IP 等），
  静态扫描会拦截；此处只提供 MAC。

取值来自环境变量 TREX_DST_MAC / TREX_SRC_MAC / TREX_START_FORCE / TREX_HOST
（CLI main.py 与 Web 控制台 backend/experiment.py 都会在启动时从
experiment.json 注入这些变量）。未设置时使用下方的字面默认值——它们与
src/trex/config.py 的默认值及 topology.yaml / experiment.json 保持一致，
由 tests/unit/test_trex_l2_sync.py 防漂移。请勿只改其中一处。
"""
import os

DST_MAC = os.environ.get("TREX_DST_MAC", "f4:e9:75:ee:51:69")
SRC_MAC = os.environ.get("TREX_SRC_MAC", "58:a2:e1:6d:89:2c")
TREX_SERVER = os.environ.get("TREX_HOST", "127.0.0.1")


def _parse_bool(value):
    return str(value).strip().lower() not in {"false", "0", "no", ""}


START_FORCE = _parse_bool(os.environ.get("TREX_START_FORCE", "true"))


def make_client(server=None):
    """创建并连接 STLClient。

    延迟 import trex_stl_lib：本模块可被任何 Python（含无 trex 库的环境）
    导入，只有真正需要客户端时才要求 trex 库可用。
    """
    from trex_stl_lib.api import STLClient

    client = STLClient(server=server or TREX_SERVER)
    client.connect()
    return client


def start_safe(client, ports=None, mult="100%", duration=10, force=None):
    """启动流量：默认按 START_FORCE 配置决定 force，显式传 force 则覆盖。

    force=True 用于绕过 TRex 的显式 dest MAC 校验
    （"Port 0 dest MAC is invalid ..."）。
    """
    if ports is None:
        ports = [0]
    if force is None:
        force = START_FORCE
    return client.start(ports=ports, mult=mult, duration=duration, force=force)
