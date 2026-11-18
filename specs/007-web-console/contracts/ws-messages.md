# 契约：WebSocket 消息协议（/ws/{client_id}）

**特性目录**: `specs/007-web-console/` | **日期**: 2026-11-19 | **对应 FR**: FR-002~FR-014、FR-019

## 总则

- 传输：每条消息为单个 JSON 文本帧；格式 `{"type": string, "data": object}`。
- 通道：`/ws/{client_id}`；client_id 由前端生成（随机 8 位），服务端在连接确认中回显。
- 单客户端会话模型（007-2）：`hitl_response`、`stop_experiment` 仅会话所有者（发起实验的 client_id）的消息被接受，其他客户端的此类消息返回 error 且不改变实验状态。
- 顺序保证：同一实验内，服务端推送顺序 = 产生顺序；每个 `hitl_request` 恰好对应一个 `hitl_response` 回显与一次决定消费。
- 错误处理：无法解析的 JSON → error（"无效的 JSON"）；未知 type → error（"未知消息类型: …"）；错误消息不影响实验状态。

## 客户端 → 服务端

### start_experiment（启动实验）

```json
{
  "type": "start_experiment",
  "data": {
    "target_ip": "100.1.11.20",
    "pcap_path": "data/uploads/ab12cd34_sample.pcap",
    "log_path": "data/experiment.jsonl",
    "max_iters": 20,
    "no_improve_limit": 5
  }
}
```

| 字段 | 类型 | 必填 | 校验 |
|------|------|:---:|------|
| target_ip | string(IPv4) | 是 | 非空；实际发送时经 allowlist 校验（008-security-config） |
| pcap_path | string | 否 | 空 = 不使用画像；非空应来自上传接口返回的路径 |
| log_path | string | 否 | 默认 data/experiment.jsonl |
| max_iters | int | 否 | ≥1；默认取 experiment.json |
| no_improve_limit | int | 否 | ≥1；默认取 experiment.json |

响应（服务端 → 客户端）：先推送 `status`（starting，含 thread_id）；若本会话已有运行中实验 → `error`（"实验已在运行中，请先停止当前实验"）。

### hitl_response（审批决定）

```json
{ "type": "hitl_response", "data": { "approved": true } }
```

- `approved`: bool，必填。true=批准继续；false=拒绝（该次工具调用中止）。
- 非会话所有者发送 → error（"非会话所有者"），决定被忽略。
- 同一审批请求的第二次决定 → 忽略（每请求恰好消费一次）。

### stop_experiment（停止实验）

```json
{ "type": "stop_experiment" }
```

- 语义：请求优雅停止当前实验；审批等待中收到停止请求时，停止优先（向队列注入拒绝值终结阻塞）。
- 非会话所有者发送 → error。

## 服务端 → 客户端

| type | data 结构 | 时机 |
|------|----------|------|
| status | `{"status": "connected", "client_id": "ab12cd34"}` 或 `{"status": "starting", "thread_id": "9f8e7d6c"}` | 连接建立后立即 / 实验启动时 |
| messages | `[{"role": "ai", "content": "…", "tool_calls": [{"name": "…", "args": {…}}]}]` | Agent 产生新推理消息（数组可含多条） |
| tool_result | `{"role": "tool", "content": "…", "tool_calls": null}` | 工具执行结束 |
| hitl_request | `{"message": "[HITL] Approve traffic send?", "params": {"dst_ip": "…", "pps": 100, "…"}}` | Agent 在流量工具处暂停（与 008-security-config 统一审批契约对齐） |
| hitl_response | `{"approved": true}` | 服务端回显已消费的决定 |
| experiment_done | `{"message": "实验已结束"}` 或 `{"summary": "…（≤2000 字符）"}` | 实验结束/异常后的最终推送 |
| error | `{"message": "…"}` | 无效 JSON、未知类型、参数错误、运行异常等 |

## 字段渲染与转义约束

- 前端渲染 `content`/`message` 前必须做 HTML 转义（防注入）；工具调用徽章参数截断展示（≤60 字符）。
- 展示截断：AI 消息内容 ≤1000 字符、工具结果 ≤300 字符、摘要 ≤2000 字符（服务端推送全量或按上述截断，契约要求：截断不得发生在 RTT 观测数值字段上）。

## 兼容性说明（008 联动）

- `hitl_request.data` 的完整统一结构见 `specs/008-security-config/contracts/hitl-payload.md`；服务端 `_extract_hitl` 依赖 `message` 键定位审批信息，统一后保持不变。
