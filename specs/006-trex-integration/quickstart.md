# 快速开始：TRex 集成与攻击目录探索验证

**特性目录**: `specs/006-trex-integration/` | **日期**: 2026-11-19

端到端可运行的验证场景（不含完整实现代码）。探索模式全程零流量零 HITL，可安全直接运行；live 场景建议先用无害测试脚本验证门控链。

## 前置条件

1. 依赖安装：`uv sync`（必要时 `uv sync --extra dev`）。
2. allowlist 配置：`src/config/allowlist.json` 的 hosts 数组含 `10.99.80.160`。
3. 探索模式需要 LLM API Key（`.env` 中 `DEEPSEEK_API_KEY`）。

## 场景 1：模式互斥（现状已满足）

```bash
uv run python src/main.py --trex-explore --trex-live
```

**预期结果**: 立即报错 `--trex-explore cannot be combined with --trex-live`，进程以非 0 退出码终止，不进入 Agent 循环。

## 场景 2：默认探索运行（核心验收）

```bash
uv run python src/main.py --trex-explore
```

**预期结果**:
- 全程零流量、零 HITL（工具集仅 `write_python_file`/`run_python_file`，强制 dry-run）。
- `trex_scripts/` 出现 ≥10 个 `cat_*.py`，每个脚本头部含「攻击名称/类别/机制/关键参数/预期效果」中文注释块。
- `output/trex_attack_catalog_<时间戳>.md` 生成，含目录表格与能力边界总结。
- 退出码 0（实现 G1 后，达标即 0）。

## 场景 3：定向探索 + 清理 + 达标校验（G1/G2 实现后）

```bash
uv run python src/main.py --trex-explore --catalog-target 15 --explore-direction "重点探索DNS放大攻击和TCP SYN洪水" --clean-scripts --max-iters 60
```

**预期结果**:
- 启动横幅打印清理行为；旧的 `cat_*.py` 被清空，目录中非 `cat_` 文件完好。
- 结束统计语法通过的 `cat_*.py` ≥15 → 退出码 0；若预算耗尽未达标 → 退出码非 0 且总结仍落盘。
- 总结表格中明确说明 DNS 放大与 TCP SYN 洪水的覆盖情况。

## 场景 4：dry-run 工具零执行（现状已满足）

```bash
uv run pytest tests/unit/test_trex_tools.py -v
```

**预期结果**（覆盖现有 20+ 用例）:
- 路径穿越/保留名/非 .py/超限拒绝。
- dry-run 不执行脚本；语法错误报告行号但仍落盘。
- live 门控：非白名单 IP 拒绝、HITL 拒绝零执行、超时终止、非 0 退出透传 stderr。

## 场景 5：live 人工验证（可选，需谨慎）

```bash
uv run python src/main.py --target-ip 10.99.80.160 --trex-live --max-iters 2
```

**预期结果**: 每次 `run_python_file` 触发 HITL 审批（材料含脚本预览、检测 IP、完整权限警告）；拒绝则零执行；批准后受超时约束执行并返回返回码/输出/耗时（FR-009/010/011）。

## 场景 6：探索模式回归

```bash
uv run pytest tests/unit/test_trex_catalog_mode.py -v
```

**预期结果**: 探索模式 19 个现有用例全绿；G4 新增用例（退出码判定、清理参数只删 cat_ 前缀）通过。

## 验收对照

| 场景 | 对应 FR/SC |
|------|-----------|
| 1 | FR-020、SC-010 |
| 2 | FR-012/014/016/017/018、SC-007/008/009 |
| 3 | FR-016/019/021、决策 006-2/006-3、G1/G2 |
| 4 | FR-001~010、SC-002~006 |
| 5 | FR-009/010/011、SC-005/006 |
| 6 | 宪法三（测试伴随） |
