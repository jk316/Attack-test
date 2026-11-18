# 契约：RTT 观测输出（build_rtt_observation）

**特性**: `specs/003-ping-monitor-rtt/` | **消费者**: 所有流量工具结果（Scapy / Pktgen / TRex）与 LLM 决策 | **日期**: 2026-11-19

定义每次攻击动作结束后附加到工具结果上的观测 JSON。LLM 被要求先检查 `covers_attack_window`，为 false 时不得把本观测用作决策依据。

## 1. 顶层结构

```json
{
  "rtt_during": { ... } | null,
  "attack_window": { ... },
  "observation_window": { ... }
}
```

三个键必须**始终存在**；`rtt_during` 在无数据时为 null（不得省略）。

## 2. attack_window

| 字段 | 类型 | 约束 |
|------|------|------|
| `start` / `end` | `{ "ts": number, "iso": "YYYY-MM-DD HH:MM:SS" }` | 攻击开始时刻（t0）与观测构造时刻；同一时钟源 |
| `duration_s` | number | `end.ts − start.ts`，保留 3 位小数 |
| `mode` | string | 执行模式标注（`scapy` / `live` / `dry_run` 等） |

## 3. observation_window

| 字段 | 类型 | 约束 |
|------|------|------|
| `sample_count` | integer ≥ 0 | t0 之后样本数 |
| `first_sample` / `last_sample` | 时间点对象 \| null | 窗口内首/末样本时刻；无样本为 null |
| `covers_attack_window` | boolean | 见下方判定规则 |
| `note` | string（非空） | 诊断说明：未覆盖原因，或覆盖概况（含收发与丢失） |

## 4. rtt_during

| 字段 | 类型 | 约束 |
|------|------|------|
| `samples` | MonitorSample 数组 | t0 之后、时间先后（形状见 contracts/monitor-sample.md） |
| `avg_rtt_ms` / `min_rtt_ms` / `max_rtt_ms` | number | 仅统计收到的探测，按收到数加权 |
| `loss_pct` | number（0–100） | `(1 − total_received/total_sent) × 100` |
| `total_sent` / `total_received` | integer | 窗口内收发总数 |

## 5. covers_attack_window 判定规则（顺序判定，命中即返回）

| # | 条件 | 判定 | note 要求 |
|---|------|------|----------|
| 1 | 监控未运行 | false | 提示「先调用 start_ping_monitor，本结果不可用于规划」 |
| 2 | 窗口内 0 个样本 | false | 说明攻击时长过短或目标无回应，建议增大 duration 或重跑 |
| 3 | 全部探测丢失（received 全 0） | false | 说明全部丢失与 loss=100%，目标可能不可达或被阻断 |
| 4 | `duration_s < 1.0`（窗口过短） | false | 说明窗口过短（如 dry-run / duration=0 未等待） |
| 5 | 其余（有样本、有收到、窗口 ≥ 1 s） | true | 覆盖概况：收发总数与丢包率；loss ≥ 50% 时追加「丢包严重——这本身就是有效攻击信号」 |

**不变式**:
- `rtt_during != null` ⇒ `covers_attack_window == true`（未覆盖的观测不携带可被误用的聚合数据）。
- 任何未覆盖场景的 `note` 必须包含不可信原因，且不得出现暗示数据有效的表述。

## 6. 完整示例（正常覆盖）

```json
{
  "rtt_during": {
    "samples": [
      { "ts": 1764080010.100, "rtt_ms": 4.2, "sent": 1, "received": 1 },
      { "ts": 1764080010.350, "rtt_ms": 8.9, "sent": 1, "received": 1 },
      { "ts": 1764080010.600, "rtt_ms": null, "sent": 1, "received": 0 }
    ],
    "avg_rtt_ms": 6.55,
    "min_rtt_ms": 4.2,
    "max_rtt_ms": 8.9,
    "loss_pct": 33.3,
    "total_sent": 3,
    "total_received": 2
  },
  "attack_window": {
    "start": { "ts": 1764080010.0, "iso": "2026-11-19 01:35:10" },
    "end": { "ts": 1764080015.2, "iso": "2026-11-19 01:35:15" },
    "duration_s": 5.2,
    "mode": "scapy"
  },
  "observation_window": {
    "sample_count": 3,
    "first_sample": { "ts": 1764080010.1, "iso": "2026-11-19 01:35:10" },
    "last_sample": { "ts": 1764080010.6, "iso": "2026-11-19 01:35:10" },
    "covers_attack_window": true,
    "note": "观测窗口已覆盖攻击窗口，共 3 个探测（收到 2，丢包 33.3%）。"
  }
}
```

## 7. 未覆盖示例（监控未运行）

```json
{
  "rtt_during": null,
  "attack_window": {
    "start": { "ts": 1764080020.0, "iso": "2026-11-19 01:35:20" },
    "end": { "ts": 1764080022.0, "iso": "2026-11-19 01:35:22" },
    "duration_s": 2.0,
    "mode": "scapy"
  },
  "observation_window": {
    "sample_count": 0,
    "first_sample": null,
    "last_sample": null,
    "covers_attack_window": false,
    "note": "ping monitor 未运行——无 RTT 观测，请先调用 start_ping_monitor，本结果不可用于规划。"
  }
}
```
