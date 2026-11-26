# 功能规格：从实验日志提炼经验教训（lessons）

**特性目录**: `specs/010-lessons-summary/`

**创建日期**: 2026-11-25

**状态**: 草案

**输入**: 用户描述："日志文件包含每次运行的 run ID。每次运营后，按最新 ID 找到最新实验记录，查看其全部日志记录，提取可用经验教训，总结输出到 lessons 文件夹；输出文件名以 ID 命名，据此检测哪些 ID 已总结过。按 SDD 方式工作。"

（澄清后：提取方式 = 混合；触发方式 = 独立脚本；日志范围 = experiment.jsonl + agent 对话日志）

## 用户场景与测试（必填）

### 用户故事 1 - 独立脚本按 run_id 增量生成经验教训文档（优先级：P1）

实验员在（手动或定时）跑完实验后，运行 `scripts/generate_lessons.py`，脚本读取 `data/experiment.jsonl`，按 `run_id` 分组，为每个尚未总结的 run 生成 `lessons/{run_id}.md`；已存在同名文件的 run 自动跳过。首次运行处理最新（及所有未总结）的 run，再次运行零新增。

**为什么是这个优先级**: 这是本变更的核心诉求——把「每次运营后总结一次」变成可重复、幂等、可自动化的动作。没有它，其余（统计、LLM 叙事、对话关联）都无处落脚。单靠 experiment.jsonl + 规则统计即可交付可用的 MVP。

**独立测试方式**: 用 fixture 的 experiment.jsonl（含 2 个真实 run_id）运行脚本，断言 `lessons/` 下出现两个 `{run_id}.md`；再次运行断言无新文件、无改动（`--force` 则重写）。

**验收场景**:

1. **给定** experiment.jsonl 含 run `A`、`B`（均无 lessons 文件），**当** 运行脚本（默认），**那么** 生成 `lessons/A.md` 与 `lessons/B.md`，内容非空。
2. **给定** `lessons/A.md` 已存在，**当** 再次运行脚本，**那么** 跳过 A、只处理仍缺文件的 run，A 的文件字节不变。
3. **给定** `lessons/A.md` 已存在，**当** 运行 `--force`，**那么** 重写 A。
4. **给定** experiment.jsonl 含 `run_id="unknown"` 或 legacy 行，**当** 运行脚本，**那么** 跳过这些行（不为 "unknown" 生成文件）。

---

### 用户故事 2 - 规则统计层：确定性观测概览与关键结论（优先级：P2）

脚本从单个 run 的结构化行（iteration/tool/params/results/rtt/loss/timestamp）计算出：每轮观测表、最佳一轮（按 RTT/丢包/HTTP 退化综合）、RTT 随轮次趋势、是否收敛。此层纯确定性、不依赖 LLM，是文档的「骨架」。

**为什么是这个优先级**: 规则统计是可验证、可复现、离线可跑的部分，也是 LLM 叙事的事实基础。即使后续 LLM 不可用，它也能独立产出有意义的文档，是混合方案里「必选」的一半。

**独立测试方式**: 以 fixture 的行构造单个 run，调用纯函数，断言返回的最佳轮次、趋势方向、收敛判定与手算一致；渲染出的 Markdown 含正确数字。

**验收场景**:

1. **给定** 一个 run 的 5 行（RTT 逐轮 1.2→0.9→0.9→32.8→167），**当** 计算统计，**那么** 最佳一轮为第 5 轮（或按指定口径），趋势标注「显著上升」。
2. **给定** 行含 `results`/`params` 里的 HTTP 退化字段（success_rate/ttfb），**当** 计算统计，**那么** 结论纳入 HTTP 退化，而非仅看 RTT。
3. **给定** 行缺失 rtt/loss（观测不可用），**当** 计算统计，**那么** 该轮标注「无观测」，不误判为最优。

---

### 用户故事 3 - LLM 叙事层：语义化经验教训与降级（优先级：P2）

脚本在规则骨架之上，调用 DeepSeek（复用项目 LLM 配置）生成「经验教训 / 下次实验建议」的语义化段落，作为文档的叙事部分。当无 API key、调用失败或 `--no-llm` 时，降级为规则派生的要点列表，输出仍然成功。

