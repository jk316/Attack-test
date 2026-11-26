---
description: "从实验日志提炼经验教训——功能实现任务列表"
---

# 任务：从实验日志提炼经验教训（lessons）

**输入**: 来自 `specs/010-lessons-summary/` 的设计文档（spec.md / plan.md / research.md / data-model.md / contracts/lessons.md / quickstart.md）

**前置**: plan.md（技术方案）、spec.md（用户故事 US1~US4）、research.md（R1~R9 决策）

**组织方式**: 任务按用户故事分组，使每个故事可独立实现与测试。

## 任务总览

| 任务 ID | 阶段 | 所属故事 | 可并行 | 说明 |
|---------|------|---------|--------|------|
| T001 | 1 搭建 | — | 否 | 环境与基线确认 |
| T002 | 2 地基 | — | 否 | `records.py` 单元测试（先行，红） |
| T003 | 2 地基 | — | 否 | 实现 `src/lessons/records.py`（绿） |
| T004 | 2 地基 | US2 | 是 | `stats.py` 单元测试（先行，红） |
| T005 | 2 地基 | US2 | 是 | 实现 `src/lessons/stats.py`（绿） |
| T006 | 2 地基 | US1 | 否 | `render.py` 单元测试（先行，红） |
| T007 | 2 地基 | US1 | 否 | 实现 `src/lessons/render.py`（绿） |
| T008 | 3 | US1 | 否 | CLI `scripts/generate_lessons.py` 编排 + 幂等 |
| T009 | 3 | US1 | 否 | CLI 端到端集成测试 |
| T010 | 4 | US3 | 是 | `src/llm/client.py` 新增 `chat_text()` |
| T011 | 4 | US3 | 否 | 实现 `src/lessons/extract.py`（LLM 叙事 + 降级） |
| T012 | 4 | US3 | 否 | `extract.py` 单元测试（mock LLM） |
| T013 | 5 | US4 | 是 | `src/main.py` 写 `[RUN START]/[RUN END]` 标记 |
| T014 | 5 | US4 | 是 | 实现 `src/lessons/segment.py`（标记切分 + 降级） |
| T015 | 5 | US4 | 否 | `segment.py` 单测 + main.py 标记集成测试 |
| T016 | 6 打磨 | — | 否 | `quickstart.sh` + 全量测试验证 |

## 格式：`[ID] [P] [故事] 描述`

- **[P]**: 可并行（不同文件、无依赖）
- **[故事]**: 所属用户故事（US1、US2、US3、US4）；地基/搭建/打磨不标注
- 描述中包含确切文件路径

## 阶段 1：搭建（共享基础设施）

**目的**: 环境与基线确认

- [X] T001 在 worktree 根运行 `uv sync --extra dev` 确认 venv 就绪；运行 `uv run pytest tests/unit/ -q` 记录基线（已知存量：`tests/unit/test_llm_client.py` 8 个 httpx mock URL 解析失败，与本特性无关，不在修复范围）。

---

## 阶段 2：地基（阻塞性前置）

**目的**: 三个纯函数模块（分组/统计/渲染）——任何用户故事接线前必须完成

**⚠️ 关键**: 本阶段完成前不得开始任何用户故事工作

- [X] T002 新建 `tests/unit/test_lessons_records.py`，先写用例并确认失败（红）：`load_runs` 把多行按 `run_id` 分组且行按 iteration 排序；过滤 `unknown`/`legacy-*`/不匹配 `^\d{8}T\d{6}-[0-9a-f]{6}$` 的 id；真实 id 按时间序排序；空文件/坏行（不可解析）被跳过并计数；返回的 `Run` 含 `run_id`/`rows`/`target_ip`/`start_ts`/`end_ts`/`iterations`。
- [X] T003 新建 `src/lessons/records.py` 实现 T002 约定（绿）：导出 `load_runs(log_path) -> list[Run]` 与 `RUN_ID_RE`、`Run` 数据类；坏行跳过并计入统计，不抛异常。

