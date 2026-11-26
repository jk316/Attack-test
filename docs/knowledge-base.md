# 智能测试知识库 — 需求分析

> 目标：基于 Agent 过往历史实验记录，抽取有用内容构建知识库，用于指导后续 Agent 的思考（画像构建 / 向量生成 / 任务编排 / 迭代判定），并沉淀可复用的跨实验经验。
> 对应 `ARCHITECTURE.md` 的「智能测试知识库（历史经验查询 / 历史经验积累）」模块。
> 最后更新：2026-05
>
> ⚠️ **状态**：本文档仅为需求分析，功能**尚未实现**。其中「经验总结闭环」（实验日志 → LLM 自动总结经验教训 → 人工审核 → 加入经验库）标记为 **TODO**，后续按 **SDD**（Spec-Driven Development，spec 落 `docs/superpowers/specs/`）开发。

---

## 0. 背景与目标

知识库要解决的核心问题：**当前每次实验都从零开始**——LLM 只靠系统提示词 + 当次对话记忆探索参数，历史实验的「参数→效果」经验随实验结束即丢失（仅剩 `log_tool` 的稀疏 JSONL）。

知识库的三大目标：
1. **冷启动**：新实验用历史经验推荐初始参数，替代随机/默认值；
2. **加速收敛**：用历史有效向量/参数做 warm start，减少探索轮数；
3. **负经验复用**：沉淀"什么无效/不可信"，避免重复犯错。

---

## 1. 数据现状（当前能沉淀什么 / 缺什么）

### 已持久化（稀疏）
`src/tools/log_tool.py` 只写 JSONL 一行：
```json
{"iteration": 0, "params": {...}, "rtt": 1.0, "loss": 0.0, "timestamp": "..."}
```

### 富数据（当前**未持久化**，随对话丢失）
| 数据 | 来源 | 价值 |
|------|------|------|
| `rtt_during`（RTT 时间序列 + avg/min/max + loss_pct + total_sent/received） | `rtt_window.build_rtt_observation()` | 攻击窗口内的真实效果 |
| `attack_window` / `observation_window.covers_attack_window` + `note` | 同上 | **观测可信度**，负经验金矿 |
| `ping_monitor.get_stats()`（基线、backend、丢包） | `ping_monitor.py` | 对照基线，排除背景噪声 |
| 业务画像（`top_dst_ips/ports`、`packet_size_hist`、`iat_ms_stats`、`flow_stats`、`payload_len_stats`） | `pcap_profile_tool.py` | 目标特征，跨实验复用 |
| 攻击向量 / `traffic_spec_json` | `mixed_traffic_send` | 可复用的向量模板 |
| LLM 推理过程（`reasoning_content`） | `graph.py` monkey-patch | 策略洞察的原料 |

> 结论：**知识库的上限 = 实验记录的下限**。必须先补全记录（需求 0），再谈抽取。

---

## 2. 核心需求

### 需求 0：实验记录完整化（前提）

把每次实验结构化落盘为「实验 → 多轮迭代」：

```
ExperimentRun（实验）
├── experiment_id, target_ip, backend, mode, start_time, end_time, goal
├── business_profile（若提供 PCAP）
└── iterations[]
     └── Iteration（轮次）
          ├── iteration_index
          ├── params / traffic_spec（向量）
          ├── effect: { baseline_rtt, rtt_during{avg,min,max}, loss_pct, reward, delta_rtt }
          ├── observation: { covers_attack_window, note }
          ├── llm_reasoning（推理摘要）
          └── outcome: success / failure / invalid
```

**实施**：新增 `ExperimentRecorder`，在工具调用后（或 graph 节点内）把 `rtt_during` / `observation_window` / `ping_monitor` 基线一并写入；`log_tool` 升级为调用它（或保留 JSONL 作为旁路，结构化库为主）。

### 需求 1：知识抽取（从记录提炼知识单元）

5 类知识单元：

| 单元 | 定义 | 用途 |
|------|------|------|
| **EffectSample** | 一条「参数→效果」样本（含 delta_rtt / reward / 情境） | 经验回放、冷启动、预测 |
| **VectorTemplate** | 结构化可复用的攻击向量模板（协议栈 + 字段 + 百分比） | 定制化向量生成参考 |
| **TargetProfile** | 每目标聚合画像（协议敏感、基线 RTT、最有效向量类别） | 目标画像复用、跨实验 |
| **Insight** | LLM 蒸馏的文本结论（策略法则） | 语义检索、注入提示词 |
| **FailureRule** | 负面经验（窗口过短/目标不可达/丢包即信号） | 避免重复犯错 |

### 需求 2：知识存储（双轨）

- **结构化库**（SQLite/Postgres）：`ExperimentRun` / `Iteration` / `EffectSample` / `TargetProfile` / `VectorTemplate` 表，支持精确查询与聚合。
- **语义库**（向量：Chroma/FAISS/pgvector）：`Insight` / 实验结论摘要 embedding，支持语义相似检索。

