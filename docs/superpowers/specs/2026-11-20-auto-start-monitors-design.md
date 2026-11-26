# 设计：RTT 与 HTTP 拨测由程序自动启动（Agent 只读数据）

日期：2026-11-20
状态：待批准

## 意图与原因

ping（RTT）与 HTTP 后台拨测是实验基础设施，生命周期应由程序管理。现状由 Agent 主动调用 start/stop 工具：模型一旦忘记，整轮 `rtt_during` / `http_during` 为空，收敛判定失去数据。改为入口自动启动后，观测数据每轮必有，Agent 只消费结果。

## 目标 / 非目标 / 反目标

- 目标：实验开始时自动启动两个 monitor（目标来自配置/CLI 参数）；实验结束时自动清理；Agent 工具集移除 4 个 start/stop 工具。
- 非目标：不改动观测注入逻辑（`rtt_during` / `http_during` / window 字段）、HITL 规则、收敛判定本身。
- 反目标：不破坏 `--trex-explore` 零流量模式；目标缺失时不强启；不允许 Agent 再控制 monitor 生命周期（否则双头管理）。

## 约束

- 目标 IP 必须过 allowlist（沿用 `validate_target` / main.py 预检）。
- 跨平台：ping 后端 fping / system ping 自适应，不得写死 OS。
- 配置读取顺序：工具/监控默认值经 env 注入，启动代码须在 env 设置之后执行。
- 测试存在工具数量断言（23），删 4 个工具后需同步。

## 方案对比

- A（维持现状，Agent 启动）：不可靠，依赖模型记性，已确认「忘记启动则无数据」的隐患。弃。
- B（入口自动启动 + 移除 start/stop 工具）✅：生命周期单一归属程序，Agent 只读；改动集中在两个入口 + 工具集 + 提示词。选。
- C（自动启动 + 保留工具）：保留会让 Agent 仍可中途 stop，双头管理、状态不一致。弃。

## 已定细节

- 两个入口都改：CLI `src/main.py` 与 Web 控制台 `backend/experiment.py`（`ExperimentManager.start/stop`）。
- ping monitor 目标 = 有效实验目标 IP（CLI `--target-ip` 优先，否则 `experiment.json`）；HTTP monitor 目标 = `http.url`，未配置则不启。
- 启动时机：实验运行前；`--trex-explore` 目录模式不启动。
- dry-run 模式同样启动（监控是观测，非攻击流量，原设计即无 HITL）。
- 退出清理：两个 monitor 都在实验结束/进程退出时 stop（HTTP 目前连清理都没有，一并补上）。
- Agent 工具集：删除 `start_ping_monitor` / `stop_ping_monitor` / `start_http_monitor` / `stop_http_monitor`；保留 `read_ping_stats` / `read_http_stats` / `ping_rtt` / `http_probe`。
- 提示词：协议第 0 步改为「监控已自动运行，直接读基线」；更新工具表与「monitor 未运行」相关指引。

## 留给实现者

- 启动/清理函数的具体落位与失败兜底（monitor 启动失败仅告警、实验继续，观测字段自然为空）。
- 测试更新：工具数量断言、start/stop 工具相关用例删除或改写、新增「入口自动启动与清理」用例。
- 提示词具体措辞。
