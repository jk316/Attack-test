---
description: "拨测监控生命周期收归程序——功能实现任务列表"
---

# 任务：拨测监控生命周期收归程序

**输入**: 来自 `specs/009-auto-start-monitors/` 的设计文档（spec.md / plan.md / research.md / data-model.md / contracts/monitor-lifecycle.md / quickstart.md）

**前置**: plan.md（技术方案）、spec.md（用户故事 US1~US3）、research.md（R1~R8 决策）

**组织方式**: 任务按用户故事分组，使每个故事可独立实现与测试。

## 任务总览

| 任务 ID | 阶段 | 所属故事 | 可并行 | 说明 |
|---------|------|---------|--------|------|
| T001 | 1 搭建 | — | 否 | 环境与基线确认 |
| T002 | 2 地基 | — | 否 | 生命周期 helper 单元测试（先行，红） |
| T003 | 2 地基 | — | 否 | 实现 `src/tools/monitor_lifecycle.py`（绿） |
| T004 | 3 | US1 | 是 | CLI `src/main.py` 接线自动启动/清理 |
| T005 | 3 | US1 | 是 | CLI 自动启动集成测试 |
| T006 | 4 | US2 | 是 | 后端 `backend/experiment.py` 接线 + http 配置读取 |
| T007 | 4 | US2 | 是 | 后端自动启动集成测试 |
| T008 | 5 | US3 | 否 | 删除 4 个 start/stop 工具 |
| T009 | 5 | US3 | 否 | 工具数/名断言 23→19 |
| T010 | 5 | US3 | 是 | 系统提示词改写 |
| T011 | 5 | US3 | 是 | 窗口 note 与 docstring 文案同步 |
| T012 | 5 | US3 | 否 | 既有测试中 start/stop 工具引用改写 |
| T013 | 6 打磨 | — | 否 | 全量测试与 quickstart 验证 |

## 格式：`[ID] [P] [故事] 描述`

- **[P]**: 可并行（不同文件、无依赖）
- **[故事]**: 所属用户故事（US1、US2、US3）；地基/搭建/打磨不标注
- 描述中包含确切文件路径

## 阶段 1：搭建（共享基础设施）

**目的**: 环境与基线确认

- [ ] T001 在 worktree 根运行 `UV_CACHE_DIR=<可写目录> uv sync --extra dev`，确认 venv 就绪；运行 `uv run pytest tests/unit/ -q` 记录基线（预期：309 通过、8 个 `tests/unit/test_llm_client.py` 存量失败——httpx 0.28.1 mock URL 解析问题，与 webui 分支相同，不在本特性修复范围）

---

## 阶段 2：地基（阻塞性前置）

**目的**: 两个入口共用的生命周期编排模块——任何用户故事接线前必须完成

**⚠️ 关键**: 本阶段完成前不得开始任何用户故事工作

- [ ] T002 新建 `tests/unit/test_monitor_lifecycle.py`，先写以下用例并确认失败（红）：启动后 ping monitor 处于运行态且目标为传入 target_ip；`http_cfg` 为空/`url` 缺失时不启动 HTTP monitor；`http_cfg` 含 url/interval_s/timeout_s/method 时 HTTP monitor 以对应参数启动；allowlist 外目标被拒绝（仅告警不启动）；monitor 已在运行时重复 start 先停后启（幂等）；启动抛异常时被捕获、记录告警、不向上抛；`stop_experiment_monitors` 停止两个 monitor 且对未启动的 monitor 安全无操作。mock `get_ping_monitor` / `get_http_monitor`，不产生真实网络流量。
- [ ] T003 新建 `src/tools/monitor_lifecycle.py` 实现 T002 约定的行为（绿）：导出 `start_experiment_monitors(target_ip, http_cfg=None)` 与 `stop_experiment_monitors()`；内部用 `validate_target`（自 `src/tools/ping_rtt_tool.py` 导入）校验 target_ip（FR-003），用 `get_ping_monitor().start(ip)` / `get_http_monitor().start(url, interval_s=..., timeout_s=...)` 启动（FR-001/FR-002），失败仅 `logger.warning`（FR-008），启动前若运行中先 stop（幂等，data-model 状态流转）。不得硬编码任何目标/参数默认值（FR-010）。

