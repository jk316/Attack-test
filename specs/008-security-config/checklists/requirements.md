# 需求质量检查清单：安全约束与配置体系（横切关注点）

**目的**: 对 specs/008-security-config 的需求质量进行评审——确认该横切规格完整、清晰、一致、无实现细节泄漏、与宪法完全一致、与事实源一致，且引用其他规格而不重复细节。
**创建**: 2026-11-19
**功能**: [specs/008-security-config/spec.md](../spec.md)

**评审归属**: 本清单是评审者拥有的"需求质量"评审产物。仅当评审者确认该项需求质量标准已满足时，才标记 `[x]`。
**标记语义**: `[x]` 表示该标准已评审并通过（需求质量层面），不代表实现工作完成。

## 检查清单

### 内容质量

- [x] CHK001 spec.md 采用 spec-template 结构（创建日期/输入/用户故事/边界情况/FR/关键实体/SC/需求清单/假设）且为中文撰写
- [x] CHK002 每个用户故事（P1/P2/P3）均含「为什么是这个优先级」「独立测试方式」与给定-当-那么验收场景
- [x] CHK003 FR-001 至 FR-020 编号连续、每条可测试、不含语言/框架/库实现细节
- [x] CHK004 SC-001 至 SC-010 均可度量（100% 比例、延迟、0 冲突等定量指标）且与技术选型无关
- [x] CHK005 [需要澄清] 共 3 条（≤3）且按影响排序（全自动流量可达性 > 配置错误可见性 > 审批展示一致性）

### 需求完整性

- [x] CHK006 覆盖 validate_target allowlist 校验与 fail-closed（FR-001/FR-002/FR-003、SC-006）
- [x] CHK007 覆盖广播/组播与 src_ip 伪造禁令（FR-003/FR-004、SC-002）
- [x] CHK008 覆盖参数上限单一来源，数值与宪法一致（FR-005/FR-006/FR-007：MAX_PPS=20000、MAX_DURATION_S=20、MAX_PACKET_SIZE=1024、MAX_FLOW_COUNT=100、MAX_IAT_JITTER_MS=20、MAX_STREAMS=100、rate≤100%、duration≤60000ms）
- [x] CHK009 覆盖 HITL 门控矩阵：arp_flood/pcap_replay 免 allowlist 但仍审批；stats_monitoring/safe_stop_and_reset 免审批（FR-009）
- [x] CHK010 覆盖 TRex 门控：dry-run 默认、实发审批+静态 IP 扫描（尽力而为）+脚本目录沙箱（FR-010/FR-011）
- [x] CHK011 覆盖配置流：experiment.json→环境变量→调用时读取，CLI 覆盖优先级（FR-013/FR-014）
- [x] CHK012 覆盖 profiles 命名预设与未知预设报错（FR-015）
- [x] CHK013 覆盖 --auto-approve 默认关闭、标记与风险声明（FR-017、故事 3）
- [x] CHK014 覆盖探索模式零流量零审批与 dry-run 零流量（FR-012/FR-019、SC-010）
- [x] CHK015 覆盖文档一致性（docstring/提示词/README 与常量同步，FR-016、SC-008）
- [x] CHK016 以横切方式引用 specs/001–007（「与其他功能规格的关系」表），未重复其工具级细节
- [x] CHK017 边界情况覆盖：白名单缺失/为空、等于上限、非法端口、pcap_replay 豁免、静态扫描漏检、auto-approve×实发、配置超上限、外部 env、运行期改 allowlist

### 就绪度

- [x] CHK018 spec.md 末尾「需求清单」5 项自检全部勾选
- [x] CHK019 与宪法完全一致：原则四（安全优先、allowlist/HITL/上限不可协商）→ FR-001~FR-012、FR-018~FR-020；原则六（配置单一来源、调用时读取、allowlist 唯一管理）→ FR-002/FR-013/FR-014；附加约束（上限数值、文档真实性）→ FR-005/FR-007/FR-016
- [x] CHK020 与事实源一致：上限常量与 CLAUDE.md「Parameter Limits」、README「参数上限」逐项核对一致；门控矩阵与 CLAUDE.md「Allowlist & HITL Gates」、README「HITL/allowlist 门控矩阵」一致；配置流与「Configuration Flow」一致
- [x] CHK021 未修改 .specify/feature.json、未写入其他 specs 目录（仅 specs/008-security-config/）
- [x] CHK022 目录与文件命名符合约定：specs/008-security-config/spec.md、specs/008-security-config/checklists/requirements.md

## 备注

- 仅在评审确认需求质量标准满足后标记 `[x]`
- 仍需澄清、修正或评审者评估的条目保持未勾选
- speckit-implement 把清单勾选状态作为门禁读取，且不得修改标记
- 条目连续编号便于引用
- 相关注释与发现直接写在条目旁
- 待澄清问题 C1/C2/C3 未回填前，实现应以 spec.md「假设」节的默认立场（C1-A 现状+警告、C2-A 静默钳制、C3-B 现状）为准；回填后须重跑本清单。
