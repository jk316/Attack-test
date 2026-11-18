---
description: "TRex 集成与攻击目录探索实现任务列表"
---

# 任务：TRex 集成与攻击目录探索

**输入**: 来自 `specs/006-trex-integration/` 的设计文档

**前置**: [plan.md](plan.md)（差距清单 G1–G4）、[spec.md](spec.md)（用户故事 US1–US3）、[research.md](research.md)（决策 D1–D6）、[data-model.md](data-model.md)、[contracts/](contracts/)

**组织方式**: 任务按用户故事分组，使每个故事可独立实现与测试。本特性为回溯式：工具层与探索模式主体已实现并有单测，任务 = 基线确认 + 缺口实现（G1–G3 均在 CLI 编排/提示层）+ 回归补测。

## 任务总览

| 任务 ID | 阶段 | 所属故事 | 可并行 | 说明 |
|---------|------|---------|:---:|------|
| T001 | 1 搭建 | — | 否 | 运行现有测试基线（trex_tools / trex_catalog_mode） |
| T002 | 1 搭建 | — | 否 | 依赖与环境确认（uv、yaml、子进程环境） |
| T003 | 2 地基 | — | 是 | 契约现状核对表（G1–G3 现状证据） |
| T004 | 2 地基 | — | 是 | main.py 探索分支修改位置梳理（只读） |
| T005 | 3 · US1 | US1 | 是 | 失败测试 G3：HITL 材料含「可混淆」提示（test_trex_tools.py） |
| T006 | 3 · US1 | US1 | 是 | 契约补测：超时钳制/截断/env 重读（tests/unit/test_trex_config.py 新建） |
| T007 | 3 · US1 | US1 | 否 | 实现 G3：审批 payload 补充提示（src/trex/tools.py） |
| T008 | 3 · US1 | US1 | 否 | US1 全绿验证 |
| T009 | 4 · US2 | US2 | 是 | 回归核对：互斥/dry-run 零执行/工具集（test_trex_catalog_mode.py） |
| T010 | 4 · US2 | US2 | 否 | 手动验证互斥退出码（quickstart 场景 1） |
| T011 | 5 · US3 | US3 | 是 | 失败测试 G1+G2（tests/unit/test_trex_catalog_exit.py 新建） |
| T012 | 5 · US3 | US3 | 否 | 实现 G1：达标计数 + 非 0 退出码 + catalog-target<1 拒绝（src/main.py） |
| T013 | 5 · US3 | US3 | 否 | 实现 G2：--clean-scripts 清理参数（src/main.py） |
| T014 | 5 · US3 | US3 | 是 | 渲染回归：探索提示词用例不受影响（test_trex_catalog_mode.py） |
| T015 | 6 打磨 | — | 是 | 提示词口径核对（trex_catalog_prompt.j2） |
| T016 | 6 打磨 | — | 否 | 端到端验证（quickstart 场景 2/3） |
| T017 | 6 打磨 | — | 否 | 全量回归 + 契约不变量终核 |

## 格式：`[ID] [P] [故事] 描述`

- **[P]**: 可并行（不同文件、无依赖）
- **[故事]**: 所属用户故事（US1/US2/US3）
- 描述中包含确切文件路径

## 阶段 1：搭建（基线确认）

**目的**: 回溯式特性没有从零搭建——本阶段确认现有实现与测试基线可信。

- [ ] T001 运行基线测试 `uv run pytest tests/unit/test_trex_tools.py tests/unit/test_trex_catalog_mode.py -v`，记录全绿/已知失败清单（现有约 40 个用例覆盖门控链与探索模式）
- [ ] T002 确认依赖与环境：`uv sync --extra dev`；确认 `src/trex/config.py` 的 yaml 拓扑读取可用、`sys.executable` 子进程环境可运行测试脚本

---

## 阶段 2：地基（阻塞性前置）

**目的**: 任何用户故事开始前必须完成的核对与定位。

**⚠️ 关键**: 本阶段完成前不得开始任何用户故事工作。

