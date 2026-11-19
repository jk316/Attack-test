---
name: speckit-checklist
description: "生成需求质量检查清单（checklist.md）——'需求层面的单元测试'，确认规格完整、清晰、一致。触发词：检查清单、checklist、需求质量。用法：'speckit-checklist'。"
---

# speckit-checklist：需求质量检查清单

为当前特性生成定制质量清单：把规格的完整性、清晰度、一致性变成可勾选的检查项，在拆任务之前把需求层面的问题挡下来。

## 前置校验

- `.specify/feature.json` 必须存在：否则报错「项目尚未初始化，请先运行 speckit-init」；其指向的 `spec.md` 必须存在：否则报错「缺少规格，请先运行 speckit-specify」。
- 其指向的 `plan.md` 必须存在：否则报错「缺少实现计划，请先运行 speckit-plan」——本清单结合技术上下文生成，且步骤 1 的脚本要求 plan.md。

## 执行步骤

1. **初始化**：项目根运行 `bash .specify/scripts/bash/check-prerequisites.sh --json --template checklist-template`，解析 `FEATURE_DIR` 与 `TEMPLATE_CONTENT`（清单模板）。
2. **读上下文**：spec.md（用户故事、FR/SC、边界情况、假设）、plan.md（技术上下文，若有）、tasks.md（若已存在）。
3. **生成清单** `specs/<NNN>-<短名>/checklist.md`（按 checklist-template 结构，中文）：
   - 检查项按类别组织（如：内容质量、需求完整性、范围边界、一致性），编号 CHK001… 连续。
   - 每项是「可判定真伪的判据」，不是泛泛建议；项目应能根据规格文字直接判断通过与否。
   - 检查项要覆盖：无实现细节泄漏、FR 可测试且无歧义、SC 可度量且技术无关、验收场景完整、边界情况已列出、范围清晰、假设与依赖已记录、spec/plan/tasks 间无冲突。
4. **初始评审**：按清单逐项评审当前规格，把结论写在清单备注（哪些已满足、哪些待改），但**不改规格本身**。

## 标记语义（重要）

- 清单是**评审者拥有的需求质量产物**：只有评审者（用户或其指定的人）确认判据满足时才打 `[x]`。
- `[x]` ≠ 实现完成。
- speckit-implement 会把本清单的勾选状态作为门禁读取，且**不得修改任何标记**。

## 完成汇报

清单路径、条目数、初始评审中未满足的项。

## 下一步

汇报后停下（分步触发）。提示：`speckit-tasks：拆解实现任务`（清单全部勾选后再进入 implement）。
