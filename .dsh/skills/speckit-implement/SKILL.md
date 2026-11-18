---
name: speckit-implement
description: "按 tasks.md 的依赖顺序逐任务实现功能，自动勾选完成的任务。触发词：开始实现、implement、执行任务、写代码。用法：'speckit-implement'。"
---

# speckit-implement：按计划实现

按 tasks.md 的依赖顺序自动逐任务执行，直到全部完成（这是本技能内部的自动执行；跨技能仍然分步触发）。tasks.md 不完整时建议先跑 speckit-tasks。

## 前置校验

- `.specify/feature.json` 必须存在：否则报错「项目尚未初始化，请先运行 speckit-init」；其指向的 spec.md、plan.md、tasks.md 必须齐全：缺失分别报错「先运行 speckit-specify」「先运行 speckit-plan」「先运行 speckit-tasks」。

## 执行步骤

1. **初始化**：项目根运行 `bash .specify/scripts/bash/check-prerequisites.sh --json --require-spec --require-tasks --include-tasks`，解析 `FEATURE_DIR` 与 `AVAILABLE_DOCS`（全部用绝对路径）。
2. **检查清单门禁**（`FEATURE_DIR/checklists/` 存在时）：
   - 扫描目录下所有清单文件的 `- [ ]` / `- [x]` 行，统计总数/已勾/未勾，输出状态表。
   - 全部勾选：自动继续。存在未勾项：**停下询问**「有清单项未勾选，是否仍继续实现？（是/否）」；用户同意才继续。**绝不修改任何清单文件或标记**（标记是评审者的）。
3. **加载上下文**：tasks.md（任务全集与执行顺序，必需）、plan.md（技术栈与结构，必需）、data-model.md / contracts/ / research.md / quickstart.md / 宪法（若有）。
4. **项目设置核对**：按 plan.md 技术栈创建/核对忽略文件（git 仓库则 .gitignore；Docker 则 .dockerignore；Node 项目 node_modules/、dist/、.env* 等），已存在则只补缺失的关键模式。
5. **解析 tasks.md 结构**：阶段、依赖、任务 ID/描述/文件路径/[P] 并行标记、执行顺序。
6. **执行实现**（本技能核心规则）：
   - 按阶段推进，前一阶段完成再进下一阶段。
   - 顺序任务逐个执行；[P] 任务可并行处理；同一文件的任务必须串行。
   - **TDD**：任务列表里有测试任务时，先写测试确认失败再写实现（若项目采用 TDD）。
   - 每个任务完成后**立即把 tasks.md 中该任务的 `- [ ]` 改为 `- [X]`**。
   - 汇报每个任务的完成进度；非并行任务失败即停止并报告错误上下文；并行任务失败的单独报告，其余继续。
7. **完成校验**：核对全部任务完成、实现与规格/计划一致、测试通过；未完成项列出并说明。

## 完成汇报

已完成/失败任务数、tasks.md 勾选情况、测试结果、与规格的符合性结论。

## 下一步

汇报后停下（分步触发）。提示：`speckit-converge：评估实现并追加剩余工作`。
