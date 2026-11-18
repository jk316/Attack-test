# 契约：Pktgen 适配器工具结果结构

**特性目录**: `specs/005-pktgen-integration/` | **日期**: 2026-11-19

**契约性质**: 描述 9 个 Pktgen 工具对 Agent（LLM）返回结果的统一结构。现状已实现大部分字段；`replaced_mac` 为计划缺口 G5 的新增字段。

## 1. 成功结果（示例，dry-run）

```json
{
  "success": true,
  "skill": "udp_flood",
  "params": {"dst_ip": "10.99.80.160", "rate": 50, "duration": 5000},
  "mode": "dry_run",
  "summary": "Pktgen 'udp_flood' succeeded (dry_run mode).",
  "artifacts": {
    "lua_script": "lua_scripts/20261119_120000_udp_flood.lua",
    "lua_preview": "package.path = package.path ..\";?.lua...（截断至 200 字符）"
  },
  "rtt_during": { "...": "见数据模型实体 5" },
  "attack_window": {"start": 1763520000.0, "end": 1763520000.0, "mode": "dry_run"},
  "observation_window": {"first": null, "last": null, "covers_attack_window": false}
}
```

## 2. 字段契约

| 字段 | 类型 | 出现条件 | 说明 |
|------|------|---------|------|
| success | bool | 总是 | 编译/下发是否成功 |
| skill | string | 总是 | 技能名 |
| params | dict | 总是 | 剥离 None 后的实际参数 |
| mode | enum | 总是 | `dry_run` \| `live` \| `unknown`（异常兜底） |
| summary | string | 总是 | 单行可读摘要（见第 4 节分类规则） |
| error | string | 失败时 | 原始错误信息 |
| artifacts | dict | 编译成功时 | `{lua_script, lua_preview}`；脚本全文不进结果（截断 200 字符） |
| response | string | live 成功时 | 硬件 TCP 响应 |
| replaced_mac | list | packet_sequence 且发生替换时（**G5 新增**） | `[{"index": 0, "from": "00:00:00:00:00:01", "to": "f0:c4:78:4c:a5:55"}]` |
| rtt_during | dict | 提供了 dst_ip 时 | 窗口内 RTT 采样与聚合 |
| attack_window | dict | 提供了 dst_ip 时 | `{start, end, mode}`；end=start+实际等待（live，封顶 60s） |
| observation_window | dict | 提供了 dst_ip 时 | `{first, last, covers_attack_window}`；ping 未启动时字段为空、覆盖标志 false |

## 3. 失败结果形态

```json
// 参数校验失败（G1/G3 及编译错误）
{"success": false, "skill": "udp_flood", "error": "duration 120000 exceeds maximum 60000 ms", "mode": "unknown"}
// allowlist 失败
{"success": false, "error": "Target 192.168.1.99 not in allowlist"}
// HITL 拒绝（live）
{"success": false, "error": "HITL rejected by operator"}
// 连接失败
{"success": false, "skill": "udp_flood", "error": "Connection failed: Failed to connect to Pktgen at 10.99.80.222:22022: ...", "mode": "live"}
```

## 4. summary 分类规则（LLM 决策依据）

| 触发特征 | summary 文案 | Agent 建议恢复路径 |
|---------|-------------|------------------|
| success=true | `Pktgen '<skill>' succeeded (<mode> mode).` | 继续优化循环 |
| 错误含 "Connection" | `Pktgen '<skill>' failed: Pktgen unreachable — fall back to Scapy tools.` | 回落 Scapy 工具 |
| 错误含 CompileError/required/参数校验 | `Pktgen '<skill>' failed: parameter error — <error>` | 修正参数后重试 |
| 其他 | `Pktgen '<skill>' failed: <error>` | 按 error 原文判断 |

## 5. 契约不变量（可测试口径）

1. 结果必须包含 `success` 与 `mode` 字段（FR-015）。
2. 编译成功后 `artifacts.lua_script` 指向真实存在的审计文件（FR-014）。
3. `lua_preview` 长度 ≤200 字符（超长追加 `...`）。
4. HITL 拒绝、allowlist 拒绝、参数拒绝三类失败均在发送任何流量前返回。
5. `replaced_mac` 仅当实际发生替换时出现，且与日志记录一致（G5）。
6. live 成功结果的 `attack_window.end - start` ≤ 60s（FR-009）。
