---
name: speckit-tasks
description: "把设计制品拆成依赖有序、可直接执行的任务列表 tasks.md。触发词：拆任务、任务列表、tasks、任务拆解。用法：'speckit-tasks'。"
---

# speckit-tasks：拆解实现任务

把 spec/plan/设计制品变成 `tasks.md`：按用户故事组织、依赖有序、每任务含明确文件路径，可被 speckit-implement 直接逐条执行。

## 前置校验

- `.specify/feature.json` 必须存在：否则报错「项目尚未初始化，请先运行 speckit-init」；其指向的 `spec.md`、`plan.md` 必须存在：缺失分别报错「先运行 speckit-specify」「先运行 speckit-plan」。

## 执行步骤

1. **初始化**：项目根运行 `bash .specify/scripts/bash/setup-tasks.sh --json`，解析 `FEATURE_DIR` 与 `TASKS_TEMPLATE_CONTENT`（脚本只输出路径与模板内容，**不会**创建 tasks.md——由步骤 5 按 TASKS_TEMPLATE_CONTENT 结构写回 tasks.md）。
2. **加载设计文档**（从 FEATURE_DIR）：必需 plan.md（技术栈、结构）、spec.md（用户故事与优先级 P1/P2…）；可选 data-model.md、contracts/、research.md、quickstart.md、checklist.md；宪法若存在一并读。
3. **生成任务**（按 tasks-template 结构与编号体系 T001… 连续）：
   - **阶段 1 搭建**：项目初始化、依赖、lint/格式化。
   - **阶段 2 地基**：阻塞所有用户故事的核心基础设施。
   - **阶段 3+**：每个用户故事一个阶段（按优先级排序），包含：故事目标、独立测试方式、测试任务（仅当规格要求测试或用户要求 TDD 时）、实现任务。
   - **最后阶段**：打磨与横切关注点。
   - 格式要求：`- [ ] TXXX [P] [USn] 描述（含确切文件路径）`；`[P]` 标可并行（不同文件、无依赖）；`[USn]` 标所属故事。
   - 依赖图：用户故事完成顺序；并行示例：每故事给出可并行的任务组。
   - 每个任务足够具体：实现者只凭设计文档 + 该任务描述即可完成，无需额外上下文。
4. **完整性校验**：每个用户故事都有完整任务集且可独立测试；data-model 中每个受约束字段在至少一个实现任务中被明确引用。
5. **写回 tasks.md**：填「任务总览」表（任务 ID / 阶段 / 所属故事 / 可并行 / 说明）、各阶段任务、依赖与执行顺序、实施策略（MVP 优先、增量交付）。

## 完成汇报

tasks.md 路径、任务总数、每故事任务数、可并行机会、各故事独立测试方式、建议 MVP 范围（通常仅用户故事 1）。

## 下一步

汇报后停下（分步触发）。提示：可选 `speckit-analyze：跨制品一致性检查`；然后 `speckit-implement：开始实现`。
