# 阶段 0 研究：从实验日志提炼经验教训

**特性**: `specs/010-lessons-summary/` | **日期**: 2026-11-25

每个条目按「决策 / 理由 / 备选方案」记录。

## R1 核心逻辑的位置

- **决策**: 新建 `src/lessons/` 包（`records.py` / `stats.py` / `segment.py` / `extract.py` / `render.py`），`scripts/generate_lessons.py` 只做 CLI 参数解析与编排。
- **理由**: 规则统计与渲染必须是纯函数才能离线单测（宪法「测试伴随」）；与 `src/llm/`（独立于 Agent 循环的辅助模块）同层；既有脚本（`normalize_experiment_log.py`）已示范「脚本薄、逻辑进 src」。
- **备选**:
  - 全部塞进一个 `scripts/generate_lessons.py`——无法单元测试、脚本臃肿，拒绝。
  - 放进 `src/tools/`——该目录是 Agent 工具/监控，语义不符，拒绝。

## R2 run 分组来源

- **决策**: 用 `experiment.jsonl` 每行的 `run_id` 字段精确分组（`src/tools/log_tool.py` 的 `generate_run_id()` 注入），不做「按 iteration 重置切分」的推断。
- **理由**: `run_id` 是程序写入的权威键，精确、无歧义；`normalize_experiment_log.py` 的「iteration 重置切分」是为 legacy 数据补 run_id 的迁移手段，本特性只消费已带 run_id 的行。
- **备选**: 复用 `split_runs()` 按 iteration 重置切分——会把「有 run_id 的新数据」与「无 run_id 的 legacy」混在一起，且无法与 lessons 文件按 run_id 去重，拒绝。

## R3 真实 run_id 的识别

- **决策**: 仅处理匹配 `^\d{8}T\d{6}-[0-9a-f]{6}$` 的 run_id；其余（`unknown`、legacy、`legacy-*`）跳过。
- **理由**: `generate_run_id()` 格式为 `YYYYmmddTHHMMSS-<hex6>`；536 行 legacy 无 run_id（被规范化为 `unknown`），不应为它们生成以 `unknown` 命名的文件。
- **备选**: 一并处理 legacy 并给它们合成 id——超出范围（FR-001 明确跳过），拒绝。

## R4 最佳一轮的评分口径

- **决策**: 确定性复合评分，按优先级叠加：`loss`（主信号，×10）→ `rtt`（次信号，×1）→ HTTP 退化（`(1-success_rate)×100` + `(ttfb−baseline)` 归一）。得分最高者为最佳一轮；无观测的行不参与最佳评选。
- **理由**: 闭环目标是「最大化 RTT / 业务退化」，丢包与 RTT 是硬指标，HTTP success_rate/ttfb 是业务指标；权重使「高丢包」优先于「高 RTT」。纯算术、可手算对照（SC-002）。
- **备选**: 只按 rtt 排序——忽略丢包与 HTTP 退化，违背「可观测驱动」的多信号意图，拒绝。

## R5 收敛判定的口径

- **决策**: 收敛用启发式标注（非硬断言）：取有效 RTT 序列，若末段连续轮次不再创新高 → 「可能已收敛」，否则「未收敛（RTT 仍在上升）」；同时报告实际轮数与 RTT 首末趋势。文档中显式标注「启发式」。
- **理由**: `experiment.jsonl` 不含 `max_iters`/`no_improve_limit`，无法精确判定「是否因无改善提前停止」；趋势与「是否创新高」是可从数据推出的最诚实信号。
- **备选**: 读 `experiment.json` 的 `no_improve_limit` 反推——配置是运行期快照，可能与历史 run 不一致，且违反「只读日志」的纯粹性，拒绝。

## R6 LLM 叙事的复用方式

- **决策**: 复用 `src/llm/client.py` 的 `LLMClient`，为其新增 `chat_text(messages) -> str`（返回原始文本内容，区别于现有 `chat()` 的 JSON 解析）；key 与模型读 `DEEPSEEK_API_KEY` / `LLM_MODEL`（默认 `deepseek-chat`）。
- **理由**: FR-004 要求「复用项目 DeepSeek 配置」；现有 `chat()` 强制 JSON 解析，叙事需要自然语言文本，故加一个不破坏向后兼容的方法。不引入 `ChatOpenAI`（那是 Agent 循环路径，且带 reasoning_content 往返的复杂度）。
- **备选**:
  - 在 `extract.py` 直接 `openai.OpenAI(...)`——重复 key/model 读取逻辑，DRY 违背，拒绝。
  - 走 `graph.py` 的 `ChatOpenAI`——引入 `thinking` 往返与 LangChain 依赖，重，拒绝。

## R7 agent 对话日志的关联方式

- **决策**: `src/main.py` 在 experiment 运行开始/结束时向每日日志写 `[RUN START] <run_id>` / `[RUN END] <run_id>`（成对）；`segment.py` 按标记切分。旧日志无标记时：按 run_id 内嵌日期定位当日日志 → 无标记则返回 `None` → 降级为仅用 jsonl（不张冠李戴）。
- **理由**: 每日日志的 `[LLM INPUT]` 块无时间戳、无 run_id，顺序关联脆弱且会错配；起止标记是唯一可靠切分，且对旧数据明确降级而非猜。
- **备选**:
  - 按「当日第 k 个 run」与「日志第 k 段」顺序对应——run 与日志块数量/顺序无强保证，错配风险高，拒绝（FR-006「绝不误配」）。
  - 解析 stdout 的 `Run ID:`——不落文件，且 `VerboseCallback` 不含它，拒绝。

## R8 CLI 参数面与幂等

- **决策**: `--log-path`（默认 `data/experiment.jsonl`）、`--data-dir`（默认 `data/`，定位 agent 日志）、`--lessons-dir`（默认 `lessons/`）、`--run-id <id>`、`--latest`、`--force`、`--no-llm`、`--list`。默认处理全部未总结 run（按 run_id 时间序）；`lessons/{run_id}.md` 已存在则跳过，`--force` 重写。
- **理由**: FR-002/FR-007；「默认处理全部未总结」天然满足「每次运营后处理最新」——运营后仅最新一个未总结。
- **备选**: 默认只处理最新一个 run——需显式 `--all` 才能补历史，违背「检测哪些 ID 已总结」的增量意图，拒绝。

## R9 测试策略

- **决策**:
  - `records.py`：分组、过滤 `unknown`/legacy、只留真实格式、按时间排序。
  - `stats.py`：给定 fixture 行，断言观测表、最佳一轮、趋势、收敛标注与手算一致（含「无观测不误判」用例）。
  - `segment.py`：含起止标记的 fixture 日志切出正确片段；无标记返回 `None`；`[RUN START]` 无配对 `[RUN END]` 时返回 `None` 不越界。
  - `extract.py`：mock `LLMClient.chat_text` 返回固定文本 → 叙事段出现；mock 抛异常 / 无 key → 降级要点段出现、不抛。
  - `scripts/generate_lessons.py`（集成）：fixture jsonl + tmp lessons 目录 + `--no-llm` 端到端产出文件；二次运行 0 变更；`--force` 重写；`--list` 只打印不改文件。
  - `main.py` 标记：CLI experiment（mock 图）后当日日志含成对 `[RUN START]/[RUN END]`。
- **理由**: 宪法「测试伴随」（FR-009）；LLM 全程 mock 保证离线可跑（SC-002）。
