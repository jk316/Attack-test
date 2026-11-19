---
name: speckit-converge
description: "实现完成后评估代码库与规格的一致性，把剩余/偏差工作追加为任务。触发词：收敛、converge、收尾评估。用法：'speckit-converge'。"
---

# speckit-converge：收敛评估

实现完成后，对照 spec/plan/tasks/宪法检查真实代码，把「缺失 / 部分完成 / 相矛盾 / 计划外」的工作追加为 tasks.md 新任务（本技能只追加任务，**不删代码**）。

## 前置校验

- `.specify/feature.json` 必须存在：否则报错「项目尚未初始化，请先运行 speckit-init」；其指向的 spec.md、plan.md、tasks.md 必须齐全：缺失分别报错「先运行 speckit-specify」「先运行 speckit-plan」「先运行 speckit-tasks」。

## 执行步骤

1. **初始化**：项目根运行 `bash .specify/scripts/bash/check-prerequisites.sh --json --require-spec --require-tasks --include-tasks`，解析 `FEATURE_DIR`；派生 SPEC/PLAN/TASKS 路径。
2. **加载制品（渐进披露）**：spec 取 FR/SC（只含需要构建工作的项，排除上线后 KPI）、用户故事与验收场景、边界情况；plan 取架构决策、阶段、将创建/修改的文件清单、技术约束；tasks 取任务 ID（用于计算下一个 ID）、阶段分组、文件路径；宪法若存在取原则与 MUST/SHOULD 规范语句。
3. **建立意图清单**（内部表示）：每个 FR/SC/验收场景一个稳定键（如 `US1/AC2`），连同计划决策与宪法义务；代码范围图 = plan/tasks 中命名的文件路径 + 概念关键词定位的源文件（**不超出制品定义的范围**）。
4. **评估代码并分类发现**：对意图清单逐项检查当前代码，有差距才记 Finding：
   - `missing` 完全缺失；`partial` 部分完成；`contradicts` 与意图或宪法 MUST 冲突；`unrequested` 计划外的代码（仅提示，追加评审任务，不删除）。
   - 每条 Finding 记：稳定 ID、来源引用（FR-x / USy/ACz / 任务 Txxx）、差距类型、严重度、证据（文件/区域）。
   - **代码很少或没有**：整个规格范围按 `missing` 处理，不视为失败。
   - **无差距**：走「已收敛」分支。
5. **会话内摘要**：按严重度输出发现摘要表（ID、类型、来源、说明、证据）。
6. **追加任务**：按依赖顺序把 Finding 转成 tasks.md 新任务（T 编号接着现有最大号递增，阶段号顺延），描述含来源引用与证据；无发现则报告「已收敛」，不追加。
7. **汇报**：发现总数、追加任务数、下一步建议。

## 完成汇报

发现摘要 + tasks.md 追加内容概览（或「已收敛」结论）。

## 下一步

汇报后停下（分步触发）。有追加任务：提示 `speckit-implement：继续实现剩余任务`；已收敛：提示「本特性 SDD 流程完成，新功能从 speckit-specify 开始」。
