# 快速开始：Pktgen-DPDK 硬件集成验证

**特性目录**: `specs/005-pktgen-integration/` | **日期**: 2026-11-19

端到端可运行的验证场景（不含完整实现代码）。无需真实 Pktgen 硬件——dry-run 场景零网络依赖；live 场景用模拟 TCP 端点验证。

## 前置条件

1. 依赖安装：`uv sync`（必要时 `uv sync --extra dev`）。
2. allowlist 配置：`src/config/allowlist.json` 的 hosts 数组含 `10.99.80.160`。
3. （仅 live 场景）`topology.yaml` 指向可用的 Pktgen 主机，或使用模拟端点。

## 场景 1：默认 dry-run（零流量基线）

```bash
uv run python src/main.py --target-ip 10.99.80.160 --max-iters 3
```

**预期结果**:
- Agent 可调用 Pktgen 工具；每次调用的结果 `mode=dry_run`。
- `lua_scripts/` 目录出现 `YYYYMMDD_HHMMSS_<skill>.lua` 审计文件。
- 无 TCP 连接产生（可用接口计数/抓包验证零流量）。

## 场景 2：参数上限拒绝（实现后验证 G1）

通过单元测试验证（比 CLI 更直接）：

```bash
uv run pytest tests/unit/test_pktgen_adapter.py -v
```

**预期结果**（针对新增用例）:
- `duration=120000` 的调用被拒绝并返回参数错误，不产生编译产物。
- `rate=150` 的调用返回编译参数错误（现状已满足）。
- 传入 `src_ip` 的调用被拒绝（G3）。

## 场景 3：eth_dst_addr 自动填充（现状已满足，防回归）

**操作**: 调用 `pktgen_packet_sequence`，序列条目含 `"eth_dst_addr": "00:00:00:00:00:01"`。

**预期结果**:
- 结果含 `replaced_mac` 明细（`[{index, from, to}]`，G5 已实现）；真实 MAC 不被替换。
- 替换后的真实 MAC（`topology.yaml` 的 `dst_mac`，`f0:c4:78:4c:a5:55`）体现在转发给
  编译器的参数序列中（`params.sequences[i].eth_dst_addr`），由
  `tests/unit/test_pktgen_adapter.py` 的参数级断言锁定。
- ⚠️ 口径说明（R10 修订）：vendored 编译器对 seqTable 数据只发占位注释
  （`-- table data from $params.sequences[...]`），因此**编译产物 Lua 文件本身
  不含逐条目 MAC**——替换的可观测证据在适配器结果（`replaced_mac`）与转发参数，
  而非产物文件内容（vendored 代码保持与上游同步，不修改）。

## 场景 4：live 门控链（模拟端点）

```bash
uv run pytest tests/integration/test_pktgen_client.py tests/integration/test_pktgen_integration.py -v
```

**预期结果**:
- 模拟 TCP 端点收到编译产物（验证 FR-003 下发链路）。
- HITL 审批流触发；拒绝时零下发（FR-006）。
- 非白名单目标拒绝（FR-005）；arp_flood 提供非白名单 dst_ip 拒绝（G2 实现后）。
- 硬件不可达时返回「建议回落 Scapy」摘要（FR-015）。

## 场景 5：配置默认值生效（实现后验证 G4）

```bash
uv run python src/main.py --target-ip 10.99.80.160 --pktgen-rate 80 --pktgen-duration 3000 --max-iters 2
```

**预期结果**: 未显式传 rate/duration 的 Pktgen 调用，其默认值来自 CLI 参数（80 / 3000ms），而非签名硬编码（验证提示词与工具默认一致）。

## 场景 6：全量回归

```bash
uv run pytest tests/unit/ -v && uv run pytest tests/integration/ -v
```

**预期结果**: 全部通过；集成测试中 Pktgen 相关用例在硬件不可达时自动跳过（session 级检测）。

## 验收对照

| 场景 | 对应 FR/SC |
|------|-----------|
| 1 | FR-004、SC-001 |
| 2 | FR-008/009/016、SC-004 |
| 3 | FR-012、SC-006 |
| 4 | FR-003/005/006/015、SC-002/003/007 |
| 5 | FR-017（宪法六）、G4 |
| 6 | 宪法三（测试伴随） |