- [ ] T003 [P] 契约现状核对：对照 `specs/006-trex-integration/contracts/trex-script-sandbox.md` 与 `contracts/trex-run-gates.md` 逐项核对 `src/trex/tools.py`、`src/trex/config.py`、`src/main.py` 现状，输出「已满足 / G1 缺口 / G2 缺口 / G3 缺口」核对表，标注现状证据行号（只读核对，不改代码）
- [ ] T004 [P] main.py 探索分支定位：梳理 `src/main.py` 中探索模式的参数解析区（`--trex-explore`/`--catalog-target`/`--explore-direction` 约 273–291 行）、env 注入（`_apply_trex_explore_env` 约 350 行）、收尾区（目录摘要落盘约 515 行），产出 G1/G2 的精确修改位置清单（只读梳理）。注意：`src/main.py` 与 005 的 T004（PKTGEN_SRC_IP 注入）及 008 的改动同文件，实施前以 git 状态为准避免互相覆盖

**检查点**: 基线可信、缺口位置明确——用户故事可以开始。

---

## 阶段 3：用户故事 1 - 受门控的 TRex 脚本写入与执行（优先级：P1）🎯 MVP

**目标**: `write_python_file`（沙箱写入 + 仅语法检查）与 `run_python_file`（存在性 → 语法 → 静态 IP 筛查 → allowlist → HITL → 超时 → 结果透传）完整可执行，补齐 G3（审批材料风险披露）。

**独立测试**: `tests/unit/test_trex_tools.py`（G3 用例）+ `tests/unit/test_trex_config.py`（新建）全绿；dry-run 零执行零审批、非法输入全部拒绝。

### 用户故事 1 的测试 ⚠️

> **注意：先写测试，确认失败后再实现（宪法三·测试伴随）**

- [ ] T005 [P] [US1] 失败测试 G3：扩展 `tests/unit/test_trex_tools.py`——用 mock `interrupt` 捕获审批 payload，断言其 `warning` 字段包含「静态 IP 筛查可被混淆绕过，请人工审查脚本内容」类提示（当前 payload 仅含完整权限警告）。写完后运行确认失败
- [ ] T006 [P] [US1] 契约补测：新建 `tests/unit/test_trex_config.py`——断言 `get_trex_timeout_s()` 钳制语义（0/负数/非法值/超 300 一律回退默认 30、(0,300] 内取配置值）、`get_trex_host()/get_trex_port()` env 优先与拓扑回退、`is_trex_dry_run()` 仅显式 "false" 为 live；断言 `src/trex/tools.py` 的 `_truncate()` 截断 4000 字符并附 `…(+N chars)` 后缀（对应 contracts/trex-run-gates.md 第 4 节）

### 用户故事 1 的实现

- [ ] T007 [US1] 实现 G3：在 `src/trex/tools.py` 的 `_execute_live` 审批 payload（约 177–185 行的 `warning` 字段）补充「脚本内 IP 静态筛查可被混淆绕过，请人工审查脚本内容」提示，与既有「完整权限执行任意 Python」警告并列（依赖 T005）

### 用户故事 1 的验证

- [ ] T008 [US1] US1 全绿验证：运行 `tests/unit/test_trex_tools.py`、`tests/unit/test_trex_config.py` 全量，修复回归；确认 dry-run 零执行零审批（依赖 T005、T006、T007）

**检查点**: 用户故事 1 应完整可用且可独立测试（对应 quickstart 场景 4/5）。

---

## 阶段 4：用户故事 2 - 默认 dry-run 与模式互斥（优先级：P2）

**目标**: 默认 dry-run 零流量零审批、`--trex-live` 才执行、`--trex-explore` 与 `--trex-live` 同时给出时拒绝启动——三个模式边界固化（现状已实现，本阶段回归确认）。

**独立测试**: `tests/unit/test_trex_catalog_mode.py` 相关用例 + 手动验证互斥退出码。

### 用户故事 2 的测试 ⚠️

