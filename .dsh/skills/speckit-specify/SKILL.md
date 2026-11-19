---
name: speckit-specify
description: "把自然语言需求写成功能规格 spec.md：生成特性编号与目录、更新 .specify/feature.json、产出可测试的功能需求与成功标准。触发词：写规格、功能规格、spec、specify、规格驱动。用法：'speckit-specify：做一个团队协作平台，用户可以创建项目、分配任务、评论、在看板列之间拖动任务（第一阶段无登录）'。"
---

# speckit-specify：写功能规格

把触发消息里的自然语言描述变成 `specs/<NNN>-<短名>/spec.md`（中文，按 spec-template 结构），并更新 `.specify/feature.json` 指向当前特性目录。

## 前置校验

- `.specify/` 必须存在：否则报错「项目尚未初始化，请先运行 speckit-init」。
- 读取 `.specify/feature.json`（若存在且指向有效目录）：本次是对既有特性的规格修订，写回原目录；不存在：本次是新建特性。

## 用户输入

触发消息中技能名之后的文字就是功能描述。为空则报错「缺少功能描述」，请用户补充。

## 执行步骤

1. **生成短名**：2-4 个词、kebab-case、尽量动作-名词（如 user-auth、fix-payment-timeout）；保留技术词与缩写（OAuth2、API、JWT）。
2. **确定特性目录编号**：扫描 `specs/` 现有目录，NNN = 最大编号 + 1（3 位补零，无现有目录从 001 开始）；若该编号目录已存在（罕见冲突）继续 +1。**绝不覆盖已有目录**。目录名 = `<NNN>-<短名>`。
3. **解析模板**：项目根运行 `bash .specify/scripts/bash/resolve-template.sh spec-template --json`，取 `TEMPLATE_CONTENT`；失败则停下报告。
4. **建目录与文件**：`mkdir -p specs/<NNN>-<短名>`，把模板内容写入 `specs/<NNN>-<短名>/spec.md`。
5. **更新 `.specify/feature.json`**：写入实际路径值，如 `{"feature_directory": "specs/001-user-auth"}`。
6. **读宪法**（若 `.specify/memory/constitution.md` 存在）：后续内容不得违背其原则。
7. **填充规格**（按 spec-template 结构与编号体系）：
   - 从描述提取关键概念：角色、动作、数据、约束。
   - 不明确处先做合理假设并写进「假设」节；仅当显著影响范围/体验且无合理默认时，用 `[需要澄清：问题]` 标记，**最多 3 个**，按影响排序（范围 > 安全/隐私 > 体验 > 技术细节）。
   - 用户故事：按重要性排序 P1/P2/P3，每个含「为什么这个优先级」「独立测试方式」「验收场景（给定/当/那么）」；每个故事可独立交付 MVP。
   - 功能需求 FR-xxx：每条可测试、无实现细节（不写语言/框架）。
   - 成功标准 SC-xxx：可度量、技术无关（时间、性能、满意度等定量/定性指标）。
   - 关键实体、边界情况如实填写。
8. **质量自检**：逐项核对 spec-template「需求清单」节；失败项修订规格并重跑，最多 3 轮；仍失败则在清单备注里记录并告知用户。
9. **生成需求质量清单**：写 `specs/<NNN>-<短名>/checklists/requirements.md`（内容质量 / 需求完整性 / 就绪度三类勾选项，见官方清单结构）。
10. **澄清轮**（有 `[需要澄清]` 标记时）：一次性呈现全部问题，每题给上下文引用 + 选项表（A/B/C + 自定义，含各自影响），等待用户回答后回填规格并重跑自检。

## 完成汇报

新特性目录与 spec.md 路径、feature.json 更新情况、FR/SC 数量、待澄清问题数、自检结论。

## 下一步

汇报后停下（分步触发）。提示：可选 `speckit-clarify：澄清规格歧义`；否则 `speckit-plan：给出技术选型与实现计划`。