- [X] T004 新建 `tests/unit/test_lessons_stats.py`，先写用例并确认失败（红）：`summarize_run(rows)` 产出每轮观测表（iteration/tool/rtt/loss/http 字段正确提取）；复合评分 `loss×10 + rtt + (1-success_rate)×100 + ttfb 增量` 选出最佳一轮；「无观测」行不参与最佳评选；趋势（上升/下降/平稳/无数据）与收敛启发式（可能已收敛/未收敛/无数据）与手算一致；工具分布计数正确。给定 5 行 RTT `1.2→0.9→0.9→32.8→167` 断言最佳=第 5 轮、趋势=上升。
- [X] T005 新建 `src/lessons/stats.py` 实现 T004 约定（绿）：导出 `summarize_run(rows) -> RunStats`、`IterationObservation`/`RunStats` 数据类、`_score`/`_trend`/`_convergence` 纯函数；HTTP 字段从 `results`（及 `params` 兜底）提取；无观测标注。

- [X] T006 新建 `tests/unit/test_lessons_render.py`，先写用例并确认失败（红）：`render_lesson(run_id, run, stats, narrative)` 输出含固定四节标题（观测概览/关键结论/经验教训/下次实验建议）；元信息行含 run_id、目标、轮数；观测表含每轮行与「无观测」标注；narrative 为 None 时降级要点仍渲染。
- [X] T007 新建 `src/lessons/render.py` 实现 T006 约定（绿）：导出 `render_lesson(...) -> str` 与 `render_rule_lessons(stats) -> str`（规则要点，US3 降级共用）；章节结构与 `contracts/lessons.md` 第 3 节一致。

**检查点**: `uv run pytest tests/unit/test_lessons_records.py tests/unit/test_lessons_stats.py tests/unit/test_lessons_render.py -q` 全绿；地基就绪。

---

## 阶段 3：用户故事 1 - 独立脚本按 run_id 增量生成（优先级：P1）🎯 MVP

**目标**: `scripts/generate_lessons.py` 读取 jsonl → 分组 → 统计 → 渲染 → 写 `lessons/{run_id}.md`，幂等跳过已存在文件，支持 `--list/--force/--latest/--run-id/--no-llm`。此阶段 `--no-llm` 下即可交付可用 MVP。

**独立测试**: quickstart.md 场景 1/2/3——fixture jsonl 生成文件、二次运行 0 变更、`--list` 只打印不改文件。

### 用户故事 1 的实现

- [X] T008 [US1] 新建 `scripts/generate_lessons.py`：`argparse` 参数（`--log-path`/`--data-dir`/`--lessons-dir`/`--run-id`/`--latest`/`--force`/`--no-llm`/`--list`，默认见 contracts 第 2 节）；`load_runs` → 确定 targets（幂等：`lessons/{run_id}.md` 不存在或 `--force`；`--run-id`/`--latest` 先收窄）→ 对每个 run：`summarize_run` → `render_lesson`（`narrative=None`，`--no-llm` 时用 `render_rule_lessons`）→ 写文件；`--list` 只打印待总结 id；`--log-path` 缺失/空 → 退出码非 0 并打印错误；`lessons_dir` 自动创建。
- [X] T009 [US1] 新建 `tests/integration/test_generate_lessons.py`：fixture jsonl（含 2 个真实 run_id + 1 行 `unknown`）+ tmp `lessons` 目录 + `--no-llm` 端到端：生成 2 个 `{run_id}.md` 且内容含四节；二次运行 0 新文件/字节不变；`--force` 重写；`--list` 只打印不改文件；`--run-id` 只处理指定 id；`--latest` 只处理最新 id；空/缺失 log 退出码非 0。

**检查点**: 用户故事 1 完整可用——`uv run python scripts/generate_lessons.py --no-llm` 产出 lessons 文档

---

## 阶段 4：用户故事 3 - LLM 叙事与降级（优先级：P2）

**目标**: `extract.py` 用 DeepSeek 生成「经验教训/下次建议」两段；`--no-llm`/无 key/失败降级为规则要点。

**独立测试**: quickstart.md 场景 4——有 key 出 LLM 段；无 key/`--no-llm` 出规则要点，退出码 0。

### 用户故事 3 的实现

