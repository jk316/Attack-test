# 攻防智能体控制台 — 后端核心 Implementation Plan（Plan 1 / 3）

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有单实验 Web 后端升级为「实验为中心」的后端：SQLite 持久化（events 权威流水 + attacks/probes 派生表）、创建/排队/停止/软删除 REST、WS 实时事件与 HITL、断线续读、工具子集与每实验软上限。

**Architecture:** 三层：`backend/storage.py`（SQLite，每操作独立连接）→ `backend/derive.py`（纯函数：攻击抽取/摘要/大小估算）→ `backend/experiment.py`（ExperimentManager：每实验一个 asyncio 任务，同步图用 `asyncio.to_thread(graph.invoke)` 跑，事件落库后广播给订阅者）。`backend/server.py` 通过 `create_app(storage, manager)` 工厂注入依赖。工具软上限经 `src/config/run.py` 写 env（单实验并发模型下 env 安全），工具在调用时读 `*_LIMIT` 环境变量钳制。

**Tech Stack:** Python ≥3.11 · FastAPI + WebSocket · sqlite3（stdlib）· pydantic · pytest（pytest-asyncio、TestClient/httpx）· uv

**Spec:** [spec.md](../../../spec.md)（v0.2，唯一事实源；执行者实现每个任务时对照该文档相应小节）

## 计划拆分说明

spec 覆盖三个可独立交付的部分：本计划（后端核心：spec §6–§8、§12）、Plan 2（前端三视图 + ECharts，spec §9）、Plan 3（收尾：Pktgen 统计结构化输出/CLI 重构/加固，spec §7.6、§13 剩余项）。本计划完成后，可用 REST + WS 客户端完整跑通"创建→排队→运行→落库→查询→停止/软删除→重启清理"。

## Global Constraints

- Python ≥3.11，uv 管理。本机沙箱下安装/运行一律：`UV_CACHE_DIR="$PWD/.uv-cache" uv sync --extra dev`；跑测试用 `.venv/bin/python -m pytest`（不直接用 `uv run pytest`）。
- 实验状态枚举：`queued|running|completed|stopped|error|interrupted`；删除=软删除（置 `deleted_at`），`queued/running` 拒绝删除（409）。
- 硬上限常量不可下放：`MAX_PPS=20000`、`MAX_DURATION_S=20`、`MAX_PACKET_SIZE=1024`、`MAX_FLOW_COUNT=100`、`MAX_IAT_JITTER_MS=20`、pktgen `rate≤100`、`duration_ms≤60000`。软上限 = `min(表单值, 硬上限)`。
- `events` 是唯一权威流水，`seq` 实验内自增且与 WS 消息同源同值；`attacks`/`probes` 是派生物化表（`attacks.seq` = 派生它的 `tool_result` 事件 seq）。
- PCAP ≤ 50 MB（`50 * 1024 * 1024` 字节）；按实验归档 `data/uploads/{run_id}/`（归档动作属 Plan 1：创建时拷贝）。
- 单实验并发 + FIFO 队列；无鉴权；单台 WS 连接中第一个为操作员，其余旁观。
- 用户可见文案（`attack_label`、错误消息）用中文；代码注释风格与仓库一致（中文 docstring）。
- 禁止修改 vendored `pktgen_agent/`、`dsl/` 目录（本计划内不碰）。

## Review Focus

1. `reasoning_content` 为空/缺失时，折叠摘要必须回退到 `content` 前 80 字 —— T4 测试 `test_summarize_reasoning_fallback`。
2. 软删除的实验不得出现在 `list_experiments`/`get_experiment`/`next_queued` 任何结果里 —— T2 测试 `test_soft_deleted_hidden_everywhere`。
3. 重启清理只把 `queued/running` → `interrupted`，`completed/stopped/error` 与已软删除行不动 —— T2 测试 `test_mark_stale_only_active`。
4. 未设置 `*_LIMIT` 环境变量时，三个流量工具的钳制行为与改造前完全一致（仍钳到硬上限）—— T7/T8 现有单测不回归 + 显式断言。
5. HITL 断线恢复：`latest_event(run_id, "hitl")` 能取到 `approved is None` 的最新审批请求；重连订阅后该请求被重新推送 —— T3 测试 `test_latest_pending_hitl` + T10 测试 `test_reconnect_gets_pending_hitl`。

---

### Task 1: 测试基座修复（pytest-asyncio / httpx / gitignore）

**Files:**
- Modify: `pyproject.toml`（`[project.optional-dependencies] dev` 块）
- Modify: `.gitignore`

**Interfaces:**
- Produces: 可用的测试运行方式（下同所有任务）：`UV_CACHE_DIR="$PWD/.uv-cache" uv sync --extra dev` → `.venv/bin/python -m pytest <path> -v`；`@pytest.mark.asyncio` 测试真正被执行。

- [ ] **Step 1: 添加 dev 依赖**

`pyproject.toml` 的 dev 数组改为：`["pytest>=8.0", "pytest-cov>=4.0", "pytest-asyncio>=0.24", "httpx>=0.27"]`（pytest-asyncio 是修复现有 `@pytest.mark.asyncio` 测试的必要依赖；httpx 是 FastAPI TestClient 的运行时依赖，显式声明不依赖传递安装）。

- [ ] **Step 2: `.gitignore` 追加沙箱缓存与运行时数据**

追加三行：`.uv-cache/`、`data/attack_test.db`、`data/uploads/`。

- [ ] **Step 3: 同步并验证现有 async 测试恢复通过**

