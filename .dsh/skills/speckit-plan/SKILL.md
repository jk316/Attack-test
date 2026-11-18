---
name: speckit-plan
description: "基于规格生成技术实现计划 plan.md 与设计制品（research/data-model/contracts/quickstart）。触发词：实现计划、技术选型、plan、架构设计。用法：'speckit-plan：用 .NET Aspire + Postgres，前端 Blazor Server 带拖拽看板和实时更新，暴露 REST API'。"
---

# speckit-plan：技术选型与实现计划

把当前特性的 spec.md 变成可执行的实现计划与设计制品。

## 前置校验

- `.specify/feature.json` 必须存在：否则报错「项目尚未初始化，请先运行 speckit-init」。
- 其指向的 `spec.md` 必须存在：否则报错「缺少规格，请先运行 speckit-specify」。

## 用户输入

触发消息中技能名之后的文字是技术选型输入（如「用 .NET Aspire + Postgres」）；为空则本技能提出选型建议并在写计划前与用户确认关键选型。

## 执行步骤

1. **初始化路径**：项目根运行 `bash .specify/scripts/bash/setup-plan.sh --json`，解析 `FEATURE_SPEC`（spec.md 绝对路径）、`IMPL_PLAN`（plan.md 绝对路径）、`FEATURE_DIR`。脚本会在 plan.md 不存在时自动把 plan-template 复制进去。
2. **加载上下文**：读 `FEATURE_SPEC`（用户故事与优先级、FR/SC）与 `.specify/memory/constitution.md`（若有）。
3. **执行计划工作流**（按 plan-template 结构，中文填写）：
   - 「技术上下文」：语言/版本、主要依赖、存储、测试、目标平台、项目类型、性能目标、约束、规模；未知项标 `[需要澄清]`。
   - 「宪法检查」：逐条对照宪法原则评估；有未论证的违反则报错。
   - **阶段 0 研究**：把每个 `[需要澄清]` 与技术选择转为调研项，结论写入 `research.md`（格式：决策 / 理由 / 备选方案）。
   - **阶段 1 设计**：从规格提取实体 → `data-model.md`（实体、字段、关系、校验规则、状态流转）；项目有对外接口时定义契约 → `contracts/`（API/CLI/UI 契约，纯内部项目可跳过）；写 `quickstart.md`（端到端可运行验证场景：前置、启动命令、验证命令、预期结果，不含完整实现代码）。
   - 设计完成后复查「宪法检查」。
4. **写回 plan.md**：把「技术上下文」「宪法检查」「项目结构」「实施阶段」「复杂度追踪」按实际内容填好。

## 完成汇报

plan.md 路径与生成的设计制品清单（research.md / data-model.md / contracts/ / quickstart.md）、宪法检查结论、仍待澄清项（若有）。

## 下一步

汇报后停下（分步触发）。提示：可选 `speckit-checklist：生成需求质量检查清单`；然后 `speckit-tasks：把计划拆成依赖有序的任务`。