**为什么是这个优先级**: 这是「混合」里增值的一半，把结构化事实转成可读、可行动的经验。但它依赖外部服务，必须可降级，不能因 LLM 失败而阻断产出。

**独立测试方式**: mock LLM 返回固定文本，断言其出现在文档叙事段；mock 抛异常（或清空 `DEEPSEEK_API_KEY`），断言降级段出现且脚本退出码 0。

**验收场景**:

1. **给定** 已配置 `DEEPSEEK_API_KEY` 且 LLM 可用，**当** 运行脚本，**那么** 文档含 LLM 生成的「经验教训」段。
2. **给定** 无 `DEEPSEEK_API_KEY` 或调用抛错，**当** 运行脚本，**那么** 文档含规则派生的要点段（标注「未使用 LLM」），且退出码 0。
3. **给定** `--no-llm`，**当** 运行脚本，**那么** 不发起任何 LLM 请求，直接产出规则要点。

---

### 用户故事 4 - 关联 agent 对话日志作为叙事上下文（优先级：P3）

`main.py` 在实验开始/结束时向每日日志写 `[RUN START] <run_id>` / `[RUN END] <run_id>` 标记；脚本据此从 `data/agent-YYYY-MM-DD.log` 切出该 run 的对话片段（含 LLM 推理与最终总结），并入 LLM 叙事上下文。对无标记的旧日志，脚本按日/序 best-effort 关联，关联失败则优雅降级为仅用 jsonl（绝不张冠李戴）。

**为什么是这个优先级**: 对话片段里 Agent 自己已经反思过「哪些攻击有效」，是最有信息量的经验来源，但它需要 main.py 侧加标记才能可靠切分，属增量增强，且对旧数据只能降级，故列 P3。

**独立测试方式**: 用含 `[RUN START]/[RUN END]` 标记的 fixture 日志，断言 `extract_run_segment(run_id, log)` 返回正确片段；用无标记日志断言返回空并触发降级；main.py 侧断言 experiment 模式日志含成对标记。

**验收场景**:

1. **给定** 每日日志含某 run 的起止标记，**当** 切分，**那么** 返回该 run 区间内的对话文本。
2. **给定** 每日日志无标记（旧数据），**当** 切分，**那么** 返回空片段，脚本降级为 jsonl-only，不把别的 run 的对话错配进来。
3. **给定** 运行一次 CLI experiment，**当** 查看当日 agent 日志，**那么** 含 `[RUN START] <run_id>` 与 `[RUN END] <run_id>`（成对出现）。

---

## 边界情况

- **`run_id="unknown"` 或 legacy 行**：跳过，不为 "unknown" 生成文件。
- **lessons 文件已存在**：默认跳过；`--force` 重写。
- **无 LLM key / LLM 失败 / 网络不可达**：降级为规则要点，退出码 0，不阻断。
- **run 无结构化行或行无 rtt/loss**：仍生成文档，观测表标注「无观测」，结论据可用字段给出，不崩溃。
- **`data/experiment.jsonl` 缺失/空**：脚本退出码非零并给出明确提示（不生成空文档）。
- **lessons 目录不存在**：自动创建。
- **trex-explore / catalog 模式**：catalog 模式不写 experiment.jsonl 的 run_id 行（无 log_result），天然无 run 可总结；脚本对其无副作用。main.py 的 RUN 标记在 catalog 模式也可写（便于日后扩展），但当前脚本只按 jsonl 驱动。
- **同一 run_id 跨多日日志**：run 正常单日完成；若跨日，按 run 起止标记跨文件拼接（best-effort），失败则降级。
- **`--list` 与 `--latest`**：`--list` 只打印待总结 run_id 不改文件；`--latest` 只处理时间戳最新的一个 run。

## 功能需求（必填）

