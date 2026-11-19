# 契约：监控样本与查询接口

**特性**: `specs/003-ping-monitor-rtt/` | **消费者**: Agent 工具层、`rtt_window.build_rtt_observation` | **日期**: 2026-11-19

本文档定义监控样本（MonitorSample）与两个查询接口返回值的 JSON 形状。字段名与语义是对既有实现的固化，实施不得破坏；新增字段须向后兼容（只增不改）。

## 1. MonitorSample（样本条目）

`get_samples_since(timestamp)` 返回的列表元素；`build_rtt_observation` 的 `rtt_during.samples` 复用同构。

```json
{
  "ts": 1764080000.123,
  "rtt_ms": 5.7,
  "sent": 10,
  "received": 8
}
```

| 字段 | 类型 | 约束 |
|------|------|------|
| `ts` | number | 解析时刻（秒）；查询结果按 `ts` 严格递增（时间先后） |
| `rtt_ms` | number \| null | 毫秒；`received == 0` 时必须为 null（丢失不得记为 0 ms） |
| `sent` | integer ≥ 1 | 逐探测后端为 1；fping -Q 周期为该周期探测数 |
| `received` | integer ≥ 0 | ≤ `sent`；0 表示该条目无成功探测 |

**丢失样本示例**（系统 ping 超时行 / fping 超时行）:

```json
{ "ts": 1764080001.456, "rtt_ms": null, "sent": 1, "received": 0 }
```

## 2. 窗口聚合查询（get_stats）

| 字段 | 类型 | 约束 |
|------|------|------|
| `monitor_active` | boolean | 监控未运行必须为 false，且计数全 0、`loss_pct=100` |
| `target_ip` | string \| null | 当前目标；未运行可保留上次目标或 null |
| `latest_rtt_ms` | number \| null | 缓冲内最新一条的 RTT（可为 null） |
| `avg_rtt_ms` / `min_rtt_ms` / `max_rtt_ms` | number | 仅统计窗口内收到的探测；fping -Q 周期样本按其 `received` 加权 |
| `sample_count` | integer | 窗口内**收到**探测总数（加权求和后） |
| `sent_count` | integer | 窗口内发送探测总数 |
| `loss_pct` | number（0–100） | `(1 − received_total/sent_total) × 100`；无发送时为 0；未运行时为 100 |
| `window_s` | number | 查询窗口时长（秒） |
| `backend` | string | `fping_q` \| `ping`（当前运行后端；未运行时为上次所用后端） |

**示例**（fping -Q 运行 1 秒窗口）:

```json
{
  "monitor_active": true,
  "target_ip": "10.99.80.160",
  "latest_rtt_ms": 6.1,
  "avg_rtt_ms": 5.703,
  "min_rtt_ms": 2.1,
  "max_rtt_ms": 12.3,
  "sample_count": 8,
  "sent_count": 10,
  "loss_pct": 20.0,
  "window_s": 1.0,
  "backend": "fping_q"
}
```

## 3. 时间戳采样查询（get_samples_since）

返回 `timestamp` 之后（严格 `ts > timestamp`）的样本数组，时间先后排序；空窗口返回 `[]`。

```json
[
  { "ts": 1764080000.123, "rtt_ms": 5.7, "sent": 1, "received": 1 },
  { "ts": 1764080000.456, "rtt_ms": null, "sent": 1, "received": 0 }
]
```

## 4. 语义约束（供实现与测试）

1. 加权口径一致：fping -Q 周期样本（sent/received > 1）在聚合中按 `received` 加权，保证与逐探测后端可比。
2. 线程安全：查询与采集并发，返回的数组必须是某一时刻的一致快照（不出现半条样本）。
3. 缓冲有界：容量可配置（默认 4000），写满淘汰最旧；查询接口不暴露缓冲容量细节。
4. 时间戳同源：`ts` 与攻击开始时刻 t0 均为同一时钟源（epoch 秒），可直接比较。
