# 契约：experiment.json 配置（默认参数单一来源）

**特性目录**: `specs/008-security-config/` | **日期**: 2026-11-19 | **对应 FR**: FR-013/FR-014/FR-015/FR-020

## 定位

`src/config/experiment.json` 是**默认参数**的单一事实来源（宪法六）。它不包含、也不允许包含**上限**——上限为宪法级常量（见 data-model.md「安全策略」），恒为最终裁决层。

## JSON Schema

```json
{
  "target_ip": "100.1.11.20",
  "pcap_path": "",
  "log_path": "data/experiment.jsonl",
  "max_iters": 20,
  "no_improve_limit": 5,
  "attack": {
    "duration_s": 10,
    "pps": 100,
    "packet_size": 64,
    "flow_count": 1,
    "iat_jitter_ms": 0
  },
  "pktgen": {
    "rate": 50,
    "duration_ms": 10000
  },
  "trex": {
    "timeout_s": 30
  },
  "profiles": {
    "high_pps": { "attack": { "pps": 2000, "duration_s": 5 } },
    "long_run": { "max_iters": 40, "attack": { "duration_s": 20, "pps": 500 } },
    "pktgen_max": { "pktgen": { "rate": 100, "duration_ms": 30000 } }
  }
}
```

## 字段表与校验规则

| 字段 | 类型 | 默认值约定 | 上限（常量，不可放宽） |
|------|------|-----------|----------------------|
| target_ip | string(IPv4) | 必填 | 运行时须 ∈ allowlist |
| pcap_path | string | "" | — |
| log_path | string | data/experiment.jsonl | — |
| max_iters | int | 20 | 正整数（无宪法上限） |
| no_improve_limit | int | 5 | 正整数 |
| attack.duration_s | int | 10 | ≤ 20（MAX_DURATION_S） |
| attack.pps | int | 100 | ≤ 20000（MAX_PPS） |
| attack.packet_size | int | 64 | ≤ 1024（MAX_PACKET_SIZE） |
| attack.flow_count | int | 1 | ≤ 100（MAX_FLOW_COUNT） |
| attack.iat_jitter_ms | int | 0 | ≤ 20（MAX_IAT_JITTER_MS） |
| pktgen.rate | number | 50 | 0 ≤ rate ≤ 100（%） |
| pktgen.duration_ms | int | 10000 | ≤ 60000 |
| trex.timeout_s | number | 30 | (0, 300]（trex/config.py 已钳制） |
| profiles.<name> | object | 覆盖任一字段组 | 与基础配置同规则 |

## 语义规则

1. **优先级链**: 显式 CLI 参数 > profiles 预设 > 基础配置 > 工具签名 fallback（FR-014）。
2. **超限处置**（008-2 决议）: 配置默认值超过上限 → 启动时逐项 WARN（字段/配置值/钳制后上限值），工具内照常钳制；**不报错退出**。
3. **未知 profiles**: 报错并列出全部可用预设名。
4. **未知顶层键**: 忽略（向后兼容）；不新增除上表外的字段语义。
5. **生效方式**: main.py 加载 → 注入环境变量（ATK_* / PKTGEN_* / TREX_*）→ 工具调用时读取；Pktgen 工具默认值接入 env 注入链由 008 计划 G4 补齐。
6. **重载**: 进程内加载一次，运行期修改需重启生效（007 的 /api/experiment/defaults 同理）。

## 与 007 的联动

007-web-console 的启动参数默认值（target_ip/max_iters/no_improve_limit）与前端表单初值均取自本文件（单一来源），不得另立默认值表。
