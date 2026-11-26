# 契约：监控生命周期与 Agent 工具集

**特性**: `specs/009-auto-start-monitors/` | **日期**: 2026-11-20

本契约定义程序侧（两个入口）与 Agent 侧的接口边界，供 speckit-tasks 与 speckit-analyze 对照。

## 1. Agent 工具集契约（本特性的可见变化）

`EXPERIMENT_TOOLS` 总数由 23 → 19。

**移除（4 个）**:

- `start_ping_monitor`
- `stop_ping_monitor`
- `start_http_monitor`
- `stop_http_monitor`

**保留（读取/单次探测，4 个）**:

- `read_ping_stats(window_s)` — 读取 ping 监控窗口统计
- `read_http_stats(window_s)` — 读取 HTTP 监控窗口统计
- `ping_rtt(ip, ...)` — 单次 ping 探测
- `http_probe(url, method, timeout_s)` — 单次 HTTP 拨测

**不变**: 其余 15 个工具（Scapy 4：`pcap_profile` / `traffic_send` / `mixed_traffic_send` / `log_result`；Pktgen 9；TRex 2）名称、参数、语义不变。核对：23 − 4（移除）− 4（保留的读取/探测）= 15。

## 2. 生命周期契约（程序侧）

| 时机 | 行为 |
|------|------|
| 实验开始前（CLI 预检通过后 / Web 控制台 `start()` 内） | 自动启动 ping 监控（目标 = 有效目标 IP，CLI 参数优先）；`http.url` 非空时自动启动 HTTP 监控 |
| `--trex-explore` 目录模式 | 不启动任何监控 |
| 重复启动（同进程再次 start） | 幂等：先停旧实例再启动 |
| 实验结束 / 异常 / 中断 / 进程退出 | 停止两个监控，回收线程与子进程（5 秒内无残留） |
| 监控启动失败 | 告警后继续实验；不抛出、不阻断 |

## 3. 观测字段契约（不变 + 语义澄清）

- `rtt_during` / `http_during` / `attack_window` / `observation_window` 的字段结构与聚合逻辑**不变**。
- null 语义变化：原「需先调用 start 工具」→ 新「监控不可用（未启动/启动失败/未配置 http.url/窗口内无样本）」，提示文案随之更新。
- `covers_attack_window` 判定逻辑不变。

## 4. 配置契约

- 监控目标与参数唯一来源：项目根 `experiment.json`（CLI 参数可覆盖目标 IP 与 http 相关参数）；不得在工具或 helper 中硬编码默认值（宪法「配置单一来源」）。
