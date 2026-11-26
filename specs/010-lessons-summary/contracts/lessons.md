# 契约：lessons 总结脚本

**特性**: `specs/010-lessons-summary/` | **日期**: 2026-11-25

本契约定义脚本与 main.py 标记的接口边界，供 tasks 与 converge 对照。

## 1. run_id 与文件命名契约

- 仅处理匹配 `^\d{8}T\d{6}-[0-9a-f]{6}$` 的 `run_id`。
- 产物路径：`{lessons_dir}/{run_id}.md`（`lessons_dir` 默认 `lessons/`）。
- 幂等：文件已存在且未指定 `--force` → 跳过，不重写、不改字节。
- 跳过 `unknown`、`legacy-*` 及一切不匹配的行。

## 2. CLI 契约（`scripts/generate_lessons.py`）

| 参数 | 默认 | 说明 |
|------|------|------|
| `--log-path` | `data/experiment.jsonl` | 输入 JSONL |
| `--data-dir` | `data/` | agent 每日日志所在目录 |
| `--lessons-dir` | `lessons/` | 输出目录（自动创建） |
| `--run-id <id>` | — | 仅处理指定 run（可与 `--force` 组合） |
| `--latest` | — | 仅处理时间戳最新的一个 run |
| `--force` | — | 重写已存在的 lessons 文件 |
| `--no-llm` | — | 强制规则要点，不发起 LLM 请求 |
| `--list` | — | 只打印待总结 run_id（不改文件），逗号/换行分隔 |

- 默认（无 `--run-id`/`--latest`/`--list`）：处理全部未总结 run，按 run_id 时间序。
- 退出码：成功 0；`--log-path` 缺失/空/不可读 → 非 0 且打印明确错误；LLM 失败 → 仍 0（降级）。

## 3. Lesson 文档结构契约

```markdown
# 经验教训 · {run_id}

> 目标: {target_ip} ｜ 轮数: {N} ｜ 时间: {start} ~ {end} (UTC) ｜ 生成: {LLM 叙事 | 规则要点}

## 观测概览
| 轮次 | 工具 | 目标 | 关键参数 | RTT(ms) | 丢包% | HTTP成功率 | HTTP TTFB | 备注 |
| ... |

## 关键结论
- 最佳一轮: 第 {k} 轮（{tool}，得分 {score}）
- 趋势: {上升/下降/平稳/无数据}
- 收敛: {可能已收敛/未收敛/无数据}（启发式）

## 经验教训
{LLM 叙事或规则要点}

## 下次实验建议
{LLM 叙事或规则要点}
```

- 无观测的行 `备注` 标注「无观测」，不参与最佳评选。
- 降级时「经验教训/下次实验建议」为规则派生要点，元信息「生成」标注「规则要点（未使用 LLM）」。

## 4. run 起止标记契约（main.py 写、segment.py 读）

- main.py 在 experiment 运行开始写一行：`[RUN START] {run_id}`；结束时写：`[RUN END] {run_id}`（`run_id` 为 `generate_run_id()` 结果）。
- 标记写入「agent」logger（INFO 级别），落 `data/agent-YYYY-MM-DD.log`（与现有 `VerboseCallback` 同一 handler）。
- segment.py 只认 `[RUN START] {id}` … `[RUN END] {id}` 之间的文本；`START` 无配对 `END` 或 `END` 缺失 → 返回 `None`（降级），不越界、不报错。

## 5. LLM 叙事契约

- 输入：结构化 `RunStats`（观测表 + 最佳/趋势/收敛）+ 可选 `RunSegment.text`（对话片段，可能 None）。
- 输出：`经验教训` + `下次实验建议` 两段自然语言 Markdown。
- 复用 `LLMClient`（`DEEPSEEK_API_KEY` / `LLM_MODEL`），新增 `chat_text(messages) -> str`。
- 失败/无 key/`--no-llm` → 规则派生要点，退出码 0。

## 6. 降级契约（优先级从高到低）

1. LLM 不可用（无 key / 调用抛错 / `--no-llm`）→ 叙事段替换为规则要点，其余章节不变。
2. 对话片段不可得（无标记 / 日志缺失）→ 叙事仅用 jsonl 统计，不臆造对话内容。
3. run 无任何观测 → 文档仍生成，观测表标注「无观测」，最佳一轮为 None。
4. `experiment.jsonl` 缺失/空 → 退出码非 0，不生成空文档。