Run: `UV_CACHE_DIR="$PWD/.uv-cache" uv sync --extra dev && .venv/bin/python -m pytest tests/integration/test_web_experiment.py -q`
Expected: `5 passed`，无 `PytestUnknownMarkWarning`（该文件目前 2 failed + 未知 mark 警告；装好插件后应全绿——若仍有失败，说明既有测试与当前代码漂移，记录后进入 T10 一并重写）。

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml .gitignore uv.lock
git commit -m "chore: add pytest-asyncio and httpx dev deps, fix async test baseline"
```

---

### Task 2: `backend/storage.py` — 建表、迁移、experiments CRUD、软删除、孤儿清理

**Files:**
- Create: `backend/storage.py`
- Test: `tests/unit/test_storage.py`

**Interfaces:**
- Produces（T3–T12 依赖）:

```python
class Storage:
    def __init__(self, db_path: Path | str): ...        # 初始化时建表，PRAGMA user_version=1
    def create_experiment(self, config: dict, status: str = "queued") -> str
        # run_id 形如 "r_20261118_213000_ab12"（时间戳_8位hex）；config JSON 快照；created_at ISO8601 UTC
    def get_experiment(self, run_id: str) -> dict | None   # config/summary 反序列化回 dict
    def list_experiments(self, status: str | None = None, cursor: str | None = None, limit: int = 20) -> dict
        # -> {"items": [...], "total": int, "next_cursor": str|None}；过滤 deleted_at IS NOT NULL；
        # cursor = "{created_at},{id}"，按 created_at DESC, id DESC 分页
    def update_experiment(self, run_id: str, **fields) -> None
        # fields 白名单: status, stop_reason, started_at, finished_at, summary, deleted_at
    def soft_delete(self, run_id: str) -> None
        # 不存在 → ValueError("experiment not found")；status in (queued, running) → ValueError("cannot delete running/queued experiment")；
        # 否则置 deleted_at=now
    def mark_stale_as_interrupted(self) -> int    # status IN (queued,running) 且未软删除 → interrupted + finished_at=now；返回更新行数
    def next_queued(self) -> str | None           # 未软删除的 queued 中 created_at 最早者
```

- [ ] **Step 1: 写失败测试** `tests/unit/test_storage.py`（`tmp_path` 建库）：

```python
def test_create_and_get_experiment(tmp_path):
    s = Storage(tmp_path / "t.db")
    rid = s.create_experiment({"target_ip": "10.99.80.160"}, status="queued")
    row = s.get_experiment(rid)
    assert row["status"] == "queued" and row["config"]["target_ip"] == "10.99.80.160"

def test_soft_deleted_hidden_everywhere(tmp_path):
    s = Storage(tmp_path / "t.db")
    a = s.create_experiment({}, status="completed")
    s.soft_delete(a)
    assert s.get_experiment(a) is None
    assert s.list_experiments()["items"] == [] and s.next_queued() is None

def test_soft_delete_rejects_active(tmp_path):
    s = Storage(tmp_path / "t.db")
    for st in ("queued", "running"):
        rid = s.create_experiment({}, status=st)
        with pytest.raises(ValueError):
            s.soft_delete(rid)

def test_mark_stale_only_active(tmp_path):
    s = Storage(tmp_path / "t.db")
    q = s.create_experiment({}, status="queued"); r = s.create_experiment({}, status="running")
    c = s.create_experiment({}, status="completed")
    n = s.mark_stale_as_interrupted()
    assert n == 2
    assert s.get_experiment(q)["status"] == "interrupted"
    assert s.get_experiment(r)["status"] == "interrupted"
    assert s.get_experiment(c)["status"] == "completed"

def test_next_queued_fifo(tmp_path):
    s = Storage(tmp_path / "t.db")
    a = s.create_experiment({}, status="queued"); b = s.create_experiment({}, status="queued")
    assert s.next_queued() == a
```

表结构照抄 spec §7.2（`experiments` 表含 `deleted_at`；本任务只建 `experiments` 表，其余表 T3 建——建表函数需幂等，T3 会扩充同一 schema 版本，迁移逻辑用 `PRAGMA user_version` 分支）。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/unit/test_storage.py -v`
Expected: FAIL（`ModuleNotFoundError: backend.storage` / 类不存在）

- [ ] **Step 3: 实现 `Storage` 于 `backend/storage.py`**

每方法 `with sqlite3.connect(str(self._path)) as conn`（`row_factory=sqlite3.Row`）独立连接；建表 + `PRAGMA user_version=1` 在 `__init__` 执行。`update_experiment` 对未知字段名抛 `ValueError`。时间戳统一 `datetime.now(timezone.utc).isoformat()`。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/unit/test_storage.py -v` Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/storage.py tests/unit/test_storage.py
git commit -m "feat: add SQLite storage layer with experiments CRUD, soft delete, stale cleanup"
```

---

### Task 3: 事件流水与派生表读写

**Files:**
- Modify: `backend/storage.py`（追加方法与表）
- Test: `tests/unit/test_storage.py`（追加用例）

**Interfaces:**
- Produces（T4/T10–T12 依赖）:

```python
    def append_event(self, experiment_id: str, kind: str, payload: dict) -> int
        # kind ∈ {reasoning, ai_message, tool_call, tool_result, hitl, status, error}；
        # seq = 该实验 max(seq)+1（无则 1）；INSERT 后返回 seq；唯一索引冲突抛 sqlite3.IntegrityError
    def list_events(self, experiment_id: str, after_seq: int = 0, limit: int = 500) -> list[dict]
        # seq > after_seq，升序，payload 反序列化
    def latest_event(self, experiment_id: str, kind: str) -> dict | None
    def append_attack(self, experiment_id: str, seq: int, ts: str, attack_type: str,
                      attack_label: str, params: dict, size: dict, rtt: dict | None,
                      hitl: dict | None) -> None
    def append_probe(self, experiment_id: str, seq: int, ts: float, sent: int,
                     received: int, avg_rtt_ms: float | None, loss_pct: float) -> None
    def list_attacks(self, experiment_id: str) -> list[dict]   # seq 升序
    def list_probes(self, experiment_id: str) -> list[dict]    # ts 升序
```

- [ ] **Step 1: 写失败测试**（追加到 `tests/unit/test_storage.py`）：

