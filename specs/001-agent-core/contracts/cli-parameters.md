# 契约：CLI 参数 — 核心闭环 ReAct Agent 与运行模式

**特性**: `specs/001-agent-core/` | **日期**: 2026-11-19

## 1. 参数优先级链

```
CLI 参数  >  命名预设（--profile）  >  experiment.json  >  内置默认
```

- 预设深合并覆盖 `attack` / `pktgen` / `trex` 三个分组（只写变更键）。
- 所有攻击/硬件默认值经环境变量（ATK_DURATION_S / ATK_PPS / ATK_PACKET_SIZE / ATK_FLOW_COUNT / ATK_IAT_JITTER_MS / PKTGEN_RATE / PKTGEN_DURATION_MS 等）注入，工具在**调用时**读取。

## 2. 参数表

| 参数 | 类型 | 默认来源 | 说明 / 校验 |
|------|------|---------|-------------|
| `--target-ip` | str | config.target_ip | 必须 ∈ allowlist（预检）；必填实际生效 |
| `--pcap-path` | str | config.pcap_path | 可空；提供 PCAP 时提示 Agent 先做画像 |
| `--log-path` | str | config.log_path（data/experiment.jsonl） | JSONL 日志路径 |
| `--max-iters` | int | config.max_iters（20）；`--trex-explore` 时默认 40 | ≥1（预检）；未指定取配置 |
| `--no-improve-limit` | int | config.no_improve_limit（5） | ≥1（预检）；连续无改善停止阈值 |
| `--auto-approve` | flag | false | 自动批准所有 HITL（跳过交互提示） |
| `-v/--verbose` | flag | false | 控制台展示完整消息（文件始终 DEBUG 全量） |
| `--duration` | int | attack.duration_s（10） | 攻击时长秒 |
| `--pps` | int | attack.pps（100） | Scapy 发包速率 |
| `--packet-size` | int | attack.packet_size（64） | 报文负载字节 |
| `--flow-count` | int | attack.flow_count（1） | 并发流数 |
| `--pktgen-live` | flag | false | Pktgen 实发（默认 dry-run 仅编译 Lua） |
| `--pktgen-host` / `--pktgen-port` | str/int | topology.yaml | 缺省从拓扑读取 |
| `--pktgen-rate` | float | pktgen.rate（50） | 0–100 线速百分比 |
| `--pktgen-duration` | int | pktgen.duration_ms（10000） | 毫秒 |
| `--trex-live` | flag | false | TRex 实发（默认 dry-run 仅写+语法检查） |
| `--trex-host` / `--trex-port` | str/int | topology.yaml | 缺省从拓扑读取 |
| `--trex-timeout` | float | trex.timeout_s（30） | 脚本执行超时秒 |
| `--trex-explore` | flag | false | 目录探索模式（零流量零审批） |
| `--catalog-target` | int | 10 | 目录探索最少脚本数 |
| `--explore-direction` | str | "" | 探索方向自由文本（仅目录模式） |
| `--instruction` | str | "" | 实验额外目标自由文本（注入 user message 与系统提示） |
| `--profile` | str | 无 | 命名预设名；不存在 → 报错并列出可用项 |

## 3. 互斥与组合规则

| 规则 | 行为 |
|------|------|
| `--trex-explore` × `--trex-live` | 启动即报错退出（parser.error），不执行任何动作 |
| `--trex-explore` | 强制 `TREX_DRY_RUN=true`、仅目录工具集、无 HITL |
| `--profile` | 预扫描后再解析其余参数，使预设默认值参与后续参数默认 |

## 4. 退出码约定（目标态）

| 场景 | 退出码 |
|------|--------|
| 正常完成（含目录模式） | 0 |
| 启动预检失败（目标不在 allowlist / 预算非正 / 互斥组合 / 未知预设 / 缺密钥） | 非 0（≠0），stderr 输出中文原因 |

## 5. 环境变量注入表（工具读取侧）

| env | 来源 | 读取方 |
|-----|------|--------|
| ATK_DURATION_S / ATK_PPS / ATK_PACKET_SIZE / ATK_FLOW_COUNT / ATK_IAT_JITTER_MS | CLI/attack 分组 | traffic_send / mixed_traffic_send 默认值 |
| PKTGEN_RATE / PKTGEN_DURATION_MS / PKTGEN_DRY_RUN / PKTGEN_HOST / PKTGEN_PORT | CLI/pktgen 分组 | Pktgen 适配器（005 规格） |
| TREX_DRY_RUN / TREX_HOST / TREX_PORT / TREX_TIMEOUT_S / CATALOG_TARGET / EXPLORE_DIRECTION | CLI/trex 分组/目录模式 | TRex 工具（006 规格） |
| INSTRUCTION | `--instruction` | system_prompt.j2 渲染 |

## 6. 状态说明

本契约描述目标态；现状差异见 `plan.md` 实施工作清单（G3 预检待实现、G1/G2 裁决与公式待统一）。契约以本文件为单一权威，实施与测试均据此核对。