- [X] T010 [P] [US3] 修改 `src/llm/client.py`：新增 `chat_text(messages) -> str`（返回 `response.choices[0].message.content` 原始文本，不解析 JSON）；复用现有 `__init__` 的 key/model 读取；不改变既有 `chat()` 行为。
- [X] T011 [US3] 新建 `src/lessons/extract.py`：导出 `build_narrative(stats, segment_text, client) -> tuple[str, str]`（返回经验教训、下次建议两段）与 `llm_client_from_env() -> LLMClient | None`（无 key 返回 None）；LLM 提示由 stats 结构化事实 + 可选 segment_text 组成；`client is None` 或调用抛错 → 返回 `render_rule_lessons` 派生的两段要点。
- [X] T012 [US3] 新建 `tests/unit/test_lessons_extract.py`：mock `LLMClient.chat_text` 返回固定文本 → 断言两段出现；mock 抛异常 → 降级要点段出现、不抛；`llm_client_from_env` 无 key → None；`build_narrative` 在 `--no-llm`（client=None）路径不发起调用。

**检查点**: 文档含叙事段；无 key 环境退出码 0 且含规则要点

---

## 阶段 5：用户故事 4 - 关联 agent 对话日志（优先级：P3）

**目标**: main.py 写起止标记；segment.py 按标记切分对话片段并入叙事上下文；无标记降级不误配。

**独立测试**: quickstart.md 场景 5——grep 到成对标记；unit：含标记 fixture 切出正确片段、无标记返回 None。

### 用户故事 4 的实现

- [X] T013 [P] [US4] 修改 `src/main.py`：在 agent logger 配置后、`graph.invoke` 前写 `agent_logger.info("[RUN START] %s", run_id)`；在 `finally` 中写 `agent_logger.info("[RUN END] %s", run_id)`（与 `stop_experiment_monitors` 同处，保证异常也成对）。
- [X] T014 [P] [US4] 新建 `src/lessons/segment.py`：导出 `extract_run_segment(run_id, text) -> str | None`（按 `[RUN START] {id}`…`[RUN END] {id}` 切分；无配对返回 None）与 `find_run_segment(run_id, data_dir) -> str | None`（按 run_id 内嵌日期定位 `agent-YYYY-MM-DD.log`，读文件后委托 `extract_run_segment`；文件缺失返回 None）。
- [X] T015 [US4] 新建 `tests/unit/test_lessons_segment.py`（含标记 fixture 切出正确片段；无标记返回 None；`START` 无配对 `END` 返回 None）+ `tests/integration/test_main_run_markers.py`（monkeypatch `src.main.build_graph` 为 stub、`_agent_log_path` 指向 tmp、`start/stop_experiment_monitors` 为空操作，运行 `main()` 后断言 tmp 日志含成对 `[RUN START]/[RUN END]`，SC-004）。

**检查点**: 叙事含对话上下文；旧日志无标记时优雅降级

---

## 阶段 6：打磨与横切关注点

**目的**: 一键验证脚本 + 全量测试 + 文档同步

- [X] T016 新建 `specs/010-lessons-summary/quickstart.sh`（场景 1/2/3 的自动化：生成 → 幂等 → `--list`，各输出 ✅/❌）；运行 `uv run pytest tests/unit/ tests/integration/ -q` 确认新增用例全绿、既有用例除 8 个存量 `test_llm_client.py` 失败外保持通过；converge 阶段同步 CLAUDE.md 的脚本清单与工具表。

---

## 依赖与执行顺序

### 阶段依赖

- **搭建（阶段 1）**: 无依赖，可立即开始
- **地基（阶段 2）**: 依赖搭建完成——阻塞所有用户故事
- **用户故事（阶段 3~5）**: 依赖地基完成；US3（T010~T012）与 US4（T013~T015）可并行（不同文件）；US1（T008/T009）先于 US3 接线（CLI 需 `extract.py` 才能接叙事，但 MVP 可先 `--no-llm`，故 US1 可先行独立完成）
- **打磨（阶段 6）**: 依赖所有目标故事完成

### 每个用户故事内部

- 地基按测试先行（T002 红 → T003 绿；T004 红 → T005 绿；T006 红 → T007 绿）
- US3 内部顺序：T010（chat_text）→ T011（extract）→ T012（测试）
- US4 内部顺序：T013/T014 可并行 → T015（测试）
- 每个任务或逻辑分组后提交（提交信息带 `010` 特性前缀）

### 并行机会