```python
def test_seq_increments_per_experiment(tmp_path):
    s = Storage(tmp_path / "t.db")
    rid = s.create_experiment({})
    assert s.append_event(rid, "status", {"status": "running"}) == 1
    assert s.append_event(rid, "tool_call", {"name": "ping_rtt", "args": {}}) == 2
    rid2 = s.create_experiment({})
    assert s.append_event(rid2, "status", {"status": "running"}) == 1

def test_events_after_seq(tmp_path):
    s = Storage(tmp_path / "t.db")
    rid = s.create_experiment({})
    for i in range(5):
        s.append_event(rid, "status", {"n": i})
    got = s.list_events(rid, after_seq=2)
    assert [e["seq"] for e in got] == [3, 4, 5]

def test_latest_pending_hitl(tmp_path):
    s = Storage(tmp_path / "t.db")
    rid = s.create_experiment({})
    s.append_event(rid, "hitl", {"message": "approve?", "params": {}, "approved": None})
    s.append_event(rid, "hitl", {"message": "approve?", "params": {}, "approved": True})
    latest = s.latest_event(rid, "hitl")
    assert latest["payload"]["approved"] is True

def test_attacks_and_probes_roundtrip(tmp_path):
    s = Storage(tmp_path / "t.db")
    rid = s.create_experiment({})
    s.append_attack(rid, 3, "2026-11-18T21:00:00+00:00", "scapy_udp", "Scapy UDP 流量",
                    {"pps": 100}, {"engine": "scapy"}, None, {"requested": True, "approved": None})
    s.append_probe(rid, 1, 1730000000.0, 10, 9, 5.0, 10.0)
    assert len(s.list_attacks(rid)) == 1 and len(s.list_probes(rid)) == 1
```

表结构照抄 spec §7.2（`events`、`attacks`、`probes` + 索引）；`events`/`attacks` 建 `UNIQUE(experiment_id, seq)`。

- [ ] **Step 2: 运行确认失败**（AttributeError/表不存在）

- [ ] **Step 3: 实现上述方法**（同一 `Storage` 类内；payload JSON 序列化入 `payload` 列）

- [ ] **Step 4: 运行确认通过**（含 Task 2 的全部用例）

- [ ] **Step 5: Commit**

```bash
git add backend/storage.py tests/unit/test_storage.py
git commit -m "feat: add events/attacks/probes append and query APIs with per-experiment seq"
```

---

### Task 4: `backend/derive.py` — 攻击抽取、摘要、大小估算、结果摘要

**Files:**
- Create: `backend/derive.py`
- Test: `tests/unit/test_derive.py`

**Interfaces:**
- Consumes: `Storage`（`compute_summary` 参数）
- Produces（T10/T12 依赖）:

```python
ATTACK_TOOL_MAP: dict[str, tuple[str, str]]   # 工具名 -> (attack_type, attack_label)，19 个工具全表按 spec §8.8
def is_attack_tool(name: str) -> bool
def summarize_reasoning(reasoning_content: str | None, content: str) -> str
    # 规则：取 reasoning_content（缺省回退 content）；去换行/多余空白；前 80 个 Unicode 字符 + "…"（不足 80 不加）
def build_size_estimate(tool_name: str, params: dict, result: dict) -> dict
    # 按 spec §7.5：scapy→engine/rate(pps)/duration_s/packet_size/flow_count/est_total_packets/est_mbps；
    # pktgen→rate% + duration_ms→s 换算 + packet_size + measured=None（本计划阶段无结构化统计，Plan 3 接入）；
    # trex→{engine, script, elapsed_s}
def extract_attack(tool_name: str, params: dict, result: dict) -> dict | None
    # 非攻击工具→None；否则 {"attack_type","attack_label","params","size","rtt","hitl":{"requested":True,"approved":None}}
    # rtt = result 中含 rtt_during/attack_window/observation_window 的键则透传，否则 None
def compute_summary(storage: Storage, experiment_id: str) -> dict
    # spec §7.4 全字段：best_rtt_ms/final_rtt_ms 取 attacks.rtt.rtt_during.avg_rtt_ms 最大/最后；
    # probe_success_rate = Σreceived/Σsent×100（无探针 None）；attack_count；steps = events 中 kind∈(reasoning,ai_message,tool_call) 计数；
    # stop_reason 由调用方传入并入 dict（函数签名含 stop_reason: str 参数）
```

- [ ] **Step 1: 写失败测试**：

```python
def test_summarize_reasoning_fallback():
    assert summarize_reasoning(None, "x" * 200) == "x" * 80 + "…"
    assert summarize_reasoning("  你好\n世界 ", "") == "你好世界"      # 去空白且不足 80 不加省略号

def test_is_attack_tool_matrix():
    assert is_attack_tool("traffic_send") and is_attack_tool("pktgen_udp_flood")
    assert not is_attack_tool("ping_rtt") and not is_attack_tool("write_python_file")

def test_extract_attack_scapy_size():
    params = {"dst_ip": "10.99.80.160", "dst_port": 53, "pps": 100, "duration_s": 10, "packet_size": 64, "flow_count": 1}
    result = {"success": True, "effective_pps": 99.0, "rtt_during": {"avg_rtt_ms": 5.0}}
    a = extract_attack("traffic_send", params, result)
    assert a["attack_type"] == "scapy_udp" and a["attack_label"] == "Scapy UDP 流量"
    assert a["size"]["est_total_packets"] == 1000 and a["size"]["est_mbps"] == round(100*64*8/1e6, 2)
    assert a["rtt"]["rtt_during"]["avg_rtt_ms"] == 5.0

def test_extract_attack_non_tool_returns_none():
    assert extract_attack("pcap_profile", {}, {"top_dst_ips": []}) is None

def test_compute_summary(tmp_path):
    s = Storage(tmp_path / "t.db"); rid = s.create_experiment({})
    s.append_attack(rid, 1, "t", "scapy_udp", "Scapy UDP 流量", {}, {}, {"rtt_during": {"avg_rtt_ms": 5.0}}, None)
    s.append_attack(rid, 2, "t", "scapy_udp", "Scapy UDP 流量", {}, {}, {"rtt_during": {"avg_rtt_ms": 9.0}}, None)
    s.append_probe(rid, 1, 1.0, 10, 9, 5.0, 10.0)
    s.append_event(rid, "tool_call", {"name": "x", "args": {}})
    s.append_event(rid, "reasoning", {"content": "c"})
    summary = compute_summary(s, rid, stop_reason="completed")
    assert summary["best_rtt_ms"] == 9.0 and summary["final_rtt_ms"] == 9.0
    assert summary["probe_success_rate"] == 90.0 and summary["attack_count"] == 2 and summary["steps"] == 2
```