- [ ] T009 [P] [US2] 回归核对与补齐：核对 `tests/unit/test_trex_catalog_mode.py` 现有用例（`test_explore_with_trex_live_conflicts`、`test_apply_mode_env_forces_dry_run`、`test_catalog_mode_restricts_tools_to_trex`、`test_default_mode_keeps_full_tool_set` 等），补齐缺口断言：互斥时报错且退出码非 0、探索模式强制 `TREX_DRY_RUN=true`、dry-run 下 `run_python_file` 零执行零审批

### 用户故事 2 的验证

- [ ] T010 [US2] 手动验证：按 `specs/006-trex-integration/quickstart.md` 场景 1 运行 `uv run python src/main.py --trex-explore --trex-live`，确认报错文案与进程退出码非 0（依赖 T009）

**检查点**: 用户故事 2 应完整可用且可独立测试。

---

## 阶段 5：用户故事 3 - 攻击目录探索模式（优先级：P3）

**目标**: 探索模式达标判定（G1：语法通过 cat_ 计数 → 退出码 0/1、--catalog-target<1 解析拒绝）与清理参数（G2：--clean-scripts 只删 cat_*.py），结合既有「仅 2 工具 + 强制 dry-run + 中文注释 + 摘要落盘」构成完整闭环。

**独立测试**: `tests/unit/test_trex_catalog_exit.py`（新建）+ 端到端运行（quickstart 场景 2/3）。

### 用户故事 3 的测试 ⚠️

- [ ] T011 [P] [US3] 失败测试 G1+G2：新建 `tests/unit/test_trex_catalog_exit.py`——断言 `--catalog-target 0`/`-1` 解析报错且退出码非 0（G1a）；断言达标计数函数：用 tmp_path 构造 `cat_*.py`（含语法错误与正确脚本），语法通过数 ≥target → 退出码 0、未达标 → 退出码 1 且总结仍落盘（G1b）；断言 `--clean-scripts` 仅删除 `cat_*.py`、保留非 `cat_` 文件并打印清理横幅（G2）。写完后运行确认失败

### 用户故事 3 的实现

- [ ] T012 [US3] 实现 G1：在 `src/main.py` 参数解析区拒绝 `--catalog-target < 1`（`parser.error` 口径，与互斥报错一致）；在探索收尾区（目录摘要落盘之后）新增达标统计——对 `trex_scripts/cat_*.py` 逐一做 parse-only 语法检查并计数，≥catalog_target → 退出码 0，未达标 → 仍落盘总结（FR-021）但退出码 1（依赖 T011）
- [ ] T013 [US3] 实现 G2：在 `src/main.py` 新增 `--clean-scripts`（bool，默认 False，仅探索模式生效）：启动时（env 注入前）删除 `trex_scripts/cat_*.py`，绝不动非 `cat_` 文件，并在启动横幅打印清理行为；与 T012 同文件，顺序执行（依赖 T011）

### 用户故事 3 的验证

- [ ] T014 [P] [US3] 渲染回归：运行 `tests/unit/test_trex_catalog_mode.py` 现有 19 个用例，确认 G1/G2 不影响提示词渲染、互斥逻辑与工具集限制；如有失败修复并注明原因（依赖 T012、T013）

**检查点**: 用户故事 3 应完整可用且可独立测试（对应 quickstart 场景 2/3）。

---

## 阶段 6：打磨与横切关注点

**目的**: 影响多个用户故事的文档口径与最终验收。