### 需求 3：知识检索（对外接口）

```python
query_history(target_ip, profile, params) -> list[EffectSample]   # Top-K 相似样本
get_target_profile(target_ip) -> TargetProfile                    # 目标画像
recommend_initial_params(target_ip, profile) -> dict              # 冷启动参数
predict_effect(params, target_ip) -> {expected_delta_rtt, conf}   # 预期效果
retrieve_insights(query) -> list[Insight]                         # 语义检索经验法则
save_experience(run, iterations) -> None                          # 写回
```

### 需求 4：知识应用（指导 Agent 思考的 5 个落点）

对应理想架构各阶段：

1. **冷启动**（画像构建后 → 向量生成前）：`recommend_initial_params` 替代默认/随机参数；
2. **向量生成**：定制化向量参考历史 `VectorTemplate`；
3. **任务编排**：`predict_effect` 过滤无效任务 + 计算测试优先级；
4. **全局先验**：`retrieve_insights` 把「经验法则」注入系统提示词；
5. **迭代判定**：反馈优化阶段用历史判断「是否已逼近该目标 RTT 上限」。

### 需求 5：知识维护

- **去重**：相同/相似样本合并，保留最新 + 计数；
- **冲突检测**：同一参数在不同时间/情境下效果冲突时，标记情境而非覆盖；
- **新鲜度衰减**：网络环境会变，检索时按时间加权（近者优先）；
- **脱敏 + 鉴权**：目标 IP/端口敏感，入库脱敏、访问需鉴权。

---

## 3. 指导 Agent 的 5 个落点（详细）

| 落点 | 触发时机 | 输入 → 输出 | 价值 |
|------|---------|------------|------|
| 冷启动参数 | 画像构建完成后 | 画像 + 目标 → 初始参数 | 跳过无效探索 |
| 向量模板参考 | 攻击向量生成 | 画像 → Top-K 有效向量模板 | 复用历史成功向量 |
| 有效性预测 | 测试任务编排 | 向量 + 参数 → 预期效果 + 置信度 | 过滤低效、排序优先级 |
| 策略先验 | 实验启动 | 目标 → 经验法则文本 | 少走弯路 |
| 收敛判定 | 反馈优化 | 当前效果 vs 历史同目标分布 | 提前停止、避免过探索 |

---

## 4. 附加功能（可选，按价值排序）

1. **效果预测模型**：不止检索，拟合「参数→预期 RTT 变化」代理模型（本质是**贝叶斯优化先验**），直接推荐下一组参数 —— 知识库最高价值用法。
2. **知识图谱 + 跨目标迁移**：目标-协议-向量-效果 图结构，把目标 A 经验迁移到协议特征相似的目标 B。
3. **自动经验蒸馏**：定期用 LLM 把大量样本总结为「经验法则」，防知识爆炸。
4. **负面经验库**：专门沉淀 `observation_window.note` 的负经验（窗口过短 / 目标不可达 / 丢包即有效信号）。
5. **实验报告 / 趋势**：从知识库生成实验报告、参数-效果趋势分析。

---

## 5. 非功能需求

- **可追溯**：每条知识能回溯到 `experiment_id + iteration`（原始记录）；
- **增量更新**：实验结束即增量写入，无需重建；
- **可回放**：从记录可重放任意一次实验；
- **质量评估**：检索命中率、推荐参数的实际有效性（离线回测）。

---

## 6. 核心挑战与风险

1. **RTT 环境/时间相关**：知识有"有效期"，必须带情境 + 时间戳，按新鲜度加权。
2. **因果混淆**：RTT 升高可能是背景噪声 → 必须记录 `baseline_rtt` 做对照，`delta_rtt` 才是攻击净效应。
3. **参数空间稀疏**：不能精确匹配参数，要按「画像/协议类别」聚类泛化。
4. **探索/利用平衡**：知识给先验但不能锁死探索，否则 agent 只会复读历史最优、失去发现新有效区的能力。
5. **知识循环自证**：若 agent 只信知识库推荐，会陷入"只探索已知有效区"，需保留随机探索份额（如 ε-greedy）。

---

## 7. 分阶段落地建议

| 阶段 | 内容 | 交付物 |
|------|------|--------|
| **P0 记录完整化** | 需求 0：`ExperimentRecorder` + 结构化实验表，接住 `rtt_window`/`ping_monitor` 富数据 | 记录层 + SQLite 表 |
| **P1 冷启动 MVP** | 需求 1/3/4 的 EffectSample + `recommend_initial_params`（最简单的最高价值） | 冷启动推荐接口 |
| **P2 语义检索** | 需求 2 向量库 + Insight 抽取 + `retrieve_insights` | 向量库 + 语义检索 |
| **P3 预测 + 图谱** | 附加功能 1/2：效果预测模型 + 跨目标迁移 | 代理模型 + 知识图谱 |
| **P4 维护 + 可视化** | 需求 5 + 附加功能 5：去重/冲突/新鲜度 + 报告/看板 | 维护策略 + Web 看板 |
