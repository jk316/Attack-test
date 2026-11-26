# 实验日志 Schema（canonical experiment log schema）

`data/experiment.jsonl` 每行一条实验记录，由 `log_result` 工具经
`src/tools/log_tool.py::canonicalize_entry()` 规范化后写入。
**LLM 传入的参数是自由格式，落盘前会被规范化**——因此无论 LLM 怎么填，
每行的字段都是统一、可查询、可对比的。

## 顶层字段（固定顺序）

| 字段 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `run_id` | string | 自动注入 | 每次实验运行唯一 id（`YYYYmmddTHHMMSS-hex6`）；旧数据迁移为 `legacy-<ts>-NN` |
| `iteration` | int | LLM | run 内迭代序号（从 1 起，仅在同一 `run_id` 内有意义） |
| `tool` | string | LLM / 自动注入 | 产生本行的攻击工具名；LLM 漏填时由 `ToolTaggerMiddleware` 注入最近一次工具调用名，兜底 `"unknown"` |
| `params` | object | LLM → 规范化 | 规范化后的**输入参数**（见下） |
| `results` | object | LLM / 自动剥离 | 本迭代**实测结果指标**（吞吐、实际 pps、备注等） |
| `rtt` | float | LLM | 平均 RTT（毫秒） |
| `loss` | float | LLM | 丢包率（百分比） |
| `timestamp` | string(ISO8601) | 自动注入 | 写入时间（UTC） |

JSON Schema（顶层）：

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["run_id", "iteration", "tool", "params", "rtt", "loss", "timestamp"],
  "properties": {
    "run_id": {"type": "string"},
    "iteration": {"type": "integer", "minimum": 1},
    "tool": {"type": "string"},
    "params": {"$ref": "#/$defs/params"},
    "results": {"type": "object"},
    "rtt": {"type": "number"},
    "loss": {"type": "number"},
    "timestamp": {"type": "string", "format": "date-time"}
  },
  "$defs": {
    "params": {
      "type": "object",
      "properties": {
        "target_ip": {"type": ["string", "null"]},
        "dst_port": {"type": ["integer", "null"]},
        "duration_ms": {"type": ["number", "null"]},
        "pkt_size": {"type": ["integer", "null"]},
        "pps": {"type": ["number", "null"]},
        "rate_pct": {"type": ["number", "null"]},
        "protocol": {"type": ["string", "null"]},
        "extras": {"type": "object"}
      }
    }
  }
}
```

## `params` 统一输入参数（canonical 字段）

| 字段 | 语义 | 备注 |
|------|------|------|
| `target_ip` | 目标 IP | 别名 `dst_ip/target/ip/dest_ip/dst` 均归一到这里 |
| `dst_port` | 目标端口 | 别名 `dport/port/dest_port/target_port` |
| `duration_ms` | 攻击时长（**毫秒**） | `duration_s` 自动 ×1000；无单位 `duration` **不猜测**，原样保留到 `extras` |
| `pkt_size` | 包大小（字节） | 别名 `packet_size/pktSize/packet_len` |
| `pps` | 包速率（packets/s） | 别名 `total_pps`；Scapy/TRex 语义 |
| `rate_pct` | Pktgen 端口线速百分比（0-100） | **仅 Pktgen 工具**：`rate` 只在 `tool` 以 `pktgen` 开头时归入这里，避免与 `pps` 语义混淆 |
| `protocol` | 协议 | 别名 `proto` |
| `extras` | 工具特有参数 | `tcp_flags`（别名 `flags`）、`scan_field`、`arp_type`、`streams`、`flow_count`、`iat_jitter_ms`、`mode`、`ttl` 等；未识别键一律保留于此，**不丢数据** |

固定键（`target_ip` … `protocol`）恒存在，值为 `null` 表示该工具没有此参数；
`extras` 为空时省略。

## `results` 实测指标

从 `params` 中自动剥离的"运行期结果"键：`tx_gbps`、`tx_util`、
`port_util_pct`、`pps_actual`、`pps_requested`、`pps_each`、`pps_per_port`、
`achieved_pps`、`payload_b`、`frame_b`、`static_no_vm`、`elapsed_s`、
`returncode`、`success`、`error`、`status`、`note(s)`，
以及历史数据中 LLM 凭空编造的测量键（`dl_bytes`、`syn_pps`、`conn_per_sec` 等）。
LLM 通过 `log_result` 的 `results` 参数显式传入的指标同样合并到这里。

## 规范化规则（canonicalizer 摘要）

实现：`src/tools/log_tool.py`

1. 别名归一：按上表别名映射到 canonical 名（先匹配先得，匹配后从原 dict 移除）。
2. 单位统一：`duration_s` → `duration_ms`（×1000）；无单位字段不猜。
3. 语义隔离：`rate` 仅 Pktgen 工具 → `rate_pct`；其余工具的 `rate` 留 `extras`。
4. 结果剥离：`_RESULT_KEYS` 中的键从 `params` 移入 `results`。
5. 兜底保留：任何未识别键进 `params.extras`，绝不丢弃。
6. 自动注入：`run_id`（env `DSH_RUN_ID`，启动时由 `main.py` /
   `backend/experiment.py` 生成）、`tool`（`ToolTaggerMiddleware` 注入最近
   工具调用名）、`timestamp`。

## 调用方契约

- **LLM**：`log_result` 的 docstring 与系统提示（`system_prompt.j2`
  "日志记录规范"）要求按 canonical 字段名填写 `params`，实测指标放
  `results`，`tool` 必填。
- **代码**：`src/agent/tools.py::log_result` 接受可选 `tool`/`results`
  参数；`src/tools/log_middleware.py::ToolTaggerMiddleware` 在 graph 层
  自动补 `tool`。

## 历史数据

旧数据（2026-11 之前的自由格式）用
`scripts/normalize_experiment_log.py` 一次性迁移到
`data/experiment.normalized.jsonl`：按 iteration 回退切分 run、按参数字段
形状推断工具名、复用同一 canonicalizer。原始文件不动。