- [ ] **Step 2: 运行确认失败** → **Step 3: 实现**（`est_mbps` 保留 2 位小数 `round(...,2)`；`ATTACK_TOOL_MAP` 值严格按 spec §8.8 中文标签）→ **Step 4: 运行确认通过** → **Step 5: Commit**（`feat: add derive helpers for attack extraction, size estimation and summary`）

---

### Task 5: `backend/schemas.py` — 创建请求校验与表单元数据

**Files:**
- Create: `backend/schemas.py`
- Test: `tests/unit/test_schemas.py`

**Interfaces:**
- Produces（T10/T12 依赖）:

```python
MAX_PCAP_BYTES = 50 * 1024 * 1024
TOOL_CATALOG: dict[str, dict]      # 名 -> {"category": "scapy"|"pktgen"|"trex", "observation": bool}
    # 19 个工具全表；observation=True 仅: start_ping_monitor, read_ping_stats, stop_ping_monitor, ping_rtt
HARD_LIMITS: dict[str, float]      # pps/duration_s/packet_size/flow_count/iat_jitter_ms/pktgen_rate/pktgen_duration_ms → 硬上限常量
class CreateExperimentRequest(BaseModel):   # 字段与默认值照 spec §8.1.1 逐字
    target_ip: str; user_prompt: str = ""; tool_limits: dict = {}; enabled_tools: list[str] | None = None
    pcap_path: str = ""; max_iters: int = 20; no_improve_limit: int = 5; mode: str = "dry_run"
class CreateValidationError(ValueError):
    def __init__(self, field: str, message: str): ...
def validate_create(req: CreateExperimentRequest) -> dict
    # 校验顺序照 spec §8.1.1：target_ip∈allowlist(复用 src.tools.ping_rtt_tool.validate_target) →
    # enabled_tools 全在 TOOL_CATALOG 且至少含 1 个 observation 工具 →
    # tool_limits 每项 ≤ HARD_LIMITS（超限报 {param, given, hard_limit}）→
    # mode ∈ {dry_run, pktgen_live, trex_live} → DEEPSEEK_API_KEY/OPENAI_API_KEY 存在 → pcap 存在且 ≤50MB
    # 返回规范化 config dict：enabled_tools=None→全部 19 个；tool_limits 补默认软上限（读 src/config/experiment.json）
def get_meta_options() -> dict
    # {"allowlist": [...hosts], "tools": [{"name","category","observation","hard_limits"}...],
    #  "modes": [...], "hard_limits": HARD_LIMITS, "max_pcap_bytes": MAX_PCAP_BYTES}
```

- [ ] **Step 1: 写失败测试**（`monkeypatch` 控制 env 与 pcap 文件；target 用 `10.99.80.160`，非法用 `192.168.1.99`）：

```python
def test_validate_ok(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    req = CreateExperimentRequest(target_ip="10.99.80.160")
    cfg = validate_create(req)
    assert len(cfg["enabled_tools"]) == 19

def test_bad_ip_rejected(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with pytest.raises(CreateValidationError) as e:
        validate_create(CreateExperimentRequest(target_ip="192.168.1.99"))
    assert e.value.field == "target_ip"

def test_limit_above_hard_rejected(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with pytest.raises(CreateValidationError) as e:
        validate_create(CreateExperimentRequest(target_ip="10.99.80.160", tool_limits={"pps": 999999}))
    assert e.value.message 包含 "hard_limit"

def test_no_observation_tool_rejected(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    req = CreateExperimentRequest(target_ip="10.99.80.160",
        enabled_tools=["traffic_send", "pktgen_udp_flood", "write_python_file"])
    with pytest.raises(CreateValidationError):
        validate_create(req)

def test_pcap_too_large_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    p = tmp_path / "big.pcap"; p.write_bytes(b"0" * (MAX_PCAP_BYTES + 1))
    req = CreateExperimentRequest(target_ip="10.99.80.160", pcap_path=str(p))
    with pytest.raises(CreateValidationError) as e:
        validate_create(req)
    assert e.value.field == "pcap_path"
```

- [ ] **Step 2–5:** 标准 TDD 循环后 Commit（`feat: add experiment creation validation and meta options`）。

---

### Task 6: `src/config/run.py` — RunConfig 与 env 注入

**Files:**
- Create: `src/config/run.py`
- Test: `tests/unit/test_run_config.py`

**Interfaces:**
- Produces（T7/T8/T9/T10 依赖）:

