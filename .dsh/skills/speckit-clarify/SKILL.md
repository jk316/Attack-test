---
name: speckit-clarify
description: "针对现有规格提问澄清歧义，把答案回写进 spec.md。触发词：澄清、clarify、需求歧义、规格问答。用法：'speckit-clarify'（全量审问）或 'speckit-clarify：重点关注任务卡的行为——状态变更、评论权限、任务分配'。"
---

# speckit-clarify：澄清规格歧义

对当前特性的 spec.md 做结构化审问，消除规划前的歧义；答案直接回写规格。

## 前置校验

- `.specify/feature.json` 必须存在：否则报错「项目尚未初始化，请先运行 speckit-init」；其 `feature_directory` 指向的 `spec.md` 必须存在：否则报错「缺少规格，请先运行 speckit-specify」。
- 当前特性目录一律以 `.specify/feature.json` 为准。

## 执行步骤

1. 读取当前特性目录下的 `spec.md`（连同 `checklists/requirements.md` 若有）。
2. **生成澄清问题**（按影响排序：范围 > 安全/隐私 > 用户体验 > 技术细节）：
   - 扫描规格中的含糊表述、未定义术语、冲突的验收场景、缺默认值的边界情况。
   - 用户指定了关注领域时只审该领域。
   - 每条问题给出：引用规格相关原文、需要知道什么、建议答案表（选项 A/B/C + 自定义，各附影响说明）。
   - **一次最多 5 个问题，全部一起呈现**，编号 Q1-Q5，等用户回答（如「Q1 选 A，Q2 自定义：……」）。
3. 把答案回写进 spec.md：替换对应 `[需要澄清]` 标记或补进相关章节；保持编号体系与章节结构不变。
4. 同步更新 `checklists/requirements.md`（若存在）：澄清后重新核对相关项并标记。

## 完成汇报

问了几个问题、回答了哪些、spec.md 的具体修改点。

## 下一步

汇报后停下（分步触发）。提示：`speckit-plan：给出技术选型与实现计划`。
