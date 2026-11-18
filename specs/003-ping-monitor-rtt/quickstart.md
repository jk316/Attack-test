# 快速验证：Ping 监控与 RTT 观测

**特性**: `specs/003-ping-monitor-rtt/` | **日期**: 2026-11-19

端到端可运行验证场景（不含完整实现代码；命令均在项目根执行）。

## 前置

1. 依赖就绪：`uv sync`。
2. 目标准备：`src/config/allowlist.json` 的 `hosts` 包含测试目标（如 `10.99.80.160`）。
3. 后端确认：Linux/macOS 检查 `which fping`（有 → 高分辨率主路径；无 → 自动回退系统 ping）；Windows 直接走回退路径。
4. 配置（差距 G-001/G-002 实施后生效）：`src/config/experiment.json` 的 `"ping_monitor"` 节（`probes_per_sec=10`、`summary_interval_s=1`、`fallback_interval_s=1.0`、`stats_window_s=5.0`、`max_samples=4000`）。

## 场景 1：启动监控并读取窗口统计（对应 P1、SC-001/SC-002）

1. 启动监控（任选其一）：
   - 工具路径：`uv run python -c "from src.agent.tools import start_ping_monitor, read_ping_stats; print(start_ping_monitor.invoke({'ip':'10.99.80.160'}))"`
   - 底层路径：`uv run python -c "from src.tools.ping_monitor import get_ping_monitor; m=get_ping_monitor(); m.start('10.99.80.160'); import time; time.sleep(3)"`
2. 读取统计：`uv run python -c "from src.agent.tools import read_ping_stats; print(read_ping_stats.invoke({'window_s':1.0}))"`

**预期结果**:
- 高分辨率后端：`backend == "fping_q"`，1 秒窗口 `sent_count` 约 10、`sample_count ≤ sent_count`、`loss_pct` 为真实值、`avg/min/max_rtt_ms` 为加权统计。
- 回退后端：`backend == "ping"`，窗口内有样本；目标间歇丢包时 `loss_pct > 0`。
- 非法目标：`start_ping_monitor` 返回 `{"success": false, "error": ...}`（allowlist 拒绝）。

## 场景 2：单次测量与安全拒绝（对应 P3、SC-005）

```bash
uv run python -c "from src.agent.tools import ping_rtt; print(ping_rtt.invoke({'ip':'10.99.80.160','count':4}))"
uv run python -c "from src.agent.tools import ping_rtt; print(ping_rtt.invoke({'ip':'192.168.1.99'}))"   # 非 allowlist
```

**预期结果**: allowlist 内返回 `avg_rtt_ms/loss_pct/packets_transmitted/packets_received`；非 allowlist 返回拒绝错误且不产生探测；目标全丢时 `avg_rtt_ms` 为不可用（无穷大）、`loss_pct=100`。

## 场景 3：攻击观测对齐（对应 P2、SC-003）

1. 保持场景 1 的监控运行，执行一次流量工具（dry-run 或经 HITL 批准）并检查返回结果中的观测三字段：
   - `attack_window` 含 start/end/duration_s/mode；
   - `observation_window.covers_attack_window == true`（监控运行 + 窗口 ≥1 s + 有收到探测）；
   - `rtt_during` 含 samples 与聚合统计。
2. 反例验证：停掉监控后再次执行流量工具 → `covers_attack_window == false`、`rtt_during == null`、note 提示先启动监控。

## 场景 4：生命周期清理（对应 FR-016、SC-006）

```bash
uv run python -c "
from src.tools.ping_monitor import get_ping_monitor
for _ in range(20):
    m = get_ping_monitor(); m.start('10.99.80.160'); m.stop()
import subprocess, sys
print('cleanup ok')
"
```
另以 CLI 完整跑一轮 `uv run python src/main.py --target-ip 10.99.80.160 --max-iters 1 --auto-approve`，进程退出后确认系统无残留 ping/fping 子进程（如 `pgrep -f 'ping|fping'`）。Web 模式（G-003 实施后）在 `uv run uvicorn backend.server:app` 结束一次实验后同样检查。

## 场景 5：单元/集成测试

```bash
uv run pytest tests/unit/test_ping_monitor.py tests/unit/test_rtt_window.py tests/unit/test_ping_rtt_tool.py -v
```

**预期结果**: 全部通过；覆盖跨语言丢包解析、加权口径、五类 covers 判定、并发一致性（SC-004）、拒绝路径（SC-005）。