- **FR-001**: 脚本必须读取 `data/experiment.jsonl`（路径可配），按 `run_id` 分组，仅处理符合真实格式（`YYYYmmddTHHMMSS-<hex6>`）的 run，跳过 `unknown` 与 legacy 行。
- **FR-002**: 每个 run 的产物写入 `lessons/{run_id}.md`；文件已存在且未指定 `--force` 时跳过（幂等）。
- **FR-003**: 规则统计层必须纯确定性、无 LLM/网络依赖，计算：每轮观测表、最佳一轮、RTT 趋势、收敛判定；HTTP 退化（success_rate/ttfb）纳入结论。
- **FR-004**: LLM 叙事层必须复用项目 DeepSeek 配置（`src/llm/client.py` 或 `graph.py` 的模型/API 配置），生成「经验教训 + 下次建议」；无 key、调用失败或 `--no-llm` 时降级为规则派生要点，不得阻断输出。
- **FR-005**: `src/main.py` 必须在 experiment 运行开始与结束时向每日 agent 日志各写一条 `[RUN START] <run_id>` / `[RUN END] <run_id>`（成对），供脚本切分对话片段。
- **FR-006**: 脚本必须支持按起止标记从每日 agent 日志切分 run 的对话片段并并入 LLM 上下文；无标记时 best-effort 关联，关联失败则降级为仅用 jsonl，绝不误配其他 run 的对话。
- **FR-007**: CLI 必须支持：默认处理全部未总结 run；`--run-id <id>` 指定单个；`--latest` 仅最新；`--force` 重写；`--no-llm` 强制规则；`--list` 仅列出待总结；`--log-path`/`--lessons-dir` 可配（默认 `data/experiment.jsonl` 与 `lessons/`）。
- **FR-008**: 配置（LLM key/model、路径、降级）来自环境变量或既有 `experiment.json`，不得在代码硬编码。
- **FR-009**: 必须配套单元/集成测试，覆盖 run 分组、幂等检测、规则统计、LLM 降级、日志切分、CLI 参数解析。

### 关键实体（涉及数据时填写）

- **实验运行（run）**：一次 main.py 实验，由 `run_id` 唯一标识；含 N 轮结构化日志行（experiment.jsonl）+ 一段每日日志对话（agent-YYYY-MM-DD.log）。
- **经验教训文档（lesson）**：`lessons/{run_id}.md`，由「观测概览（规则统计）」「关键结论」「经验教训（LLM 叙事，可降级）」「下次实验建议」组成。

## 成功标准（必填）

### 可度量结果

- **SC-001**: 给定 fixture 且 run 未总结时，脚本单次运行生成 `lessons/{run_id}.md`；二次运行 0 个新文件、0 字节变更（幂等）。
- **SC-002**: 规则统计层单元测试 100% 通过，且全程不访问网络、不依赖 LLM key。
- **SC-003**: 在无 `DEEPSEEK_API_KEY` 环境运行脚本，仍产出含降级要点的文档，退出码 0。
- **SC-004**: 每次 CLI experiment 运行后，当日 agent 日志含成对 `[RUN START]`/`[RUN END]` 标记（可用 grep 断言）。
- **SC-005**: 新增单元/集成测试全绿；既有测试除因 main.py 标记而新增的断言外保持通过。

## 需求清单

<!-- 提交规格前逐项自检；未满足的项目要回到对应章节修订。 -->

- [x] 每个用户故事有明确的优先级与独立测试方式
- [x] 每条 FR 编号连续、可验证，不含未澄清的 [需要澄清] 占位
- [x] 每条 SC 可度量、与技术选型无关
- [x] 边界情况已列出并给出处理方式
- [x] 假设已写明（见下节）

## 假设

- 触发方式为独立脚本（不侵入 main.py 的结束流程做自动总结）；但 main.py 仅新增日志标记（FR-005），属「日志记录」而非「总结触发」，二者不冲突。
- 提取方式为混合：规则统计为骨架、必跑；LLM 叙事为增强、可降级。LLM 复用项目 DeepSeek 配置，不引入新的模型供应商。
- 日志范围含 agent 对话日志（agent-YYYY-MM-DD.log）；其与 run 的关联依赖 main.py 新增的起止标记，旧数据无标记时 best-effort/降级。
- 特性编号沿用项目全局编号（已用至 009），本特性取 010。
- lessons 产物与 output/ 报告同属交付物，纳入 git 跟踪（.gitignore 无需例外）。
- 一次 run 在 experiment.jsonl 中对应 1..N 行（iteration 1..N），`run_id` 由 `generate_run_id()` 生成并注入每行。
