# 快速开始：Scapy 流量工具集（端到端验证）

**特性**: `specs/002-scapy-traffic-tools/` | **日期**: 2026-11-19

## 前置条件

1. Python 3.11+、`uv sync` 安装依赖（Scapy 等）。
2. 目标 IP 位于 `src/config/allowlist.json`（测试约定：allowlist 用 `10.99.80.160`、拒绝用 `192.168.1.99`）。
3. 网络环境已获授权发送流量；单元/集成测试使用 mock 网络，不产生真实流量。

## 场景 A：工具函数直接验证（无 Agent、无 HITL）

```bash
# traffic_send：CLI 冒烟（内部直接调用，绕过 HITL 封装层）
uv run python src/tools/traffic_send_tool.py 10.99.80.160 8080 100 2

# ping_rtt：单次探测冒烟
uv run python src/tools/ping_rtt_tool.py 10.99.80.160

# log_tool：JSONL 追加冒烟
uv run python src/tools/log_tool.py data/test-experiment.jsonl
```

**预期结果**:
- traffic_send 输出 JSON：`params`（钳制后）、`packets_sent.total/per_flow`、`elapsed_s`、`effective_pps`、`send_mode` ∈ {raw, udp, scapy}。
- ping_rtt 输出 `avg_rtt_ms / loss_pct / packets_transmitted / packets_received`。
- log_tool 向日志追加一行含 `timestamp` 的 JSON，重复执行追加不覆盖。

## 场景 B：规格校验行为（单元测试驱动）

```bash
uv run pytest tests/unit/ -v          # mock 全部 I/O
uv run pytest tests/integration/ -v   # mock 网络
```

**本特性新增/补强测试的预期落点**:
- 钳制：pps=999999 → 20000 且 `clamped=["pps"]`、`requested_params.pps=999999`（SC-001、002-1）。
- 拒绝矩阵：非 allowlist / 广播 `.255` / 组播 `224.x` / src_ip 非空 / dst_port 0 与 65536 → 拒绝且 0 报文（SC-001/002）。
- HITL：审批拒绝 → 0 报文（SC-003）。
- 轮转：flow_count=5 → per_flow 覆盖 5 条流、两两之差 ≤1、源端口互异（SC-004）。
- 规格：非法五类（越白名单/流数越界/总和不 100/注入/超长/重复 id）拒绝并给原因；缺百分比补齐至 100（SC-005）。
- 占比：≥10000 报文时各流占比偏差 ≤5 个百分点（SC-006）。
- ping：全丢包 inf + loss 100；命令缺失失败（SC-007）。
- 日志：单行合法 JSON + UTC 时间戳；目录缺失失败（SC-008）。
- 文档真实性：@tool docstring 上限与常量一致（SC-009、FR-018）。

## 场景 C：经 Agent 层调用（HITL 完整链路）

```bash
uv run python src/main.py --target-ip 10.99.80.160 --max-iters 2
```

**预期结果**: Agent 提议 `traffic_send`/`mixed_traffic_send` 时出现 `[HITL]` 审批；批准后返回结果含 `rtt_during` / `observation_window.covers_attack_window` 字段；拒绝后该轮 0 报文。

## 预期结果判据（对照 SC）

| SC | 判据 |
|----|------|
| SC-001 | 越限参数 100% 钳制到上限并返回实际值；安全违规 100% 拒绝且 0 报文 |
| SC-002 | 非 allowlist/广播/组播 100% 拒绝 |
| SC-003 | HITL 拒绝轮 0 报文 |
| SC-004 | N 流覆盖 N 条流、源端口互异、流间计数差 ≤1 |
| SC-005 | 非法规格 100% 拒绝给原因；合法规格（含缺百分比）100% 可执行且总和 100 |
| SC-006 | ≥10000 报文占比偏差 ≤5 个百分点 |
| SC-007 | 可达目标 15s 内返回；全丢包 inf；命令缺失失败 |
| SC-008 | 单行合法 JSON 含 UTC 时间戳；追加不覆盖；目录缺失失败 |
| SC-009 | 对外文档上限与实际钳制 100% 一致 |
