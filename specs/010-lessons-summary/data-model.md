# 数据模型：从实验日志提炼经验教训

**特性**: `specs/010-lessons-summary/` | **日期**: 2026-11-25

本特性不新增持久化存储；以下实体描述「读入→统计→渲染」流水线上的数据形状（运行期对象），以及 `lessons/{run_id}.md` 的文件结构。

## 1. 输入：实验日志行（已有，结构不变）

`data/experiment.jsonl` 每行（`src/tools/log_tool.py` 的 canonical schema）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `run_id` | string | `YYYYmmddTHHMMSS-<hex6>`；legacy 行为 `unknown` |
| `iteration` | int \| null | 轮次 |
| `tool` | string | 攻击工具名（`pktgen_*` / `traffic_send` / `mixed_traffic_send` / `trex_*`） |
| `params` | object | `target_ip`/`dst_port`/`duration_ms`/`pkt_size`/`pps`/`rate_pct`/`protocol`/`extras` |
| `results` | object | 实测结果（含 HTTP 退化的 `success_rate`/`avg_ttfb_ms` 等） |
| `rtt` | float \| null | 观测 RTT(ms)，缺失为 null |
| `loss` | float \| null | 丢包率(%)，缺失为 null |
| `timestamp` | string | ISO 8601（UTC） |

## 2. 实体

### Run（`records.py`）

一次实验运行的聚合视图。

| 属性 | 类型 | 来源 |
|------|------|------|
| `run_id` | str | 分组键 |
| `rows` | list[dict] | 该 run 的全部 jsonl 行（按 iteration 排序） |
| `target_ip` | str \| None | 第一行含 `params.target_ip` 的值 |
| `start_ts` / `end_ts` | str \| None | 首/末行的 `timestamp` |
| `iterations` | int | `rows` 数量 |

### IterationObservation（`stats.py`，由行派生）

| 属性 | 类型 | 说明 |
|------|------|------|
| `iteration` | int | 轮次 |
| `tool` | str | 工具名 |
| `target_ip` | str \| None | 目标 |
| `key_params` | str | 关键参数摘要（pps/rate/duration/pkt_size 等非空项） |
| `rtt` | float \| None | 观测 RTT |
| `loss` | float \| None | 丢包率 |
| `http_success_rate` | float \| None | 从 `results` 提取 |
| `http_ttfb_ms` | float \| None | 从 `results` 提取 |
| `has_observation` | bool | rtt/loss/http 至少一项非 None |

### RunStats（`stats.py`）

| 属性 | 类型 | 说明 |
|------|------|------|
| `observations` | list[IterationObservation] | 每轮观测 |
| `best` | IterationObservation \| None | 最佳一轮（复合评分最高；无观测则为 None） |
| `best_score` | float \| None | 最佳轮得分 |
| `trend` | str | `上升 / 下降 / 平稳 / 无数据`（首末有效 RTT 对比） |
| `converged` | str | 启发式标注：`可能已收敛 / 未收敛 / 无数据` |
| `tool_counts` | dict[str, int] | 各工具出现次数 |

### RunSegment（`segment.py`）

| 属性 | 类型 | 说明 |
|------|------|------|
| `run_id` | str | 归属 run |
| `text` | str \| None | 每日日志中该 run 的对话片段；无标记/未定位则为 None |

### Lesson（`render.py` 输出 → `lessons/{run_id}.md`）

Markdown 文档，固定章节（见 `contracts/lessons.md` 第 3 节）：

```text
# 经验教训 · {run_id}
> 元信息（目标 / 时间 / 轮数 / 生成方式）

## 观测概览            （规则统计：每轮表 + 工具分布）
## 关键结论            （规则统计：最佳一轮 / 趋势 / 收敛）
## 经验教训            （LLM 叙事，或降级要点）
## 下次实验建议        （LLM 叙事，或降级要点）
```

## 3. run_id 格式

正则 `^\d{8}T\d{6}-[0-9a-f]{6}$`。示例：`20261125T070649-9e1fe6`。不匹配者（`unknown`、`legacy-*`）不入 lessons。

## 4. 状态流转（脚本编排）

```text
load_runs(log_path)  ──▶  runs（按 run_id 时间序，已过滤）
       │
       ▼
targets = [r for r in runs if 需处理]      # 幂等：lessons/{run_id}.md 不存在 或 --force
       │                                   # --run-id/--latest 则先收窄
       ▼
对每个 run:  summarize(stats) ─▶ segment(run_id) ─▶ narrative(extract) ─▶ render ─▶ 写 lessons/{run_id}.md
```

- 无 LLM key / LLM 失败 / `--no-llm` → `narrative` 走规则要点分支（不改变其余流程）。
- `segment` 返回 `None` → 叙事仅用 jsonl 统计，不报错。
- `lessons/` 目录不存在 → 自动创建。