**检查点**: `uv run pytest tests/unit/test_monitor_lifecycle.py -q` 全绿；地基就绪——用户故事可以开始

---

## 阶段 3：用户故事 1 - 实验开始时监控自动就绪（优先级：P1）🎯 MVP

**目标**: CLI 入口在实验开始前自动启动监控、退出时自动清理；Agent 无需（也无法）调用启动工具，每轮 `rtt_during` 有效。

**独立测试**: quickstart.md 场景 1 与场景 4——CLI 干跑一轮，`read_ping_stats` 有数据且 Agent 未调用任何 start 工具；`--trex-explore` 无监控启动。

### 用户故事 1 的实现

- [ ] T004 [P] [US1] 修改 `src/main.py`：在预检通过、env 注入之后、`graph.invoke()`（约 485 行）之前，构造 http_cfg（来自已加载的运行配置 `cfg["http"]`，字段 url/interval_s/timeout_s/method）并调用 `start_experiment_monitors(args.target_ip, http_cfg)`；`args.trex_explore` 为真时跳过（FR-004）；把 `finally` 中现有 ping 清理（536-544 行）替换为 `stop_experiment_monitors()`（FR-007，同时覆盖 HTTP 清理）。
- [ ] T005 [P] [US1] 新建 `tests/integration/test_monitor_autostart.py`：以 mock 网络/子进程方式验证 CLI 路径启动后 `get_ping_monitor().is_running()` 为真、目标为有效 target_ip；`trex_explore` 模式下监控不启动；`finally` 路径执行 `stop_experiment_monitors`。不发起真实流量。

**检查点**: 用户故事 1 完整可用——CLI 干跑（quickstart 场景 1）观测 `rtt_during` 非空

---

## 阶段 4：用户故事 2 - 配置了 HTTP 业务目标时 HTTP 拨测同步自动启动（优先级：P2）

**目标**: Web 控制台入口同样自动启动监控；HTTP 拨测由 `experiment.json` 的 `http.url` 驱动，未配置不启动。

**独立测试**: quickstart.md 场景 3——uvicorn 起后端、页面启动实验后 `read_http_stats` 有数据；清空 `http.url` 再启动则无 HTTP 拨测。

### 用户故事 2 的实现

- [ ] T006 [P] [US2] 修改 `backend/experiment.py`：在 `ExperimentManager.start()` 中 `_run_loop()` 之前读取项目根 `experiment.json` 的 `http` 段（与 `src/main.py` 的 `CONFIG_PATH` 同源；文件缺失/解析失败按空配置处理，R2），调用 `start_experiment_monitors(target_ip, http_cfg)`（http_cfg 的 url 为空时 helper 自然跳过 HTTP，FR-002）；在 `start()` 的 `finally`（`_running=False` 处）调用 `stop_experiment_monitors()`（FR-007）。
- [ ] T007 [P] [US2] 扩展 `tests/integration/test_monitor_autostart.py` 或新建后端集成用例：mock WebSocket 前提下调用 `manager.start(params, ws)`，断言监控自动启动；`experiment.json` 缺 `http` 段或 url 空时不启动 HTTP；`finally` 清理两个监控。

**检查点**: 用户故事 2 完整可用——两个入口监控生命周期行为一致

---

## 阶段 5：用户故事 3 - Agent 工具集只读化与清理兜底（优先级：P3）

**目标**: Agent 只能读取拨测数据；工具总数 23→19；提示词与提示文案与只读语义一致；退出清理兜底由程序承担。

**独立测试**: quickstart.md 场景 2——工具集断言 19 且无 start/stop；强杀进程后无 fping/ping/curl 残留。

### 用户故事 3 的实现

