# 契约：工具 JSON 结果（Scapy 流量工具集）

**特性**: `specs/002-scapy-traffic-tools/` | **日期**: 2026-11-19 | **对应 FR**: FR-004 / FR-008 / FR-009 / FR-015 / FR-016 / FR-019

## 1. traffic_send 成功结果

```json
{
  "success": true,
  "params": {
    "dst_ip": "10.99.80.160", "dst_port": 8080,
    "duration_s": 20, "pps": 20000, "packet_size": 1024,
    "flow_count": 100, "iat_jitter_ms": 20
  },
  "requested_params": { "duration_s": 999, "pps": 999999 },
  "clamped": ["duration_s", "pps"],
  "packets_sent": { "total": 400000, "per_flow": { "0": 4000, "1": 4000 } },
  "elapsed_s": 20.0012,
  "effective_pps": 19998.8,
  "send_mode": "raw",
  "completed": true,
  "errors": [],
  "rtt_during": { "samples": [], "avg_rtt_ms": 25.3, "loss_pct": 0.0 },
  "attack_window": { "start": {"ts": 0, "iso": ""}, "end": {"ts": 0, "iso": ""}, "duration_s": 20.0, "mode": "scapy" },
  "observation_window": { "covers_attack_window": true, "note": "" }
}
```

| 字段 | 规则 |
|------|------|
| `params` | 钳制后实际生效参数（安全违规不在此列——直接拒绝） |
| `requested_params` | 原请求值（002-1 新增） |
| `clamped` | 被钳制的字段名列表；空 = 未钳制（002-1 新增） |
| `send_mode` | 枚举 `raw` / `udp` / `scapy` |
| `completed` | 缺省 true；发送被中断 = false + `interrupt_reason`（002-3 新增） |
| 观测三字段 | 结构由 003-ping-monitor-rtt 定义；monitor 未运行时 `rtt_during` 为 null |

## 2. traffic_send 拒绝结果（安全违规 / HITL 拒绝）

```json
{ "success": false, "error": "Target 192.168.1.99 not in allowlist" }
{ "success": false, "error": "HITL rejected by operator" }
```

规则：拒绝时**不包含** `packets_sent`（语义 = 0 报文），不得附带观测字段。

## 3. mixed_traffic_send 成功结果

```json
{
  "success": true,
  "params": {
    "dst_ip": "10.99.80.160",
    "duration_s": 10, "pps": 1000, "iat_jitter_ms": 0,
    "streams": [
      {"stream_id": "udp_small", "percentage": 60},
      {"stream_id": "tcp_syn", "percentage": 40}
    ]
  },
  "requested_params": { "duration_s": 10, "pps": 1000, "iat_jitter_ms": 0 },
  "clamped": [],
  "packets_sent": { "total": 10000, "per_stream": { "udp_small": 6013, "tcp_syn": 3987 } },
  "elapsed_s": 10.0021,
  "effective_pps": 999.8,
  "raw_socket": true,
  "completed": true,
  "errors": [],
  "rtt_during": {}, "attack_window": {}, "observation_window": {}
}
```

规则：`params.streams` 反映百分比补全后的最终值；`raw_socket` 为通道布尔标记；其余同 §1（含 `requested_params`/`clamped`/`completed`/`interrupt_reason` 语义）。

## 4. ping_rtt 结果

```json
{
  "success": true,
  "avg_rtt_ms": 12.5,
  "loss_pct": 0.0,
  "packets_transmitted": 4,
  "packets_received": 4,
  "raw_output": "..."
}
```

| 场景 | 结果 |
|------|------|
| 全丢包 | `success: true`、`avg_rtt_ms: +inf`、`loss_pct: 100` |
| 超时 | `success: false`、`error: "Ping timeout expired"`、`loss_pct: 100` |
| 命令缺失 | `success: false`、`error: "ping command not found"`、`loss_pct: 100` |
| 非 allowlist | `success: false` + 校验错误（不执行探测） |

## 5. log_result 结果

```json
{ "success": true, "msg": "日志写入成功" }
{ "success": false, "error": "Directory does not exist: <父目录>" }
```

写入行（单行 JSON + UTF-8）：

```json
{"iteration": 3, "params": {"pps": 100}, "rtt": 12.5, "loss": 0.0, "timestamp": "2026-11-19T01:00:00+00:00"}
```

规则：追加写入不覆盖；`timestamp` 为 UTC ISO 8601；父目录缺失返回失败且不创建文件。

## 6. 兼容性说明

- §1/§3 中 `requested_params`、`clamped`、`completed`、`interrupt_reason` 为目标态新增字段（现状缺失，见 plan.md G1/G3）；既有消费者只读 `params` 不受影响（纯增量字段）。
- 数值上限以源码常量与宪法为准：pps=20000 / duration_s=20 / packet_size=1024 / flow_count=100 / iat_jitter_ms=20 / MAX_STREAMS=100；docstring 陈旧值（200/10/512/50）待修复（FR-018）。
- 本文件是工具返回结构的权威契约，实施与测试均据此核对。
