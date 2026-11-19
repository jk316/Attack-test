# 契约：统一 HITL 审批内容（interrupt payload）

**特性目录**: `specs/008-security-config/` | **日期**: 2026-11-19 | **对应 FR**: FR-008/FR-009/FR-010 | **决议**: 008-3

## 定位

所有 `interrupt()` 调用点（CLI 与 Web 共用同一执行流）必须遵守本统一结构；CLI 的 `_extract_hitl_payload` 与 Web 的 `_extract_hitl` 均依赖 `message` 键，统一后两者无需感知工具类型（007 联动）。

## 统一结构

```json
{
  "message": "[HITL] Approve traffic send?",
  "params": { "…": "完整参数快照" },
  "scope": "scapy_traffic | pktgen_traffic | trex_script"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| message | string | 是 | 人类可读审批提示；CLI 打印此值、Web 弹窗标题/正文用此值 |
| params | object | 是 | 该次发送的完整参数明细（钳制后的生效值；拒绝时同样展示） |
| scope | enum | 是 | 风险类别，供呈现层与未来分级展示使用 |

## 各调用点契约（现状 → 统一后）

### 1. src/agent/tools.py · traffic_send（scope: scapy_traffic）

```json
{
  "message": "[HITL] Approve traffic send?",
  "params": { "dst_ip": "…", "dst_port": 5201, "duration_s": 10, "pps": 100,
              "packet_size": 64, "flow_count": 1, "iat_jitter_ms": 0 },
  "scope": "scapy_traffic"
}
```

现状：仅 message+params（少 scope）→ 补 scope 字段。

### 2. src/agent/tools.py · mixed_traffic_send（scope: scapy_traffic）

```json
{
  "message": "[HITL] Approve mixed traffic send?",
  "params": { "dst_ip": "…", "duration_s": 10, "pps": 100, "stream_count": "…" },
  "scope": "scapy_traffic"
}
```

现状：message+params 不含流数明细 → 统一时 params 增加流量规格摘要（流数/协议构成，完整 spec 可截断展示）。

### 3. src/pktgen/adapter.py · _hitl_gate（scope: pktgen_traffic）

```json
{
  "message": "[HITL] Approve Pktgen 'udp_flood' execution?",
  "params": { "skill": "udp_flood", "dst_ip": "…", "rate": 50, "duration": 10000,
              "mode": "live", "…其余技能参数" },
  "scope": "pktgen_traffic"
}
```

现状：message+params+顶层 mode → 统一后 mode 移入 params（或保留顶层但不新增其它顶层键；tasks 阶段以最小改动确定，message/params/scope 三键必须存在）。

### 4. src/trex/tools.py · _execute_live（scope: trex_script）

```json
{
  "message": "[HITL] Approve executing a generated Python script?",
  "params": {
    "filename": "cat_dns_amp.py", "path": "trex_scripts/cat_dns_amp.py",
    "target_ip": "…", "detected_ips": ["…"],
    "code_preview": "…（≤500 字符）",
    "warning": "此脚本将以本机当前用户完整权限执行任意 Python（无执行沙箱）……静态 IP 扫描为尽力而为，无法识别域名/拼接/编码构造的目标，请人工审阅脚本内容。"
  },
  "scope": "trex_script"
}
```

现状：已有 filename/path/target_ip/detected_ips/code_preview/warning → 补 scope 字段 + warning 增加「静态扫描非硬边界」声明（G3）。

## 语义规则

1. **决定**: `Command(resume=<bool>)`；true=继续，false=中止该次发送（工具返回 `{"success": false, "error": "HITL rejected by operator"}` 语义）。
2. **dry-run 豁免**: Pktgen/TRex dry-run 不触发 interrupt（无流量无审批）；Scapy 工具无 dry-run 概念，每次必审。
3. **--auto-approve**: 仅 CLI 且不与实发组合（G1 互斥）；自动批准时必须打印标记「Auto-approved (--auto-approve)」（FR-017）。
4. **顺序保证**: 每次 interrupt 恰好对应一次决定消费（CLI 单次 input；Web 队列单次 get + 所有者校验，见 007 contracts/ws-messages.md）。
5. **呈现截断**: params 内大字段（code_preview、完整 traffic spec）可截断展示，但数值型安全参数（目标/端口/速率/时长）不得截断。

## 007 联动

Web 端 `_extract_hitl` 定位规则保持「dict 且含 message 键」；统一后 hitl_request.data 即本结构原样透传（params 含 scope），前端弹窗展示 message + params 明细即可，无需分支。
