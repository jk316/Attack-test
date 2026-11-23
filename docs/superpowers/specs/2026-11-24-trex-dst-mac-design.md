# TRex 目的 MAC 支持设计（短设计）

**意图**：Agent 在 TRex live 会话中反复困在「目的 MAC 该填什么」上（agent.log 中 4 场会话大量轮次浪费于 ARP 解析失败 / "Port 0 dest MAC is invalid" 诊断）。给 TRex 侧补上与 Pktgen 侧等价的已知 L2 事实注入 + 公共 helper 模块。

**目标**：
1. 配置层提供 TRex 端口 0 的 src MAC、网关 dst MAC、start(force) 开关（env → topology.yaml → 默认值）。
2. 两个提示词模板注入「已知 L2 拓扑与目的 MAC」一节，脚本模板改引 `trex_common`。
3. `trex_scripts/trex_common.py` 公共模块：`DST_MAC` / `SRC_MAC` / `START_FORCE` 常量、`start_safe()`（force=True）、`make_client()`（trex 库延迟 import，纯 stdlib 可被任意 Python 导入）。

**非目标**：不改 TRex 端口实际网络配置；不做运行时 ARP 自动解析；不做 dst-MAC 静态扫描 lint（留作后续）。

**反目标**：不得把非 allowlist 的网关 IP 字面量写进提示词示例脚本（会被静态扫描拦截、误导 agent 复制进脚本）。

**方法**：沿用现有模式 —— `experiment.json`（trex 段）→ `main.py` 注入 env → `src/trex/config.py` getter（env → topology.yaml trex 段 → 默认值）→ `graph.py` 渲染进模板。helper 提交到 `trex_scripts/trex_common.py`（.gitignore 加例外），`write_python_file` 保留该文件名不可覆盖。

**关键值（默认，均可在配置覆盖）**：
- dst_mac（网关 MAC）：`f4:e9:75:ee:51:69`（2026-11-23 agent.log 实测，目标 100.1.11.3 位于该网关后）
- src_mac（TRex 端口 0）：`58:a2:e1:6d:89:2c`
- start_force：`true`
