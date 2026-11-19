# 快速开始：核心闭环 ReAct Agent 与运行模式（端到端验证）

**特性**: `specs/001-agent-core/` | **日期**: 2026-11-19

## 前置条件

1. Python 3.11+ 与 `uv` 可用；依赖安装 `uv sync`。
2. `.env` 配置 API 密钥：`DEEPSEEK_API_KEY`（或 `OPENAI_API_KEY`）；可选 `LLM_MODEL`（默认 deepseek-chat）。模板见 `.env_example`。
3. 目标 IP 位于 `src/config/allowlist.json`（如 `10.99.80.160`）。
4. 网络环境已获授权向该目标发送流量（实验模式会真实发送 Scapy 流量）。

## 场景 A：CLI 闭环实验（dry-run 硬件、Scapy 真实发送 + HITL）

```bash
uv run python src/main.py --target-ip 10.99.80.160 --max-iters 3
```

**预期结果**:
- 启动横幅打印 Target/Max iters/Stop after 等；随后 Agent 开始决策。
- 提议发送流量时终端出现 `[HITL] Approve traffic send?` 与参数明细，等待 `y/n`；输入 `n` 时该轮 0 报文并继续；输入 `y` 时执行发送并返回含 `rtt_during`/`covers_attack_window` 的结果。
- 达到停止条件后打印「=== Experiment Complete ===」与实验总结；后台 ping 监控被清理。

## 场景 B：自动批准（回归验证用）

```bash
uv run python src/main.py --target-ip 10.99.80.160 --max-iters 3 --auto-approve --no-improve-limit 2
```

**预期结果**: 全程无交互提示（打印 Auto-approved），预算按 3/2 生效（命令行覆盖配置）。

## 场景 C：目录探索（零流量、零审批、无人值守）

```bash
uv run python src/main.py --trex-explore --catalog-target 10
```

**预期结果**: 全程无 HITL 中断；结束后生成 `output/trex_attack_catalog_<时间戳>.md`，列出 ≥10 个脚本条目；文件名含时间戳，重复运行互不覆盖。

## 验证命令（测试伴随）

```bash
uv run pytest tests/unit/ -v          # 单元测试（mock 全部 I/O）
uv run pytest tests/integration/ -v   # 集成测试（真实编译器 + mock 网络）
uv run pytest tests/e2e/ -v           # 完整 Agent 循环
uv run pytest --cov=src --cov-report=term-missing   # 覆盖率
```

**本特性新增测试的预期落点**:
- 硬裁决：确定性「恒无改善」序列在第 `no_improve_limit` 轮停止；「恒继续」序列在 `max_iters` 停止（SC-003）。
- 奖励公式：提示渲染文本与运行时计算函数同用 `avg_rtt_ms + loss_pct × 10`（D2）。
- 启动预检：非法目标/非正预算非零退出（D3）。
- 补丁回归：多轮 ≥3 轮无 reasoning_content 类 400（SC-002）。
- HITL：拒绝轮 0 报文、EOF 默认拒绝（SC-004）。
- 配置链：CLI > profile > config > 内置默认（SC-005）。

## 预期结果判据（对照 SC）

| SC | 判据 |
|----|------|
| SC-001 | 本地构建（不含模型响应）10s 内发起首个模型请求 |
| SC-002 | ≥3 轮运行 0 次推理字段缺失导致的失败 |
| SC-003 | 确定性序列下停止时机精确等于预算 |
| SC-004 | 拒绝审批轮发送 0 报文 |
| SC-005 | 工具实际默认值 = CLI 值 |
| SC-006 | 目录探索 0 流量 0 审批、摘要带时间戳且互不覆盖 |
| SC-007 | 结束后无残留 ping 监控进程 |
| SC-008 | 未知预设/互斥参数启动后 1s 内报错退出 |
