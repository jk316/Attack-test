#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ASTF 验证脚本（TRex 3.08）

流程：连 ASTF daemon → 端口 L3 配置（set_l3_mode，ARP 不通则退回
set_l2_mode 固定网关 MAC）→ 生成 profile 文件 → load_profile →
start(pid_input) → 统计 rx 是否有回包。

运行（客户端机器，conda trex311）：
  cd ~/fzx/Attack-test/scripts
  PYTHONPATH=/root/fzx/Trex_Scripts/v3.08/automation/trex_control_plane/interactive \
    python3 astf_verify.py
"""
import inspect
import sys
import tempfile
import time

from trex.astf.api import (
    ASTFClient,
    ASTFIPGen,
    ASTFIPGenDist,
    ASTFIPGenGlobal,
    ASTFProgram,
    ASTFProfile,
    ASTFTCPClientTemplate,
    ASTFTCPServerTemplate,
    ASTFTemplate,
)

SERVER = "10.99.80.222"     # TRex daemon 所在机器
SYNC = 4501                 # 单实例 ASTF 默认 RPC 端口
ASYNC = 4502
PORT = 0                    # TRex 流量口（100G）
CLIENT_IP = "100.1.11.200"  # TRex 端口 IP（STL 时代同款，网络可达）
TARGET = "100.1.11.3"       # 真实服务器
DPORT = 8081
GATEWAY_MAC = "f4:e9:75:ee:51:69"  # 网关 MAC（STL 时证明可达目标）
SRC_MAC = "58:a2:e1:6d:89:2c"      # 端口自身 MAC
IMAGE_PATH = "/api/activities/00000000-0000-0000-0000-000000000001/image"

# ── 运行时探测本版本 ASTF API 的参数名 ──
print(f"[debug] ASTFClient.start 签名: {inspect.signature(ASTFClient.start)}")

# ── ASTF profile 源码：3.08 惯例——普通类 + get_profile() 返回 ASTFProfile 实例 ──
# （对照官方 examples/astf/http_many.py 的写法）
PROFILE_SRC = '''\
from trex.astf.api import *

CLIENT_IP = "__CLIENT_IP__"
TARGET = "__TARGET__"
DPORT = __DPORT__

HTTP_REQ = (
    "GET __IMAGE_PATH__ HTTP/1.1\\r\\n"
    "Host: __TARGET__:__DPORT__\\r\\n"
    "Connection: close\\r\\n"
    "User-Agent: trex-astf-verify/1.0\\r\\n"
    "\\r\\n"
).encode()


class ProfGetImage():
    def __init__(self):
        pass

    def get_profile(self, **kwargs):
        # ── 客户端程序：握手 → GET → 收响应 → 关闭 ──
        prog_c = ASTFProgram()
        prog_c.connect()
        prog_c.send(HTTP_REQ)
        prog_c.recv(1, 10000)      # 至少收到 1 字节（10 秒超时）
        prog_c.delay(2000)
        prog_c.reset()

        # ── 服务端程序（惯例必须定义；打真实服务器时不会被用到）──
        prog_s = ASTFProgram()
        prog_s.accept()
        prog_s.recv(1)
        prog_s.send(b"HTTP/1.1 200 OK\\r\\nContent-Length: 2\\r\\n\\r\\nok")
        prog_s.delay(1000)

        # ── IP 分配：客户端=TRex 端口 IP，服务端=真实服务器 ──
        ip_gen_c = ASTFIPGenDist(ip_range=[CLIENT_IP, CLIENT_IP], distribution="seq")
        ip_gen_s = ASTFIPGenDist(ip_range=[TARGET, TARGET], distribution="seq")
        ip_gen = ASTFIPGen(glob=ASTFIPGenGlobal(ip_offset="0.0.0.0"),
                           dist_client=ip_gen_c,
                           dist_server=ip_gen_s)

        temp_c = ASTFTCPClientTemplate(ip_gen=ip_gen, port=DPORT, program=prog_c)
        temp_s = ASTFTCPServerTemplate(program=prog_s)
        template = ASTFTemplate(client_template=temp_c, server_template=temp_s)

        return ASTFProfile(default_ip_gen=ip_gen, templates=[template])


def register():
    return ProfGetImage()
'''

def build_profile_source() -> str:
    return (PROFILE_SRC
            .replace("__CLIENT_IP__", CLIENT_IP)
            .replace("__TARGET__", TARGET)
            .replace("__DPORT__", str(DPORT))
            .replace("__IMAGE_PATH__", IMAGE_PATH))


def configure_port(c) -> None:
    """端口 L3 配置：cfg 无 IP，需运行时配置（同 reach3.py）。ARP 不通则退回 L2 固定网关 MAC。"""
    try:
        c.set_service_mode(ports=[PORT], enabled=True)
        try:
            c.set_l3_mode(PORT, CLIENT_IP, TARGET)
            print(f"✅ set_l3_mode：src={CLIENT_IP} dst={TARGET}")
        except Exception as e:
            print("⚠️  set_l3_mode 异常（可能已生效但 ARP 未解）:", e)
        resolved = False
        try:
            c.resolve(ports=[PORT], retries=3)
            resolved = True
            print("✅ resolve（ARP）成功")
        except Exception as e:
            print("⚠️  ARP 解析失败（与 STL 时代一致）:", e)
        if not resolved and hasattr(c, "set_l2_mode"):
            # 注意：set_l2_mode 必须在 service mode 开启期间调用
            try:
                try:
                    c.set_l2_mode(PORT, dst_mac=GATEWAY_MAC)
                except TypeError:
                    c.set_l2_mode(PORT, GATEWAY_MAC)
                print(f"✅ 退回 L2 模式：出口 MAC 固定为网关 {GATEWAY_MAC}")
            except Exception as e:
                print("⚠️  set_l2_mode 失败:", e)
        try:
            c.set_service_mode(ports=[PORT], enabled=False)
        except Exception:
            pass
    except Exception as e:
        print("⚠️  set_service_mode 失败:", e)

    pa = c.get_port_attr(PORT)
    print(f"▶ 端口 {PORT}: link={pa.get('link')}, src_ipv4={pa.get('src_ipv4')}, "
          f"layer_mode={pa.get('layer_mode')}, arp={pa.get('arp')}")


def main() -> None:
    c = ASTFClient(server=SERVER, sync_port=SYNC, async_port=ASYNC)
    try:
        c.connect()
    except Exception as e:
        print("❌ 连不上 ASTF daemon:", e)
        sys.exit(1)
    print("✅ 已连接 ASTF daemon——模式握手通过")

    try:
        c.acquire(force=True)
        c.reset()
    except Exception as e:
        print("❌ acquire/reset 失败:", e)
        c.disconnect()
        sys.exit(1)

    configure_port(c)

    # ── 生成 profile 文件并加载 ──
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(build_profile_source())
        prof_path = f.name
    print(f"▶ profile 文件: {prof_path}")
    try:
        pid = c.load_profile(prof_path)
        print(f"✅ load_profile 成功，pid={pid!r}")
    except Exception as e:
        print("❌ load_profile 失败:", e)
        c.disconnect()
        sys.exit(1)

    print(f"▶ 启动 ASTF 流：{CLIENT_IP} → {TARGET}:{DPORT}  GET {IMAGE_PATH}")
    try:
        c.start(pid_input=pid, mult=1, duration=15, block=True)
        time.sleep(1)
        stats = c.get_stats()
    except Exception as e:
        print("❌ start/统计失败:", e)
        c.disconnect()
        sys.exit(1)

    ps = stats.get(PORT, {})
    tx, rx = ps.get("opackets", 0), ps.get("ipackets", 0)
    print(f"▶ 端口 {PORT}: tx={tx} 包, rx={rx} 包")
    if rx > 0:
        print("🎉 真实服务器有回包——三次握手成功，HTTP 请求已送达")
    else:
        print("⚠️  无回包。排查：1) arp/layer_mode 状态；2) 网关 MAC 是否正确；")
        print("     3) 服务器 8081 是否在听：curl --noproxy '*' http://100.1.11.3:8081/...")

    c.stop()
    c.release()
    c.disconnect()
    print("done")


if __name__ == "__main__":
    main()
