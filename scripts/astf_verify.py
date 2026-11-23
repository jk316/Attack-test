#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ASTF 验证脚本（TRex 3.08）

目标：验证 ASTF daemon 可用，并对真实服务器 100.1.11.3:8081 完成
真实 TCP 三次握手 + 发送一个 HTTP GET（图片接口），打印是否收到响应。

运行（客户端机器，conda trex311）：
  cd ~/fzx/Attack-test/trex_scripts
  PYTHONPATH=/root/fzx/Trex_Scripts/v3.08/automation/trex_control_plane/interactive \
    python3 astf_verify.py

关键设计：TRex 端口 0 的 IP 是 100.1.11.200（与目标同网段，见 diag 日志
src_ipv4）。本脚本让 ASTF 客户端以 100.1.11.200 为源、以真实服务器
100.1.11.3 为目的，服务器的响应会回到 TRex 端口 0 的 RX，从而完成
有状态握手。ip_offset 必须为 0.0.0.0，否则会把真实目标 IP 偏移掉。
"""
import sys

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

SERVER = "10.99.80.222"   # TRex daemon 所在机器
SYNC = 4501               # 单实例切换后仍是默认 RPC 端口
ASYNC = 4502              # sync + 1
PORT = 0                  # TRex 流量口（100G 那块）
CLIENT_IP = "100.1.11.200"  # TRex 端口 IP
TARGET = "100.1.11.3"     # 真实服务器
DPORT = 8081
IMAGE_PATH = "/api/activities/00000000-0000-0000-0000-000000000001/image"

HTTP_REQ = (
    f"GET {IMAGE_PATH} HTTP/1.1\r\n"
    f"Host: {TARGET}:{DPORT}\r\n"
    "Connection: close\r\n"
    "User-Agent: trex-astf-verify/1.0\r\n"
    "\r\n"
).encode()


class ProfGetImage(ASTFProfile):
    """单个 HTTP GET 客户端流：握手 → GET → 收响应 → 关闭。"""

    def __init__(self):
        super().__init__()

        # ── 客户端程序 ──
        prog_c = ASTFProgram()
        prog_c.connect()            # 与 ip_gen_s 指向的“服务器”建连
        prog_c.send(HTTP_REQ)       # 发 GET
        prog_c.recv(1, 10000)       # 等至少 1 字节响应（10 秒超时）
        prog_c.delay(2000)
        prog_c.reset()

        # ── 服务端程序（TRex 惯例必须定义；打真实服务器时不会被用到）──
        prog_s = ASTFProgram()
        prog_s.accept()
        prog_s.recv(1)
        prog_s.send(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        prog_s.delay(1000)

        # ── IP 分配：客户端用 TRex 端口 IP，服务端指向真实服务器 ──
        ip_gen_c = ASTFIPGenDist(ip_range=[CLIENT_IP, CLIENT_IP], distribution="seq")
        ip_gen_s = ASTFIPGenDist(ip_range=[TARGET, TARGET], distribution="seq")
        ip_gen = ASTFIPGen(glob=ASTFIPGenGlobal(ip_offset="0.0.0.0"),
                           dist_client=ip_gen_c,
                           dist_server=ip_gen_s)

        # ── 模板（兼容不同小版本的参数名 port / dport）──
        try:
            temp_c = ASTFTCPClientTemplate(port=DPORT, program=prog_c)
        except TypeError:
            temp_c = ASTFTCPClientTemplate(dport=DPORT, program=prog_c)
        temp_s = ASTFTCPServerTemplate(program=prog_s)
        template = ASTFTemplate(client_template=temp_c, server_template=temp_s)

        self.add_template(template)
        self.set_ip_gen(ip_gen)


def main() -> None:
    c = ASTFClient(server=SERVER, sync_port=SYNC, async_port=ASYNC)
    try:
        c.connect()
    except Exception as e:
        print("❌ 连不上 ASTF daemon（模式/端口不对？）:", e)
        sys.exit(1)
    print("✅ 已连接 ASTF daemon——模式握手通过（server 是 ASTF 模式）")

    try:
        c.acquire(force=True)
        c.reset()
        pa = c.get_port_attr(PORT)
        print(f"✅ 端口 {PORT} 已 reset：link={pa.get('link')}, "
              f"speed={pa.get('speed')}G, src_ipv4={pa.get('src_ipv4')}")
        if pa.get("link") != "UP":
            print("⚠️  端口 link 不是 UP，流量可能发不出去")
    except Exception as e:
        print("❌ acquire/reset 失败:", e)
        c.disconnect()
        sys.exit(1)

    print(f"▶ 发送 ASTF 流：{CLIENT_IP} → {TARGET}:{DPORT}  GET {IMAGE_PATH}")
    try:
        c.start(profiles=[ProfGetImage()], mult=1.0, duration=15)
        c.wait_on_traffic(ports=[PORT], timeout=25)
        stats = c.get_stats()
    except Exception as e:
        print("❌ start/统计失败（API 或模式问题）:", e)
        c.disconnect()
        sys.exit(1)

    ps = stats.get(PORT, {})
    tx, rx = ps.get("opackets", 0), ps.get("ipackets", 0)
    print(f"▶ 端口 {PORT}: tx={tx} 包, rx={rx} 包")
    if rx > 0:
        print("🎉 真实服务器有回包——三次握手成功，HTTP 请求已送达")
    else:
        print("⚠️  无回包，排查顺序：")
        print("    1) 端口 link 是否 UP；2) 100.1.11.200 与 100.1.11.3 是否同网段可达")
        print("    3) 服务器 8081 是否真的在听（curl --noproxy '*' 试试）")

    c.stop()
    c.release()
    c.disconnect()
    print("done")


if __name__ == "__main__":
    main()