- T004/T005（stats）与 T002/T003（records）可并行（stats 直接收 rows，不依赖 records）
- T010（chat_text）、T013（main.py 标记）、T014（segment）三者文件互不重叠，可并行
- T011（extract）依赖 stats/Render 的类型，与 T013/T014 并行

## 实施策略

### MVP 优先（仅用户故事 1）

1. 完成阶段 1：搭建（T001）
2. 完成阶段 2：地基（T002~T007——关键，阻塞所有故事）
3. 完成阶段 3：用户故事 1（T008、T009）
4. **停下来验证**: quickstart 场景 1/2/3——`--no-llm` 生成文件、幂等、`--list`
5. 可交付（离线、确定性、幂等）

### 增量交付

1. 地基完成 → 纯函数可单测
2. 加用户故事 1 → CLI 端到端 `--no-llm` 交付（MVP！）
3. 加用户故事 3 → LLM 叙事 + 降级 → 交付
4. 加用户故事 4 → 对话上下文 + main.py 标记 → 全量测试 → 交付
5. 打磨（T016）→ 进入 converge

## 备注

- [P] 任务 = 不同文件、无依赖
- [故事] 标签把任务映射到用户故事以便追溯（T004/T005=US2 归入地基；T006/T007=US1 归入地基）
- 每个用户故事应可独立完成、独立测试
- 实现前确认测试失败（地基 TDD）
- 每个任务或逻辑分组后提交（提交信息带 `010` 特性前缀）
- 避免：含糊任务、同文件冲突、破坏独立性的跨故事依赖
- LLM 调用在测试中一律 mock，保证离线可跑（SC-002）

---

## 阶段 7：收敛追加（converge 产出）

**目的**: 对照规格/宪法评估真实代码后的结论与追加工作。

### 收敛结论

- **实现路径与计划一致**：`src/lessons/` 五模块 + `scripts/generate_lessons.py` + `src/main.py` 两行标记 + `src/llm/client.py` 新增 `chat_text()`，全部按 plan/research 落地。
- **一处实现细化（非偏离）**：T008 原述「`--no-llm` 时 `narrative=None` 并用 `render_rule_lessons`」，实际统一为 CLI 始终调 `build_narrative`，`--no-llm`/无 key 时 `client=None` → 内部走 `render_rule_lessons` 并返回 `used_llm=False`。行为等价且路径更单一，文档元信息「生成: 规则要点」正确。
- **环境修复（F001·环境）**：`.venv` 缺 pytest（`uv run pytest` 落到了不含 scapy 的临时环境，导致 `import src.main` 报 `No module named 'scapy'`）。`uv sync --extra dev` 后 `uv run python -m pytest` 与 scapy 均就位；`tests/unit/test_llm_client.py` 的 8 个存量失败随之消失（原为 httpx mock URL 解析，属环境漂移）。
- **既有失败（F002·与特性无关）**：`tests/integration/test_web_experiment.py` 2 例需 `DEEPSEEK_API_KEY`（`build_graph` 时 `RuntimeError: ... not set`），本特性未触碰 `graph.py`，留待有 key 环境验证。

### 测试结果

| 范围 | 结果 |
|------|------|
| lessons 单元（records/stats/render/segment/extract） | 26 通过 |
| lessons 集成（generate_lessons + main 标记） | 7 通过 |
| `tests/unit/` 全量 | 417 通过 |
| `tests/integration/` 全量 | 91 通过 + 2 既有失败（需 API key） |

### 宪法核对

- 一、先想清楚再动手：✅ spec→plan→tasks 全就位后才实现。
- 二、闭环驱动：✅ 幂等增量即回馈闭环；converge 已对照规格逐条核对。
- 三、测试伴随：✅ 新增 33 例全绿，LLM 全程 mock 离线可跑（SC-002/SC-005）。
- 四、安全优先：✅ 只读日志、不产生流量、不触碰 allowlist/HITL。
- 五、可观测驱动：✅ 教训严格从 rtt/loss/http_during 实测导出，「无观测」标注不臆断（SC-002）。
- 六、配置单一来源：✅ LLM key/model 读 env，路径 CLI 可覆盖，无硬编码（FR-008）。
- 文档真实性：✅ CLAUDE.md 命令与 Key Files 已同步 lessons 脚本与 `src/lessons/`。