```python
@dataclass
class ToolLimits:
    pps: int = 20000; duration_s: int = 20; packet_size: int = 1024
    flow_count: int = 100; iat_jitter_ms: int = 20
    pktgen_rate: float = 100.0; pktgen_duration_ms: int = 60000
    @classmethod
    def from_dict(cls, d: dict) -> "ToolLimits":
        # 缺省层：src/config/experiment.json 的 attack/pktgen 默认值；覆盖层：d；最终每项 min(值, 硬上限常量)
@dataclass
class RunConfig:
    target_ip: str; user_prompt: str = ""; tool_limits: ToolLimits = field(default_factory=ToolLimits)
    enabled_tools: list[str] = field(default_factory=list)   # 空 = 全部
    pcap_path: str = ""; max_iters: int = 20; no_improve_limit: int = 5; mode: str = "dry_run"
def apply_run_config(cfg: RunConfig) -> None
    # 设 env：ATK_DURATION_S/ATK_PPS/ATK_PACKET_SIZE/ATK_FLOW_COUNT/ATK_IAT_JITTER_MS/PKTGEN_RATE/PKTGEN_DURATION_MS（默认值）
    # 软上限：ATK_PPS_LIMIT/ATK_DURATION_S_LIMIT/ATK_PACKET_SIZE_LIMIT/ATK_FLOW_COUNT_LIMIT/
    #          ATK_IAT_JITTER_MS_LIMIT/PKTGEN_RATE_LIMIT/PKTGEN_DURATION_MS_LIMIT
    # 模式：mode=="pktgen_live"→PKTGEN_DRY_RUN=false；"trex_live"→TREX_DRY_RUN=false；INSTRUCTION=user_prompt；TARGET_IP=target_ip
def clear_run_config() -> None   # 删除上面全部键
```

- [ ] **Step 1: 写失败测试**（`monkeypatch.delenv` 全量清空后断言）：

```python
def test_apply_then_clear(monkeypatch):
    cfg = RunConfig(target_ip="10.99.80.160", tool_limits=ToolLimits.from_dict({"pps": 500}),
                    user_prompt="测UDP", mode="pktgen_live")
    apply_run_config(cfg)
    assert os.environ["ATK_PPS_LIMIT"] == "500" and os.environ["INSTRUCTION"] == "测UDP"
    assert os.environ["PKTGEN_DRY_RUN"] == "false"
    clear_run_config()
    assert "ATK_PPS_LIMIT" not in os.environ

def test_from_dict_clamps_to_hard(monkeypatch):
    tl = ToolLimits.from_dict({"pps": 999999, "pktgen_rate": 250})
    assert tl.pps == 20000 and tl.pktgen_rate == 100.0
```

- [ ] **Step 2–5:** 标准 TDD 循环后 Commit（`feat: add RunConfig and per-experiment env injection`）。

---

### Task 7: 软上限钳制 — `traffic_send_tool` + `mixed_traffic_tool`

**Files:**
- Modify: `src/tools/traffic_send_tool.py`（`validate_params`）
- Modify: `src/tools/mixed_traffic_tool.py`（pps/duration clamp 段）
- Test: `tests/unit/test_traffic_send_tool.py`、`tests/unit/test_mixed_traffic_tool.py`（追加用例）

**Interfaces:**
- Consumes: env 键 `ATK_PPS_LIMIT`/`ATK_DURATION_S_LIMIT`/`ATK_PACKET_SIZE_LIMIT`/`ATK_FLOW_COUNT_LIMIT`/`ATK_IAT_JITTER_MS_LIMIT`（T6 设置）
- Produces: `traffic_send_tool._soft_limit(env_name: str, hard: int) -> int`（env 缺省/非法返回 hard）

- [ ] **Step 1: 写失败测试**（追加到现有两个测试文件；沿用其 mock 风格）：

```python
# tests/unit/test_traffic_send_tool.py
def test_soft_limit_clamps_below_hard(monkeypatch):
    monkeypatch.setenv("ATK_PPS_LIMIT", "500")
    dur, pps, size, flows, jitter = validate_params(
        "10.99.80.160", 53, 10, 2000, 64, 1, 0, None)
    assert pps == 500 and dur == 10        # 只有 pps 被下修，其余不变
# tests/unit/test_mixed_traffic_tool.py
def test_soft_limit_pps_and_duration(monkeypatch):
    monkeypatch.setenv("ATK_PPS_LIMIT", "300"); monkeypatch.setenv("ATK_DURATION_S_LIMIT", "8")
    # 断言 mixed_traffic_send_tool 结果 params 中 pps==300 且 duration_s==8（沿用该文件现有 mock 发送方式）
```

- [ ] **Step 2: 先跑全量既有用例确认不回归**

Run: `.venv/bin/python -m pytest tests/unit/test_traffic_send_tool.py tests/unit/test_mixed_traffic_tool.py -q`
Expected: 既有用例全部 PASS（无 LIMIT env 时行为不变——Review Focus #4），仅新用例 FAIL。

- [ ] **Step 3: 实现**：`validate_params` 中每个 `min(x, MAX_*)` 改为 `min(x, _soft_limit("ATK_*_LIMIT", MAX_*))`；mixed 的 pps/duration 两处同法（从 traffic_send_tool 导入 `_soft_limit`）。

- [ ] **Step 4: 运行确认全绿** → **Step 5: Commit**（`feat: enforce per-experiment soft limits in scapy traffic tools`）

---

### Task 8: 软上限钳制 — Pktgen adapter

**Files:**
- Modify: `src/pktgen/adapter.py`（`_run_traffic_tool` 内 clean_params 阶段）
- Test: `tests/unit/test_pktgen_adapter.py`（追加用例）

**Interfaces:**
- Consumes: env 键 `PKTGEN_RATE_LIMIT`/`PKTGEN_DURATION_MS_LIMIT`（T6 设置）
- Produces: `adapter._soft_limit(env_name: str, hard: float) -> float`

- [ ] **Step 1: 写失败测试**（沿用该文件现有 mock `_import_pktgen` 的模式）：

```python
def test_rate_and_duration_clamped_by_soft_limit(monkeypatch):
    monkeypatch.setenv("PKTGEN_RATE_LIMIT", "40"); monkeypatch.setenv("PKTGEN_DURATION_MS_LIMIT", "3000")
    monkeypatch.setenv("PKTGEN_DRY_RUN", "true")
    # mock execute_skill_dry_run 捕获 params
    # 调用 pktgen_udp_flood(dst_ip="10.99.80.160", rate=90, duration=9000)
    # 断言 dry-run 收到的 params["rate"] == 40 且 params["duration"] == 3000
```

