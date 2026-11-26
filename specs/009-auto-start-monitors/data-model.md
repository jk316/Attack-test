# 数据模型：拨测监控生命周期收归程序

**特性**: `specs/009-auto-start-monitors/` | **日期**: 2026-11-20

本特性不新增持久化存储；以下实体描述运行期状态与现有数据结构的语义变化。

## 实体

### 1. 监控观测样本（已有，结构不变）

- **MonitorSample**（ping 侧，`src/tools/ping_monitor.py`）：时间戳、发送/接收计数、RTT、丢包率。
- **HttpSample**（HTTP 侧，`src/tools/http_monitor.py`）：时间戳、TTFB、总耗时、状态码、成功/失败、错误类型。
- 两者聚合为流量工具结果中的 `rtt_during` / `http_during` 字段。

### 2. 实验运行会话（新增概念，无新存储结构）

- **属性**: 运行标识（CLI `run_id` / 后端 `thread_id`）、有效目标 IP、HTTP 监控配置（可能为空）、监控状态。
- **关系**: 一次实验运行会话绑定一组监控实例；同一进程内同时最多一个实验（Web 控制台已有 `_running` 互斥，CLI 单进程单次）。
- **状态流转**:

```text
stopped ── start_experiment_monitors() ──▶ running
running ── 重复 start ──▶ (先 stop 再 start，幂等)
running ── stop_experiment_monitors() / 进程退出 ──▶ stopped
```

### 3. 监控配置（`experiment.json` 的 `http` 段）

| 字段 | 类型 | 约束 |
|------|------|------|
| `url` | string | 空/缺失 → 不启动 HTTP 监控 |
| `interval_s` | float | > 0 |
| `timeout_s` | float | > 0 |
| `method` | string | HTTP 方法（默认 GET） |

## 校验规则

- 监控目标 IP 必须通过 `validate_target`（allowlist，FR-003）；失败 → 告警且不启动，实验继续。
- `http.url` 非空才启动 HTTP 监控（FR-002）；URL 本身由 `validate_http_url` 校验（沿用 `http_probe_tool`）。
- 监控启动失败（fping 缺失、权限、URL 不可达等）→ 告警，实验继续，观测字段为空（FR-008）。

## 关系图

```text
实验运行会话 ──拥有──▶ PingMonitor（单例，进程级）
    │                    └─ 产出 MonitorSample ─▶ rtt_during
    └─拥有──▶ HttpMonitor（单例，进程级，仅当 http.url 非空）
                        └─ 产出 HttpSample ─▶ http_during
```

说明：两个 monitor 是进程级单例（现状），「实验运行会话拥有监控」体现在生命周期的启动/停止时机，不改变单例实现；`start_experiment_monitors` 以幂等重启方式保证会话切换时状态干净。
