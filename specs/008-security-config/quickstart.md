# 快速开始 / 安全验证矩阵：安全约束与配置体系（横切关注点）

**特性目录**: `specs/008-security-config/` | **日期**: 2026-11-19

> 用途：实现完成后的验收基线，按 spec.md SC-001~SC-010 逐项组织。所有「零流量」断言以工具结果与（可选）抓包/日志双重确认。前置：`uv sync --extra dev`。

## 场景 1：allowlist 拒绝与失败关闭（FR-001/002/003、SC-001/002/006）

- 操作：`uv run python src/main.py --target-ip 192.168.1.99 --max-iters 1`（非白名单目标，dry-run）。
- 预期：Agent 首次调用目标相关工具即收到 allowlist 拒绝错误（"Target 192.168.1.99 not in allowlist"），实验不产生任何流量；日志无发包记录。
- 失败关闭：临时把 `src/config/allowlist.json` 的 `hosts` 改为 `[]` 再运行 → 所有目标校验报 "allowlist is empty"；恢复文件。

## 场景 2：广播/组播/伪造 src_ip 拒绝（FR-003/004、SC-002）

- 操作（单元测试为主）：对 `validate_target("10.99.80.255")`（广播）、`validate_target("224.0.0.1")`（组播）断言 ValueError；对 `traffic_send_tool(src_ip="1.2.3.4", …)` 断言拒绝（"src_ip forgery is not allowed"）。
- 预期：全部抛错且零流量。

## 场景 3：上限钳制（FR-005/006/007、SC-003）

- 操作：`uv run python src/main.py --target-ip 10.99.80.160 --max-iters 1 --duration 120 --pps 100000 --packet-size 9999 --flow-count 500`
- 预期：工具结果中生效值 = 20 / 20000 / 1024 / 100（钳制到上限并如实报告）；等于上限的输入（duration=20）不被钳制。

## 场景 4：配置单一来源与 profiles（FR-013/014/015、SC-005）

- 操作：修改 `src/config/experiment.json` 的 `attack.duration_s` 为 7 → 无 CLI 参数运行一次实验 → 观察工具默认时长为 7 秒；改回 10。
- `--profile high_pps` → pps/duration 采用预设值，其余沿用基础默认；`--profile nope` → 报错并列出 high_pps / long_run / pktgen_max。

## 场景 5：--auto-approve × 实发互斥（008-1 决议、FR-017、SC-004）

- 操作（实现 G1 后）：
  - `uv run python src/main.py --target-ip 10.99.80.160 --auto-approve --pktgen-live --max-iters 1` → 预期：启动即报错退出（exit≠0），提示禁止组合。
  - `… --auto-approve --trex-live …` → 同上。
  - `… --auto-approve`（dry-run）→ 可运行，每次自动批准在输出中标记「Auto-approved (--auto-approve)」。
- 未启用 --auto-approve 时：每个流量工具调用必出现审批提示（触发率 100%）。

## 场景 6：配置默认值超限启动告警（008-2 决议、FR-020）

- 操作（实现 G2 后）：临时把 experiment.json 的 `attack.pps` 改为 99999 → 启动 → 预期输出警告（字段/配置值/钳制后上限值），实验可继续运行且生效值 20000；恢复文件后警告消失。

## 场景 7：HITL 审批内容统一（008-3 决议、FR-008/010）

- 操作：分别触发 traffic_send（Scapy）、pktgen_udp_flood（--pktgen-live）、TRex run_python_file（--trex-live）三个审批点，观察审批提示。
- 预期：三者均含 `message`、`params`（完整参数快照）、`scope`（scapy_traffic / pktgen_traffic / trex_script）；TRex 审批内容保留 code_preview 与「任意 Python 执行」警告、并声明静态扫描为非硬边界。

## 场景 8：dry-run 与 explore 零流量（FR-012/019、SC-010）

- 操作：默认模式调用 Pktgen 工具 → 结果 mode=dry_run（仅编译 Lua，不连接硬件）；`--trex-explore --catalog-target 3 --max-iters 10` 全程运行。
- 预期：全程无审批提示、无流量；探索产出脚本与 `output/trex_attack_catalog_<时间戳>.md`。

## 场景 9：文档一致性（FR-016、SC-008）

- 操作（实现 G5 后）：运行一致性测试（解析 tools.py docstring 中的上限表述 vs traffic_send_tool.py 常量与 system_prompt.j2 上限表）。
- 预期：0 处冲突（当前已知 docstring 滞后：200/10/512/50 → 修正为 20000/20/1024/100）。

## 回归确认

- `uv run pytest tests/unit/ tests/integration/ -v` 全部通过（含本特性新增测试）。
- 对照 spec.md SC-001~SC-010 与 FR-001~FR-020 逐项打勾；未满足项进入收敛任务（宪法二）。