- [ ] **Step 2: 既有用例回归确认**（无 env 时应全 PASS）→ **Step 3: 实现**（在 `_run_traffic_tool` 组装 `params` 后、执行前 clamp `rate`/`duration`；仅当键存在时）→ **Step 4: 全绿** → **Step 5: Commit**（`feat: enforce per-experiment soft limits in pktgen adapter`）

---

### Task 9: `build_graph` 工具子集与提示词软上限

**Files:**
- Modify: `src/agent/graph.py`
- Test: `tests/unit/test_graph_tool_filter.py`（新建，模式参考 `tests/unit/test_trex_catalog_mode.py` 的 mock 手法）

**Interfaces:**
- Consumes: `ToolLimits`（T6）
- Produces（T10 依赖）:

```python
def build_graph(max_iters: int = 20, no_improve_limit: int = 5, mode: str = "experiment",
                tools: list[str] | None = None, tool_limits: dict | None = None) -> CompiledStateGraph
    # mode=="experiment" 且 tools 非 None：按名字过滤 EXPERIMENT_TOOLS（未知名 → ValueError）；
    # 过滤后仍至少含 1 个观测工具（否则 ValueError）；mode=="catalog" 忽略 tools/tool_limits（行为不变）
    # tool_limits 非 None：_build_system_prompt 用 ToolLimits.from_dict(tool_limits) 的生效值渲染 max_pps 等模板变量
```

- [ ] **Step 1: 写失败测试**：

```python
def test_tools_subset_filters_graph(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    # 沿用 test_trex_catalog_mode.py 里断言已注册工具集合的方式：
    # build_graph(tools=["traffic_send", "ping_rtt", "start_ping_monitor", "read_ping_stats"])
    # 断言 graph 的 tools 节点仅含这 4 个名字
def test_unknown_tool_name_raises(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with pytest.raises(ValueError):
        build_graph(tools=["not_a_tool"])
def test_no_observation_tool_raises(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with pytest.raises(ValueError):
        build_graph(tools=["traffic_send"])
```

- [ ] **Step 2–5:** 标准 TDD 循环后 Commit（`feat: support tool subset and per-experiment soft limits in build_graph`）

---

### Task 10: `ExperimentManager` v2 — 每实验任务、事件落库、HITL、停止、摘要、订阅

**Files:**
- Rewrite: `backend/experiment.py`
- Rewrite: `tests/integration/test_web_experiment.py`（对齐 v2 公共 API）
- Test: `tests/integration/test_experiment_manager.py`（新建）

**Interfaces:**
- Consumes: `Storage`(T2/T3)、`derive`(T4)、`schemas`(T5)、`RunConfig`(T6)、`build_graph`(T9)
- Produces（T11/T12 依赖）:

```python
class ExperimentManager:
    def __init__(self, graph_factory=build_graph, storage: Storage | None = None,
                 probe_interval_s: float = 1.0): ...
        # storage 缺省 Storage(Path(os.environ.get("ATTACK_TEST_DB", "data/attack_test.db"))); 构造时不再建图
    async def create(self, config: dict) -> dict                     # -> {"run_id","status"}
        # validate_create → storage.create_experiment → 若无运行中实验立即 asyncio.create_task(self._run(rid)) 返回 running，
        # 否则保持 queued
    async def join(self, run_id: str, timeout: float | None = None) -> dict
        # 等待该实验任务结束（asyncio.wait_for），返回 storage.get_experiment(run_id)；超时抛 asyncio.TimeoutError
    async def stop(self, run_id: str) -> None        # 置停止标志；若在等 HITL 则向队列放 False；幂等
    async def approve(self, run_id: str, approved: bool) -> None
    def subscribe(self, run_id: str, ws) -> str      # 第一个订阅者返回 "operator"，其后 "observer"
    def unsubscribe(self, run_id: str, ws) -> None
    async def pending_hitl(self, run_id: str) -> dict | None   # storage.latest_event(run_id,"hitl") 且 payload["approved"] is None
    @property
    def running_run_id(self) -> str | None
```

内部行为（锁死，实现不得偏离）：
- `_run(run_id)`：置 running/started_at → `apply_run_config(RunConfig(**config 字段))` → `graph = self._graph_factory(max_iters=..., no_improve_limit=..., mode=..., tools=config["enabled_tools"], tool_limits=config["tool_limits"])` → 循环：`await asyncio.to_thread(graph.invoke, state_or_command, graph_config)` → `graph.get_state(config)` 差量取新消息 → 逐条转事件（AI 消息：有 `reasoning_content`→kind `reasoning`（含 content/reasoning_content/summary），否则 kind `ai_message`；`tool_calls` 逐条→kind `tool_call`；ToolMessage→kind `tool_result`，若 `is_attack_tool(name)` 同时 `derive.extract_attack` → `storage.append_attack`（seq=该 tool_result 事件 seq，hitl.approved 取 `self._pending_approval.pop(run_id, None)`））→ 每条 `storage.append_event` 后用返回 seq 组装 WS 消息并 `await self._broadcast(run_id, msg)` → 若 `gs.next` 非空：`pending = self._extract_hitl(gs)` → append `hitl` 事件（approved=None）+ broadcast `hitl_request` → `approved = await queue.get()` → append `hitl` 事件（approved）+ 记录 `_pending_approval[run_id]=approved` + broadcast `hitl_response` → `to_thread(graph.invoke, Command(resume=approved), config)` 继续；循环退出条件：`gs.next` 为空 或 stop 标志。
- 收尾：status=stopped(手动)/error(异常，`summary.error` 截 500 字)/completed；`summary = derive.compute_summary(storage, rid, stop_reason)` → `update_experiment` → broadcast `experiment_done` → `clear_run_config()` → 触发队列启动（T11）。
- 广播对象为 `self._subscribers[run_id]` 集合，发送失败（断线）的 ws 直接 `unsubscribe`。

