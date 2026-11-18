---
name: speckit-analyze
description: "对 spec.md / plan.md / tasks.md 做跨制品一致性检查（只读），输出冲突、缺口、歧义报告。触发词：一致性检查、analyze、规格分析。用法：'speckit-analyze'。"
---

# speckit-analyze：跨制品一致性分析

实现前检查 spec.md、plan.md、tasks.md 三个制品之间的一致性。**严格只读**：不修改任何文件，只输出报告；修复由用户在源头手工进行（或明确批准后由对应技能重跑）。

## 前置校验

- `.specify/feature.json` 必须存在：否则报错「项目尚未初始化，请先运行 speckit-init」；其指向的 spec.md、plan.md、tasks.md 必须齐全：缺失分别报错「先运行 speckit-specify」「先运行 speckit-plan」「先运行 speckit-tasks」。

## 执行步骤

1. **初始化**：项目根运行 `bash .specify/scripts/bash/check-prerequisites.sh --json --require-spec --require-tasks --include-tasks`，解析 `FEATURE_DIR` 与 `AVAILABLE_DOCS`；派生 SPEC/PLAN/TASKS 绝对路径（data-model.md 可选）。
2. **加载制品（渐进披露）**：spec 取功能需求 FR-xxx、成功标准 SC-xxx、用户故事、边界情况；plan 取架构/选型、阶段、技术约束；tasks 取任务 ID、阶段分组、[P] 标记、文件路径；宪法若存在必读（**宪法冲突自动判 CRITICAL，要求改制品而非稀释原则**）。
3. **建立语义模型**（内部表示，不回显原文）：需求清单（每个 FR/SC 一个稳定键）；用户故事/动作清单；任务覆盖映射（任务 ↔ 需求/故事）；受约束字段清单与引用映射（有 data-model.md 时）。
4. **检测**（最多 50 条发现，溢出进汇总）：
   - **重复**：近重复需求，标记表述较差者合并。
   - **歧义**：无度量标准的模糊形容词（快、安全、易用）；未解决占位符（TODO、??? 等）。
   - **缺规格**：动词无宾语/无度量结果；故事缺验收标准对齐；任务引用 spec/plan 中未定义的文件或组件。
   - **宪法对齐**：任何与 MUST 原则冲突的需求/计划元素（CRITICAL）。
   - **任务覆盖**：FR/SC 无任务覆盖；任务无对应需求（孤儿任务）；同一文件的冲突任务未串行。
   - **约束一致性**（有 data-model.md 时）：每个受约束字段在实现任务中有明确引用，任务约束与模型一致。
5. **严重度分级**：CRITICAL（宪法冲突/覆盖缺口）/ HIGH（歧义影响范围）/ MEDIUM / LOW，并给每条发现定位（制品 + 章节/任务 ID）。
6. **输出报告**：按严重度分组的发现表（发现、位置、问题、建议修复源头），无发现则明确说「一致，可以进入实现」。

## 完成汇报

发现总数与分级统计；只读声明（未修改任何文件）。

## 下一步

汇报后停下（分步触发）。有 CRITICAL/HIGH 发现：提示先在源头修复并重跑 analyze；干净：提示 `speckit-implement：开始实现`。
