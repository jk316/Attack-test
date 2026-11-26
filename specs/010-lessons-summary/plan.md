# 实施计划：从实验日志提炼经验教训（lessons）

**特性目录**: `specs/010-lessons-summary/` | **日期**: 2026-11-25 | **规格**: [spec.md](spec.md)

**输入**: 来自 `specs/010-lessons-summary/spec.md` 的功能规格

## 摘要

新增一个独立脚本 `scripts/generate_lessons.py` 与一个 `src/lessons/` 包：脚本读取 `data/experiment.jsonl`，按 `run_id` 分组，为每个尚未总结的 run 生成 `lessons/{run_id}.md`（幂等，已存在则跳过）。文档由「规则统计骨架（确定性、离线）」+「LLM 叙事（DeepSeek，可降级）」两段组成；`src/main.py` 向每日 agent 日志写 `[RUN START]/[RUN END]` 标记，脚本据此切分该 run 的对话片段并入叙事上下文，旧日志无标记时优雅降级为仅用 jsonl。

## 技术上下文

**语言/版本**: Python ≥3.11（当前 venv 3.13.11）

**主要依赖**: 无新增运行时依赖——复用 `openai`（DeepSeek）与 `src/llm/client.py`；CLI 用标准库 `argparse`；测试用 pytest

**存储**: 文件读写——`data/experiment.jsonl`（读）、`data/agent-YYYY-MM-DD.log`（读）、`lessons/{run_id}.md`（写）；不新增持久化存储

**测试**: pytest（`uv run pytest tests/unit/ tests/integration/`），标记 unit/integration；LLM 调用在测试中一律 mock

**目标平台**: Linux 服务器（实验运行）+ macOS/Windows（开发）；脚本为纯 I/O + 纯函数，跨平台无 OS 特定逻辑

**项目类型**: CLI 脚本 + 纯 Python 包（非 Agent 工具集）

**性能目标**: 单 run 总结（无 LLM 时）< 100ms；LLM 叙事 < 20s（一次 API 调用）；不阻塞实验主流程（脚本独立运行）

**约束**: 幂等（宪法「闭环驱动」的增量形式）；配置来自环境变量/`experiment.json`（宪法「配置单一来源」）；不得张冠李戴关联对话（FR-006）；LLM 失败不阻断（FR-004）

**规模/范围**: 1 个新包 `src/lessons/`（5 模块）+ 1 个脚本 + 1 个 main.py 改动点（2 行日志）+ 1 个既有模块小改（`src/llm/client.py` 加 `chat_text`）+ 3 个测试文件

## 宪法检查

*门禁：阶段 0 研究前必须通过；阶段 1 设计后复查。*

| 宪法原则 | 结论 |
|----------|------|
| 一、先想清楚再动手 | ✅ spec.md（已批准）→ 本 plan → tasks，实现前全部就位 |
| 二、闭环驱动 | ✅ 本特性按 specify → plan → tasks → implement → converge 推进；脚本的幂等增量处理本身就是「回馈闭环」——已总结的 run 不再重复 |
| 三、测试伴随 | ✅ R9：`test_lessons_records.py` / `test_lessons_stats.py` / `test_lessons_extract.py` / `test_lessons_segment.py` + CLI 集成用例，LLM 全程 mock |
| 四、安全优先 | ✅ 本特性只读日志、不产生流量；LLM 提示仅含日志事实，不触碰 allowlist/HITL |
| 五、可观测驱动 | ✅ 经验教训严格从 `rtt/loss/http_during` 实测数据导出，无观测则标注「无观测」不臆断 |
| 六、配置单一来源 | ✅ FR-008：LLM key/model 读环境变量，路径默认值与 CLI 可覆盖，不在代码硬编码 |
| 附加约束：跨平台 / 文档真实性 | ✅ 纯 I/O 无 OS 特定逻辑；CLAUDE.md 的脚本/工具表在 converge 阶段同步 |

**结论**: 无违反项，复杂度追踪不适用。

## 项目结构

### 文档（本功能）

```text
specs/010-lessons-summary/
├── spec.md              # 功能规格（specify 产出）
├── checklists/
│   └── requirements.md  # 需求质量检查清单（specify 产出）
├── plan.md              # 本文件（plan 产出）
├── research.md          # 阶段 0 产出
├── data-model.md        # 阶段 1 产出
├── contracts/
│   └── lessons.md       # 阶段 1 产出（CLI/命名/文档结构/标记/LLM/降级契约）
├── quickstart.md        # 阶段 1 产出
├── quickstart.sh        # 阶段 2/实现期产出（一键验证）
└── tasks.md             # 阶段 2 产出（tasks 步骤，非本步）
```

### 源代码（仓库根）

```text
src/lessons/
├── __init__.py          # 新：导出公共 API
├── records.py           # 新：读 experiment.jsonl → 按 run_id 分组 → 过滤真实 id → 排序
├── stats.py             # 新：规则统计（观测表/最佳一轮/趋势/收敛启发式）纯函数
├── segment.py           # 新：按 [RUN START]/[RUN END] 切分 agent 对话片段 + 降级
├── extract.py           # 新：LLM 叙事（DeepSeek）+ 规则要点降级
└── render.py            # 新：渲染 lessons/{run_id}.md

scripts/
└── generate_lessons.py  # 新：CLI 入口（增量幂等处理器）

src/
├── main.py              # 改：experiment 运行写 [RUN START]/[RUN END] 标记（FR-005）
└── llm/
    └── client.py        # 改：新增 chat_text()（返回原始文本，供叙事用）

tests/
├── unit/
│   ├── test_lessons_records.py   # 新：分组/过滤/排序
│   ├── test_lessons_stats.py     # 新：观测表/最佳一轮/趋势/收敛
│   ├── test_lessons_extract.py   # 新：LLM 叙事 + 降级（mock）
│   └── test_lessons_segment.py   # 新：标记切分 + 无标记降级
└── integration/
    └── test_generate_lessons.py  # 新：CLI 端到端（fixture jsonl + tmp lessons dir + --no-llm）
```

**结构决策**: 核心逻辑放 `src/lessons/`（与 `src/llm/` 同层、纯函数可单测），`scripts/generate_lessons.py` 只做 CLI 参数解析与编排；与既有 `scripts/normalize_experiment_log.py`（`from src.tools.log_tool import ...`）的「脚本薄、逻辑进 src」模式一致。不新建目录之外的依赖。

## 实施阶段

- **阶段 0 · 研究**：✅ 产出 `research.md`（R1~R9：模块位置、分组来源、id 识别、评分口径、收敛判定、LLM 复用、对话关联、CLI/幂等、测试策略）。
- **阶段 1 · 设计**：✅ 产出 `data-model.md`、`contracts/lessons.md`、`quickstart.md`；宪法检查复查通过（见上表）。
- **阶段 2 · 任务生成**：由 tasks 步骤依据本计划产出 `tasks.md`（本步不创建）。

## 复杂度追踪

> 仅当宪法检查存在需论证的违反时填写

无违反项。