- [ ] **Step 1: 写失败测试** `tests/integration/test_experiment_manager.py`（fake graph factory 用 MagicMock，get_state side_effect 仿 `test_web_experiment.py` 旧写法）：

```python
def _fake_factory(done_states, release=None, **kwargs):
    """返回 MagicMock graph：invoke 同步返回 None；get_state 依序返回状态。"""
@pytest.mark.asyncio
async def test_run_persists_events_and_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    storage = Storage(tmp_path / "t.db")
    done = _make_state((), [("human", "start", None), ("ai", "完成", None)])
    mgr = ExperimentManager(graph_factory=lambda **kw: _fake_factory([done]), storage=storage)
    res = await mgr.create({"target_ip": "10.99.80.160"})
    row = await mgr.join(res["run_id"], timeout=10)
    assert row["status"] == "completed" and row["summary"]["stop_reason"] == "completed"
    events = storage.list_events(res["run_id"])
    assert [e["kind"] for e in events] == ["status", "ai_message", "status"]
@pytest.mark.asyncio
async def test_hitl_flow_and_attack_row(tmp_path, monkeypatch):
    # 状态序列：paused(HITL interrupt, ai 带 traffic_send tool_call) → resumed → done(tool 结果)
    # approve_soon() 0.1s 后 mgr.approve(rid, True)；断言 storage.list_attacks(rid) 长度 1、
    # attacks[0]["hitl"]["approved"] is True、events 含 kind=="hitl" 两条
@pytest.mark.asyncio
async def test_stop_marks_stopped(tmp_path, monkeypatch):
    # paused 状态 + 不 approve；0.2s 后 mgr.stop(rid)；join 返回 status=="stopped"
@pytest.mark.asyncio
async def test_reconnect_gets_pending_hitl(tmp_path, monkeypatch):
    # 运行至 paused 后不 approve：await mgr.pending_hitl(rid) 返回 payload；
    # 新 FakeWS subscribe(rid, ws) 返回 "observer"，manager 主动向该 ws send hitl_request
```

- [ ] **Step 2: 运行确认失败**（旧 `ExperimentManager` 无 `create/join`）

- [ ] **Step 3: 实现 v2**（`_msg_to_dict` 保留但升级：补 `reasoning_content` 与 `summary`；`_extract_hitl` 逻辑照旧；`build_graph` 建图从 `__init__` 移入 `_run`）

- [ ] **Step 4: 重写 `tests/integration/test_web_experiment.py`**：删除对 `_run_loop`/`manager._graph` 内部结构的直接依赖，改为覆盖 v2 公共 API（`create/join/approve/stop/subscribe/pending_hitl`）；保留 `test_extract_hitl_*` 与 `_msg_to_dict` 的既有断言（升级后仍成立）。

- [ ] **Step 5: 运行确认全绿**：`.venv/bin/python -m pytest tests/integration/test_web_experiment.py tests/integration/test_experiment_manager.py -v` → **Step 6: Commit**（`feat: rewrite ExperimentManager as per-run async tasks with event persistence and HITL recovery`）

---

### Task 11: FIFO 队列、探针后台聚合、pending 恢复推送

**Files:**
- Modify: `backend/experiment.py`
- Test: `tests/integration/test_experiment_manager.py`（追加用例）

**Interfaces:**
- Consumes: T10 全部；`src.tools.ping_monitor.get_ping_monitor`
- Produces（T12 依赖）: `ExperimentManager._start_next_queued()`（内部）、`probe_interval_s` 构造参数

- [ ] **Step 1: 写失败测试**：

```python
@pytest.mark.asyncio
async def test_queue_fifo_starts_next(tmp_path, monkeypatch):
    # 3 个实验：A 用"阻塞型" fake factory（invoke 等待 releaseA Event），B/C 用立即完成型
    # resA = create → running；resB/resC = create → queued（断言 storage 状态）
    # releaseA.set() → join(A) completed → join(B) completed → join(C) completed
    # 断言 B、C 的 started_at 非空且按 A→B→C 顺序
@pytest.mark.asyncio
async def test_probe_loop_writes_aggregated_points(tmp_path, monkeypatch):
    # 假 monitor：get_stats(window_s=1.0) 返回 {"monitor_active": True, "sent_count":10,
    #   "received_count":9, "avg_rtt_ms":5.0, "loss_pct":10.0}；monkeypatch src.tools.ping_monitor.get_ping_monitor
    # manager = ExperimentManager(probe_interval_s=0.05, ...)
    # 运行 0.3s 的慢 fake 实验；join 后断言 len(storage.list_probes(rid)) >= 2 且首条 received==9
```

- [ ] **Step 2: 运行确认失败** → **Step 3: 实现**：`_run` 收尾块末尾调用 `_start_next_queued()`（取 `storage.next_queued()` 非空则 `asyncio.create_task(self._run(rid))`，跳过软删除/已中断）；`_run` 开始时启动 `asyncio.create_task(self._probe_loop(rid))`，结束时 cancel；`_probe_loop` 每秒（构造参数）`get_stats(window_s=1.0)`，`monitor_active` 为真才 `append_probe` + broadcast `probe`；subscribe 时若 `self.running_run_id == run_id` 且 `await self.pending_hitl(run_id)` 非空，立即向新连接 send `hitl_request`（Review Focus #5）→ **Step 4: 全绿** → **Step 5: Commit**（`feat: add FIFO queue, probe aggregation loop and hitl re-push on reconnect`）

---

### Task 12: `backend/server.py` — REST + WS 路由 + lifespan

**Files:**
- Rewrite: `backend/server.py`
- Test: `tests/integration/test_api.py`（新建）

**Interfaces:**
- Consumes: T10/T11 的 `ExperimentManager`；T5 的 `schemas`
- Produces:

```python
def create_app(storage: Storage | None = None, manager: ExperimentManager | None = None) -> FastAPI
    # 缺省用 Storage(env ATTACK_TEST_DB) 与 ExperimentManager()；模块级 app = create_app()（uvicorn 入口不变）
```

