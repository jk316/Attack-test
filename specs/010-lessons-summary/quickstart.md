# Quickstart：验证 lessons 经验教训总结

**特性**: `specs/010-lessons-summary/` | **日期**: 2026-11-25

端到端验证场景。验证目标：按 run_id 增量生成、幂等跳过、规则统计正确、LLM 降级、main.py 起止标记、测试全绿。

## 前置

```bash
uv sync --extra dev
# 可选：export DEEPSEEK_API_KEY=...  # 验证 LLM 叙事；不设则验证降级
```

## 场景 1：从现有日志生成 lessons（P1 验证）

```bash
uv run python scripts/generate_lessons.py --no-llm
```

**预期**:
- 为 `data/experiment.jsonl` 中每个真实格式 run_id（当前约 10 个）生成 `lessons/{run_id}.md`。
- 每个文件含「观测概览 / 关键结论 / 经验教训 / 下次实验建议」四节。
- `unknown` / legacy 行不生成文件。

## 场景 2：幂等（P1 验证）

```bash
uv run python scripts/generate_lessons.py --no-llm
# 再次运行
```

**预期**: 第二次运行打印「已跳过」、0 个新文件、既有文件字节不变。`--force` 则重写：

```bash
uv run python scripts/generate_lessons.py --no-llm --force
```

## 场景 3：待总结检测（`--list`）

```bash
uv run python scripts/generate_lessons.py --list
```

**预期**: 只打印尚未总结的 run_id，不产生任何文件。

## 场景 4：LLM 叙事与降级（P2 验证）

```bash
export DEEPSEEK_API_KEY=...      # 有 key 时
uv run python scripts/generate_lessons.py --latest --force
```

**预期**: 「经验教训 / 下次实验建议」为 LLM 生成的语义化内容。无 key 或 `--no-llm` 时，这两节为规则要点，元信息标注「规则要点（未使用 LLM）」，退出码 0。

## 场景 5：main.py 起止标记（P3 验证）

```bash
uv run python src/main.py --target-ip 10.99.80.160 --max-iters 1 --auto-approve
grep -n "\[RUN START\]\|\[RUN END\]" data/agent-$(date +%F).log
```

**预期**: 当日 agent 日志含成对 `[RUN START] <run_id>` / `[RUN END] <run_id>`。

## 场景 6：测试全绿

```bash
uv run pytest tests/unit/ tests/integration/ -q
```

**预期**: 新增 `test_lessons_records` / `test_lessons_stats` / `test_lessons_extract` / `test_lessons_segment` / `test_generate_lessons` 全绿；既有用例（除 `test_llm_client.py` 的 8 个存量 httpx 失败外）保持通过。

> 一键脚本（实现期提供）：`bash specs/010-lessons-summary/quickstart.sh`。