- [ ] T015 [P] 提示词口径核对：核对 `src/prompts/trex_catalog_prompt.j2` 与退出码/清理参数新口径无矛盾；必要时在「停止条件」段补充「未达标（预算耗尽）的运行会以非 0 退出码结束；可用 `--clean-scripts` 在启动时清空旧 `cat_` 脚本」说明（不改硬性约束语义）
- [ ] T016 端到端验证：按 `specs/006-trex-integration/quickstart.md` 场景 2/3 运行（`--trex-explore` 默认，及 `--trex-explore --catalog-target 15 --explore-direction "重点探索DNS放大攻击和TCP SYN洪水" --clean-scripts --max-iters 60`），核对：≥N 个语法通过 cat_ 脚本、100% 中文注释块、摘要落盘且互不覆盖、退出码 0、清理行为、全程零流量零 HITL
- [ ] T017 全量回归 + 契约终核：`uv run pytest tests/ -v` 全绿；逐条核对 `contracts/trex-run-gates.md` 第 6 节不变量与 `contracts/trex-script-sandbox.md` 第 5 节不变量

---

## 依赖与执行顺序

### 阶段依赖

- **搭建（阶段 1）**: T002 → T001
- **地基（阶段 2）**: 依赖阶段 1；T003/T004 可并行；阻塞所有用户故事
- **用户故事（阶段 3–5）**: 依赖地基；按优先级顺序 P1 → P2 → P3 推进（US3 的探索模式依赖 US1 的写入/语法检查工具，故顺序不可倒置）
- **打磨（阶段 6）**: 依赖全部目标故事完成

### 每个用户故事内部

- 测试（T005/T006/T009/T011）先写并确认失败，再实现
- US1：T007 ← T005；T008 ← T005/T006/T007
- US2：T010 ← T009
- US3：T012 ← T011；T013 ← T011；T014 ← T012/T013
- 故事完成后再进入下一优先级

### 跨特性依赖（重要）

- `src/main.py` 被 005-T004（PKTGEN_SRC_IP 注入）与 008 的改动共享：本特性的 T012/T013 修改同一文件，实施前以 git 最新状态为准，避免互相覆盖。

### 并行机会

- 地基阶段：T003 与 T004 可并行（均为只读核对，产物不同）
- US1 内：T005（test_trex_tools.py）与 T006（新文件 test_trex_config.py）可并行
- US3 内：T011（新文件 test_trex_catalog_exit.py）与 US2 的 T009 无同文件冲突，可在 US2 完成后与 T011 并行启动测试
- 打磨：T015（提示词核对）与 T016（端到端）可并行
- 注意：同文件任务（main.py 的 T012/T013；test_trex_tools.py 的 T005 与后续扩展；test_trex_catalog_mode.py 的 T009 与 T014）必须顺序执行

## 实施策略

### MVP 优先（仅用户故事 1）

1. 完成阶段 1：搭建（T001–T002）
2. 完成阶段 2：地基（T003–T004，关键——阻塞所有故事）
3. 完成阶段 3：用户故事 1（T005–T008）
4. **停下来验证**: 运行 T008 测试并核对 quickstart 场景 4/5
5. 可部署/演示（受门控的脚本写入与执行 = 本特性核心价值）

### 增量交付

1. 搭建 + 地基完成 → 基线可信、缺口定位明确
2. 加用户故事 1 → 独立测试 → 部署/演示（MVP！）
3. 加用户故事 2 → 独立测试（互斥与 dry-run 边界固化）→ 部署/演示
4. 加用户故事 3 → 独立测试（达标/退出码/清理 + 端到端）→ 部署/演示
5. 打磨横切（提示词口径 + 端到端 + 契约终核）

## 备注

- [P] 任务 = 不同文件、无依赖；同文件任务必须顺序执行
- [USn] 标签把任务映射到用户故事（US1 受门控的脚本写入与执行 / US2 默认 dry-run 与模式互斥 / US3 攻击目录探索）
- 每个用户故事应可独立完成、独立测试
- 实现前确认测试失败（红-绿-重构）
- 每个任务或逻辑分组后提交
- G3 的审批材料实际位于 `src/trex/tools.py` 的 `_execute_live`（非 `src/agent/tools.py`，后者只承载 Scapy 工具的 HITL）——T007 以此为准
- data-model 受约束字段映射：脚本规模/文件名→T003 核对+T008 回归、超时钳制/截断→T006、exit_code/clean_scripts→T012/T013、warning 提示→T007
