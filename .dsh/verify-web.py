#!/usr/bin/env python
"""Web 控制台端到端真实验证脚本（watchdog）。

覆盖：REST 静态页/status/defaults/start 校验、PCAP 上传白名单、
WS 真实 LLM 实验（含 R8 画像映射）、HITL 请求/拒绝 0 流量、
007-2 非会话所有者防护、实验结束后监控清理。
安全：HITL 一律拒绝 → 全程零真实流量；目标 10.99.80.160 仅用于
allowlist 通过与参数规划，不发送任何报文。
"""
import asyncio
import json
import os
import sys

import httpx
import websockets

BASE = os.environ.get("VERIFY_BASE", "http://127.0.0.1:8000")
WS_BASE = BASE.replace("http", "ws") + "/ws/"

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  —  {detail}" if detail else ""))


def main_rest(pcap_path: str) -> str:
    r = httpx.get(BASE + "/", timeout=15)
    check("GET / 返回控制台页面", r.status_code == 200 and ("控制台" in r.text or "console" in r.text.lower()), f"status={r.status_code}")

    r = httpx.get(BASE + "/api/experiment/status", timeout=10)
    check("GET status 初始 running=false", r.status_code == 200 and r.json().get("running") is False, str(r.json()))

    r = httpx.get(BASE + "/api/experiment/defaults", timeout=10)
    d = r.json() if r.status_code == 200 else {}
    check("GET defaults 单源默认值", r.status_code == 200 and {"target_ip", "max_iters", "no_improve_limit"} <= set(d), str(d))

    r = httpx.post(BASE + "/api/experiment/start", json={"target_ip": "10.99.80.160", "max_iters": 0}, timeout=10)
    check("POST start max_iters=0 → 400 中文", r.status_code == 400 and "≥1" in r.json().get("error", ""), r.text[:120])

    r = httpx.post(BASE + "/api/experiment/start", json={"target_ip": "10.99.80.160", "max_iters": 1, "no_improve_limit": 1}, timeout=10)
    check("POST start 合法参数 → success", r.status_code == 200 and r.json().get("success") is True, str(r.json()))

    r = httpx.post(BASE + "/api/upload/pcap", files={"file": ("evil.txt", b"not a pcap", "text/plain")}, timeout=10)
    check("POST upload 非白名单扩展名 → 400", r.status_code == 400 and "不支持" in r.json().get("error", ""), r.text[:120])

    with open(pcap_path, "rb") as f:
        r = httpx.post(BASE + "/api/upload/pcap",
                       files={"file": ("verify.pcap", f, "application/vnd.tcpdump.pcap")}, timeout=30)
    j = r.json() if r.status_code == 200 else {}
    check("POST upload 合法 pcap → success+path", r.status_code == 200 and j.get("success") and j.get("file_path"), str(j)[:150])
    return j.get("file_path", "")


async def ws_experiment(uploaded_path: str) -> None:
    """真实 LLM 实验：start → 收消息 → HITL 出现时先让非所有者试批 → 所有者拒绝 → done。"""
    uri = WS_BASE + "watchdog-owner"
    hitl_seen = asyncio.Event()
    hitl_payload = {}

    async with websockets.connect(uri) as ws:
        m = json.loads(await asyncio.wait_for(ws.recv(), 15))
        check("WS 连接握手 status=connected",
              m.get("type") == "status" and m["data"].get("status") == "connected", str(m)[:120])

        await ws.send(json.dumps({
            "type": "start_experiment",
            "data": {"target_ip": "10.99.80.160", "max_iters": 1, "no_improve_limit": 1,
                     "pcap_path": uploaded_path or ""},
        }))

        seen_types = set()
        got_hitl = False
        got_done = False
        got_error = None
        hitl_payload_box = {}

        async def intruder_probe():
            """非所有者 client 在 HITL 窗口内尝试审批 → 应收到 error 且不影响实验。"""
            await asyncio.wait_for(hitl_seen.wait(), 120)
            try:
                async with websockets.connect(WS_BASE + "watchdog-intruder") as bws:
                    await bws.recv()  # connected
                    await bws.send(json.dumps({"type": "hitl_response", "data": {"approved": True}}))
                    resp = json.loads(await asyncio.wait_for(bws.recv(), 15))
                    check("007-2 非所有者审批被拒（error 非会话所有者）",
                          resp.get("type") == "error" and "非会话所有者" in resp["data"].get("message", ""),
                          str(resp)[:150])
            except Exception as e:
                check("007-2 非所有者审批被拒", False, f"intruder 异常: {type(e).__name__} {str(e)[:120]}")

        probe_task = asyncio.create_task(intruder_probe())

        try:
            while not got_done and not got_error:
                try:
                    raw = await asyncio.wait_for(ws.recv(), 180)
                except asyncio.TimeoutError:
                    break
                msg = json.loads(raw)
                t = msg.get("type")
                seen_types.add(t)
                if t == "hitl_request":
                    got_hitl = True
                    hitl_payload_box.update(msg.get("data", {}))
                    hitl_seen.set()
                    await asyncio.sleep(1.5)  # 给 intruder 探针窗口
                    await ws.send(json.dumps({"type": "hitl_response", "data": {"approved": False}}))
                elif t == "experiment_done":
                    got_done = True
                elif t == "error":
                    got_error = msg["data"].get("message", str(msg))

            await probe_task
        finally:
            if not probe_task.done():
                probe_task.cancel()

        data = hitl_payload_box
        check("实验期间收到 hitl_request（统一结构 message+params）",
              got_hitl and "message" in data and "params" in data, str(data)[:200])
        check("实验结束收到 experiment_done", got_done, f"seen_types={sorted(seen_types)}")
        check("无 error 消息", got_error is None, str(got_error)[:150])
        check("收到 LLM 消息流（messages）", "messages" in seen_types, f"seen_types={sorted(seen_types)}")

        # 结束后状态复位 + 无残留监控进程
        await asyncio.sleep(1)
        r = httpx.get(BASE + "/api/experiment/status", timeout=10)
        check("结束后 status running=false", r.status_code == 200 and r.json().get("running") is False, str(r.json()))


def residual_check():
    import subprocess
    out = subprocess.run(["pgrep", "-fl", "ping|fping"], capture_output=True, text=True).stdout.strip()
    mine = [ln for ln in out.splitlines() if ln and "pgrep" not in ln and "verify" not in ln]
    check("无残留 ping/fping 进程（R7 Web 端清理）", not mine, mine[:3] if mine else "无")


def main():
    from scapy.all import IP, UDP, Raw, wrpcap
    pcap = "/tmp/watchdog_verify.pcap"
    wrpcap(pcap, [IP(src="10.1.1.1", dst="10.99.80.160") / UDP(sport=12345 + i, dport=53) / Raw(b"x" * 64)
                  for i in range(10)])

    uploaded = main_rest(pcap)
    asyncio.run(ws_experiment(uploaded))
    residual_check()

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n===== 结果: {passed}/{len(results)} 项通过 =====")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