- [ ] T008 [US3] 修改 `src/agent/tools.py`：整体删除 `start_ping_monitor`、`stop_ping_monitor`、`start_http_monitor`、`stop_http_monitor` 四个函数定义，并从 `EXPERIMENT_TOOLS` 列表移除（R4；FR-006）；保留 `read_ping_stats` / `read_http_stats` / `ping_rtt` / `http_probe`。
- [ ] T009 [US3] 修改 `tests/integration/test_agent_graph.py`：`test_graph_has_23_tools`（496-508 行）改为断言 19 个工具、改名 `test_graph_has_19_tools`、增加「不含 4 个 start/stop、含 4 个读取/探测」的名称断言；修改 `tests/integration/test_pktgen_integration.py` 的 `test_tool_count_is_23`（140 行）为 19（SC-002）。
- [ ] T010 [P] [US3] 修改 `src/prompts/system_prompt.j2`：协议第 0 步（约 17 行）改为「监控已由程序自动启动，直接读取基线」；删除约 75 行的 stop 指引；工具表（81-94 行区域）删除 4 个 start/stop 行并说明监控由程序管理；约 139/143 行的「monitor 未运行需先调用 start」指引改为「监控不可用时按观测缺失处理，不据此决策」（FR-009）。
- [ ] T011 [P] [US3] 修改文案：`src/tools/rtt_window.py`（约 72 行）与 `src/tools/http_window.py`（约 53 行）的 note 中「需先调用 start_ping_monitor / start_http_monitor」改为「监控由程序自动管理，不可用时按观测缺失处理」；`src/pktgen/adapter.py`（约 447 行）docstring 同步（宪法「文档真实性」）。
- [ ] T012 [US3] 改写既有测试中 4 个工具名的引用：`tests/e2e/test_e2e_closed_loop.py`、`tests/integration/test_agent_graph.py`、`tests/integration/test_pktgen_integration.py`——删除或改写依赖 start/stop 工具调用链的用例，改为断言「监控已自动运行」（与 T009 同一逻辑分组提交，避免中间态失败）。

**检查点**: 工具集只读；提示词无自相矛盾指引；全量测试通过

---

## 阶段 6：打磨与横切关注点

**目的**: 影响多个用户故事的整体验证

- [ ] T013 按 quickstart.md 场景 1~6 全量验证：`uv run pytest tests/unit/ tests/integration/ -q`（预期除 8 个存量 `test_llm_client.py` 失败外全绿，新增用例通过）；CLI 干跑确认 `rtt_during` 非空；退出后 `pgrep fping`/`pgrep ping` 无残留；`--trex-explore` 无监控启动。

---

## 依赖与执行顺序

### 阶段依赖

- **搭建（阶段 1）**: 无依赖，可立即开始
- **地基（阶段 2）**: 依赖搭建完成——阻塞所有用户故事
- **用户故事（阶段 3~5）**: 依赖地基完成；US1 与 US2 可并行（不同文件：`src/main.py` vs `backend/experiment.py` 及各自测试）；US3 依赖 US1/US2 的接线完成后再动手（删除工具后测试须同步改写，避免中间态长期失败）
- **打磨（阶段 6）**: 依赖所有目标故事完成

### 每个用户故事内部

- 地基按测试先行（T002 红 → T003 绿）
- US3 内部顺序：T008（删工具）→ T009（断言）→ T010/T011 并行（文案）→ T012（既有测试改写）
- 每个任务或逻辑分组后提交（T008~T012 可作为同一提交分组）

### 并行机会

- T004/T005（US1）与 T006/T007（US2）可并行——四者文件互不重叠
- US3 内 T010 与 T011 可并行（提示词 vs 源码文案，不同文件）
- T009 与 T012 同属测试断言收敛，建议同一人顺序完成

## 实施策略

### MVP 优先（仅用户故事 1）

1. 完成阶段 1：搭建（T001）
2. 完成阶段 2：地基（T002、T003——关键，阻塞所有故事）
3. 完成阶段 3：用户故事 1（T004、T005）
4. **停下来验证**: quickstart 场景 1/4——CLI 干跑 `rtt_during` 非空
5. 可部署/演示

### 增量交付

1. 搭建 + 地基完成 → 两个入口可接线
2. 加用户故事 1 → CLI 端到端验证 → 交付（MVP！）
3. 加用户故事 2 → Web 控制台与 HTTP 拨测验证 → 交付
4. 加用户故事 3 → 工具集只读 + 文案收敛 → 全量测试 → 交付
5. 打磨（T013）→ 进入 speckit-converge

## 备注

- [P] 任务 = 不同文件、无依赖
- [故事] 标签把任务映射到用户故事以便追溯（T002/T003 为地基，供所有故事共用）
- 每个用户故事应可独立完成、独立测试
- 实现前确认测试失败（地基 TDD）
- 每个任务或逻辑分组后提交（提交信息带 `009` 特性前缀）
- 避免：含糊任务、同文件冲突、破坏独立性的跨故事依赖