端点与错误契约照 spec §8.1（`GET/POST /api/experiments`、`GET /api/experiments/{id}`、`GET /api/experiments/{id}/events?after_seq&limit`、`POST .../stop`、`DELETE ...`、`GET /api/meta/options`、`POST /api/upload/pcap` ≤50MB）。lifespan startup 调 `manager.storage.mark_stale_as_interrupted()`。`CreateValidationError` → 400 `{"error": field, "detail": message}`；软删除冲突 → 409；不存在 → 404。WS `/ws/{run_id}`：接受后 `role = manager.subscribe(run_id, ws)`，回 `{"type":"status","data":{"status":"connected","run_id":run_id,"role":role}}`；上行 `hitl_response`/`stop_experiment` 仅 role=="operator" 受理，否则回 `{"type":"error","data":{"code":"not_operator","message":"旁观连接不可操作"}}`；断线 `unsubscribe`。创建时若 `config["pcap_path"]` 非空：拷贝到 `data/uploads/{run_id}/` 并改写 config 内路径（目录不存在则创建）。

- [ ] **Step 1: 写失败测试** `tests/integration/test_api.py`（`fastapi.testclient.TestClient` + tmp 存储 + fake factory manager）：

```python
def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    storage = Storage(tmp_path / "t.db")
    mgr = ExperimentManager(graph_factory=immediate_factory, storage=storage, probe_interval_s=0.05)
    return TestClient(create_app(storage=storage, manager=mgr))

def test_create_and_list_and_detail(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/experiments", json={"target_ip": "10.99.80.160"})
    assert r.status_code == 200 and r.json()["status"] in ("running", "queued")
    rid = r.json()["run_id"]
    assert c.get("/api/experiments")["items"][0]["id"] == rid
    assert c.get(f"/api/experiments/{rid}").json()["status"] == "running"

def test_create_validation_errors(tmp_path, monkeypatch):
    # 非法 IP → 400 且 error 字段 == "target_ip"；pps 超限 → 400

def test_soft_delete_flow(tmp_path, monkeypatch):
    # completed 实验 DELETE → 200；列表为空；queued 实验 DELETE → 409

def test_events_incremental(tmp_path, monkeypatch):
    # 完成实验后 GET /api/experiments/{rid}/events?after_seq=2 只含 seq>2

def test_meta_options(tmp_path, monkeypatch):
    # allowlist 含 "10.99.80.160"；tools 长 19；max_pcap_bytes == 50*1024*1024

def test_upload_pcap_too_large(tmp_path, monkeypatch):
    # files={"file": ("big.pcap", b"0"*(50*1024*1024+1))} → 400
```

- [ ] **Step 2: 运行确认失败** → **Step 3: 实现**（注意：`create` 是异步方法，路由处理函数用 `async def` 并 `await manager.create(...)`；事件由 manager 直接广播，REST 只做 CRUD）→ **Step 4: 全绿** → **Step 5: Commit**（`feat: add experiment REST API, WS operator/observer roles, startup stale cleanup`）

---

### Task 13: 全量回归

**Files:**
- Modify: 无（仅修回归）

- [ ] **Step 1: 跑全量测试**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 全部 PASS（`tests/integration/` 里依赖真实 Pktgen 的用例若环境不可达自动 skip 属正常）。

- [ ] **Step 2: 手动冒烟**（可选，有 fping/ping 环境时）：起服务 `UV_CACHE_DIR="$PWD/.uv-cache" uv run uvicorn backend.server:app --port 8000`，用 curl 走一遍 创建→列表→详情→停止→删除，确认 JSON 契约与 spec §8.1 一致。

- [ ] **Step 3: Commit**（若有回归修复）：`fix: regression fixes after backend core integration`

---

## 自审记录（写作时已核对）

1. **Spec 覆盖**：§7.1/7.2→T2/T3；§7.3→T11；§7.4/7.5/7.8→T4；§8.1→T5/T12；§8.2→T10/T12；§12 E4/E5/E6/E7/E8→T2/T5/T10/T11/T12（E1 的 API key 预检→T5；E2/E3 展示语义属 Plan 2）；FR-2/7/8 后端部分→T5/T11/T12。§7.6（Pktgen 结构化统计）与 CLI 重构留 Plan 3，spec Non-goals 允许。
2. **步骤扫描**：每个 Step 均为单一动作（写测试/跑测试/实现签名/提交），实现步骤只给签名与锁定的行为约束，未代写函数体。
3. **类型一致**：`Storage`/`derive`/`ExperimentManager`/`create_app` 的签名在 T2–T12 的 Interfaces 块间交叉核对无漂移；env 键名 T6 定义、T7/T8 消费一致；`attacks.hitl` 的 approved 通过 `_pending_approval` 在 T10 落库时补写，无跨表回填接口。
4. **Review Focus**：5 条各对应 T4/T2/T2/T7-T8/T3+T10 的显式测试（已在对应 Task 中给出）。
5. **比例**：本计划 13 任务；代码块仅为测试断言与签名，未转录实现。

## Execution Handoff

计划已保存至 `docs/superpowers/plans/2026-11-18-attack-console-backend.md`。请评审：**是否准确捕捉了你的意图？** 并选择执行方式：

- **Subagent-driven**：每个任务由全新 subagent 按计划实现、由全新 reviewer 验收后再进入下一个任务，最后全分支终审。最彻底；每个任务/评审消耗独立上下文。
- **Native**：由我在本会话按任务逐个实现（TDD + 逐步提交），最后用最强模型做一次全分支评审。最快最省；终审前无独立评审。

**本计划我推荐 Subagent-driven**：13 个任务之间有严格的接口链（Storage → derive → Manager → server），且本仓库涉及安全门控（allowlist/HITL/上限），逐任务独立评审能尽早拦住安全回归。你确认后我就开始。
