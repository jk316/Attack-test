# TRex 目的 MAC 支持 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 TRex 侧补上已知 L2 事实注入（网关 dst MAC / 端口 src MAC / force 启动）与 `trex_common.py` 公共模块，让 agent 不再困于「目的 MAC 该填什么」。

**Architecture:** 沿用现有配置链 `experiment.json` → `main.py` 注入 env → `src/trex/config.py` getter（env → topology.yaml trex 段 → 默认值）→ `graph.py` 渲染进两个 Jinja2 提示词；helper 提交进 `trex_scripts/trex_common.py`（纯 stdlib、trex 库延迟 import），生成脚本与被运行脚本同目录可直接 `import trex_common`。

**Tech Stack:** Python 3.11+ / pytest / Jinja2 / LangChain。

**Spec:** `docs/superpowers/specs/2026-11-24-trex-dst-mac-design.md`

## Global Constraints

- 配置取值链顺序不变：env → topology.yaml `trex` 段 → 代码默认值；默认值 dst_mac=`f4:e9:75:ee:51:69`，src_mac=`58:a2:e1:6d:89:2c`，start_force=`true`。
- `trex_scripts/trex_common.py` 模块顶层**只允许 stdlib**，`trex_stl_lib`/`trex_astf_lib` 只在函数内延迟 import（agent 测试环境无 trex 库）。
- 提示词模板与 helper 中**不得出现非 allowlist 的 IP 字面量**（尤其网关 IP `100.1.13.1`）；只引用 MAC。
- 不新增 CLI 参数；`main.py` 只做 cfg→env 注入。
- 单元测试必须 hermetic：mock 全部 I/O，无网络、无子进程副作用；测试文件放 `tests/unit/`。

## Review Focus

1. 生成脚本 `from trex_common import ...` 在 catalog dry-run 下必须 `syntax_ok=true`（compile 不解析 import，不应被工具拦截）→ 测试落在 Task 2（`test_trex_tools.py::test_script_importing_trex_common_is_syntax_ok`）。
2. 渲染出的提示词绝不能含网关 IP `100.1.13.1` 字面量（否则 agent 会抄进脚本注释被静态扫描拦）→ 测试落在 Task 3（`test_catalog_prompt_hides_gateway_ip_literal`）。
3. `start_force` 的假值解析（`false/0/no/空` → False）→ Task 1 参数化测试。
4. helper 在无 trex 库的环境可 import（顶层无 trex 依赖）→ Task 2 首个测试即证明。
5. agent 无法用 `write_python_file` 覆盖 `trex_common.py` → Task 2 保留名测试。

---

### Task 1: TRex L2 配置 getter

**Files:**
- Modify: `src/trex/config.py`（`_load_trex_section` 之后追加 3 个 getter）
- Modify: `topology.yaml`（`trex` 段加 `dst_mac`/`src_mac`/`start_force`）
- Modify: `experiment.json`（`trex` 段加同 3 键，与 topology 同值）
- Test: Create `tests/unit/test_trex_config.py`

**Interfaces:**
- Consumes: 无（本计划第一任务）。
- Produces:
  - `get_trex_dst_mac() -> str` — env `TREX_DST_MAC` → `_load_trex_section()["dst_mac"]` → `"f4:e9:75:ee:51:69"`
  - `get_trex_src_mac() -> str` — env `TREX_SRC_MAC` → topology → `"58:a2:e1:6d:89:2c"`
  - `get_trex_start_force() -> bool` — env `TREX_START_FORCE` → topology → `True`；字符串假值集合 `{"false","0","no",""}`（大小写不敏感）判 False

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_trex_config.py`

```python
"""Unit tests for TRex L2 getters (dst/src MAC, start_force)."""
import pytest

from src.trex import config as trex_config


def _patch_section(monkeypatch, section):
    monkeypatch.setattr(trex_config, "_load_trex_section", lambda: section)


class TestL2Getters:
    def test_dst_mac_env_wins(self, monkeypatch):
        _patch_section(monkeypatch, {"dst_mac": "aa:bb:cc:dd:ee:ff"})
        monkeypatch.setenv("TREX_DST_MAC", "ff:ff:ff:ff:ff:ff")
        assert trex_config.get_trex_dst_mac() == "ff:ff:ff:ff:ff:ff"

    def test_dst_mac_topology_fallback(self, monkeypatch):
        monkeypatch.delenv("TREX_DST_MAC", raising=False)
        _patch_section(monkeypatch, {"dst_mac": "aa:bb:cc:dd:ee:ff"})
        assert trex_config.get_trex_dst_mac() == "aa:bb:cc:dd:ee:ff"

    def test_dst_mac_default(self, monkeypatch):
        monkeypatch.delenv("TREX_DST_MAC", raising=False)
        _patch_section(monkeypatch, {})
        assert trex_config.get_trex_dst_mac() == "f4:e9:75:ee:51:69"

    def test_src_mac_env_and_default(self, monkeypatch):
        monkeypatch.delenv("TREX_SRC_MAC", raising=False)
        _patch_section(monkeypatch, {})
        assert trex_config.get_trex_src_mac() == "58:a2:e1:6d:89:2c"
        monkeypatch.setenv("TREX_SRC_MAC", "00:11:22:33:44:55")
        assert trex_config.get_trex_src_mac() == "00:11:22:33:44:55"

    def test_start_force_default_true(self, monkeypatch):
        monkeypatch.delenv("TREX_START_FORCE", raising=False)
        _patch_section(monkeypatch, {})
        assert trex_config.get_trex_start_force() is True

    @pytest.mark.parametrize("value", ["false", "0", "no", "FALSE", ""])
    def test_start_force_falsy_values(self, monkeypatch, value):
        monkeypatch.setenv("TREX_START_FORCE", value)
        assert trex_config.get_trex_start_force() is False

    def test_start_force_from_topology(self, monkeypatch):
        monkeypatch.delenv("TREX_START_FORCE", raising=False)
        _patch_section(monkeypatch, {"start_force": False})
        assert trex_config.get_trex_start_force() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_trex_config.py -v`
Expected: FAIL — 3 个 getter `AttributeError: module 'src.trex.config' has no attribute 'get_trex_dst_mac'`

- [ ] **Step 3: Implement the 3 getters in `src/trex/config.py`**

在 `get_trex_timeout_s` 之后追加；每个 getter 内部 `os.environ.get("TREX_DST_MAC") or _load_trex_section().get("dst_mac") or 默认值`。`get_trex_start_force`：取值后 `str(value).strip().lower() not in {"false", "0", "no", ""}`。默认值按 Global Constraints 中的字面值。

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_trex_config.py -v`
Expected: PASS（7 项全过）

- [ ] **Step 5: 更新 topology.yaml 与 experiment.json**

`topology.yaml` 的 `trex:` 段加三行 `dst_mac: "f4:e9:75:ee:51:69"`、`src_mac: "58:a2:e1:6d:89:2c"`、`start_force: true`（带注释「TRex 端口 0 的网关下一跳 MAC / 端口 MAC / 启动是否 force 绕过 dest-MAC 校验」）；`experiment.json` 的 `"trex": {...}` 加 `"dst_mac"`/`"src_mac"`/`"start_force"` 同值。

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_trex_config.py src/trex/config.py topology.yaml experiment.json
git commit -m "feat(trex): add dst/src MAC + start_force config getters for TRex L2 facts"
```

---

### Task 2: trex_common.py 公共模块 + 保留名保护

**Files:**
- Create: `trex_scripts/trex_common.py`
- Modify: `.gitignore`（在 `trex_scripts/` 行后加 `!trex_scripts/trex_common.py`）
- Modify: `src/trex/tools.py`（`_resolve_script_path` 加保留名校验）
- Test: Create `tests/unit/test_trex_common.py`；Modify `tests/unit/test_trex_tools.py`

**Interfaces:**
- Consumes: 无（独立模块）。
- Produces（`trex_common` 模块，被 Task 3 的提示词模板引用）:
  - `DST_MAC: str`、`SRC_MAC: str`、`TREX_SERVER: str`、`START_FORCE: bool` — 模块 import 时读 env（`TREX_DST_MAC`/`TREX_SRC_MAC`/`TREX_HOST`/`TREX_START_FORCE`），缺省用 Task 1 的默认值；`TREX_SERVER` 缺省 `"10.99.80.222"`
  - `make_client(server: str | None = None)` — 函数内 `from trex_stl_lib.api import STLClient`，`STLClient(server or TREX_SERVER).connect()`，返回已连接 client
  - `start_safe(client, ports=None, mult="100%", duration=10)` — `client.start(ports=ports or [0], mult=mult, duration=duration, force=True)`

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_trex_common.py`

```python
"""Unit tests for trex_scripts/trex_common.py.

Importing the module in this (trex-less) environment is itself the first test:
top level must not import trex_stl_lib / trex_astf_lib.
"""
import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "trex_scripts"


def _fresh_module(monkeypatch):
    for key in ("TREX_DST_MAC", "TREX_SRC_MAC", "TREX_START_FORCE", "TREX_HOST"):
        monkeypatch.delenv(key, raising=False)
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    mod = importlib.import_module("trex_common")
    importlib.reload(mod)
    return mod


@pytest.fixture()
def trex_common(monkeypatch):
    return _fresh_module(monkeypatch)


class TestConstants:
    def test_module_imports_without_trex_libs(self, trex_common):
        assert trex_common.DST_MAC == "f4:e9:75:ee:51:69"
        assert trex_common.SRC_MAC == "58:a2:e1:6d:89:2c"
        assert trex_common.TREX_SERVER == "10.99.80.222"
        assert trex_common.START_FORCE is True

    def test_env_overrides(self, monkeypatch):
        # 注意：先设 env 再 reload（不能用 _fresh_module，它会先清 env）。
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        monkeypatch.setenv("TREX_DST_MAC", "aa:bb:cc:dd:ee:ff")
        monkeypatch.setenv("TREX_SRC_MAC", "11:22:33:44:55:66")
        monkeypatch.setenv("TREX_START_FORCE", "false")
        mod = importlib.import_module("trex_common")
        importlib.reload(mod)
        assert mod.DST_MAC == "aa:bb:cc:dd:ee:ff"
        assert mod.SRC_MAC == "11:22:33:44:55:66"
        assert mod.START_FORCE is False


class _FakeClient:
    def __init__(self):
        self.start_kwargs = None

    def start(self, **kwargs):
        self.start_kwargs = kwargs


class TestStartSafe:
    def test_start_safe_passes_force_true(self, trex_common):
        client = _FakeClient()
        trex_common.start_safe(client, ports=[0], mult="50%", duration=5)
        assert client.start_kwargs == {
            "ports": [0], "mult": "50%", "duration": 5, "force": True,
        }

    def test_start_safe_defaults(self, trex_common):
        client = _FakeClient()
        trex_common.start_safe(client)
        assert client.start_kwargs["force"] is True
        assert client.start_kwargs["ports"] == [0]
        assert client.start_kwargs["mult"] == "100%"
        assert client.start_kwargs["duration"] == 10


class TestMakeClient:
    def test_make_client_connects_with_server(self, trex_common, monkeypatch):
        class FakeSTLClient:
            def __init__(self, server):
                self.server = server
                self.connected = False

            def connect(self):
                self.connected = True

        monkeypatch.setitem(sys.modules, "trex_stl_lib.api",
                            type("fake_api", (), {"STLClient": FakeSTLClient})())
        client = trex_common.make_client(server="10.99.80.222")
        assert client.server == "10.99.80.222"
        assert client.connected is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_trex_common.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'trex_common'`

- [ ] **Step 3: Implement `trex_scripts/trex_common.py`**

模块 docstring 写清三点：与生成脚本同目录可直接 `from trex_common import ...`；目标在网关后、必须 `Ether(dst=DST_MAC, src=SRC_MAC)` 且不能依赖 TRex 自动 ARP；`start_safe` 用 `force=True` 绕过 "Port 0 dest MAC is invalid ..." 校验；**注释里不写任何 IP 字面量**。常量与函数签名见 Interfaces，`START_FORCE` 假值解析与 Task 1 相同。

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_trex_common.py -v`
Expected: PASS

- [ ] **Step 5: Write the reserved-name guard tests** — `tests/unit/test_trex_tools.py` 追加

```python
class TestReservedHelperName:
    def test_write_python_file_rejects_trex_common(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.trex.tools.get_trex_scripts_dir", lambda: tmp_path)
        result = write_python_file.invoke(
            {"filename": "trex_common.py", "code": "x = 1\n"}
        )
        assert result["success"] is False
        assert "reserved" in result["error"]

    def test_script_importing_trex_common_is_syntax_ok(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.trex.tools.get_trex_scripts_dir", lambda: tmp_path)
        result = write_python_file.invoke(
            {"filename": "cat_x.py",
             "code": "from trex_common import DST_MAC, SRC_MAC, start_safe\n"}
        )
        assert result["success"] is True
        assert result["syntax_ok"] is True
```

- [ ] **Step 6: Run to verify the guard test fails**

Run: `uv run pytest tests/unit/test_trex_tools.py::TestReservedHelperName -v`
Expected: FAIL — `assert result["success"] is False`（`trex_common.py` 仍可写；`test_script_importing_trex_common_is_syntax_ok` 反而通过，属预期）

- [ ] **Step 7: Implement the guard in `src/trex/tools.py`**

`_resolve_script_path` 中裸名校验通过后、返回前：`if filename == "trex_common.py": raise ValueError("trex_common.py 是保留的公共辅助模块（不可覆盖/直接执行）；请在脚本中 import trex_common")`。该函数同时被 `write_python_file` 与 `run_python_file` 使用，一处即可拦两个入口。

- [ ] **Step 8: Run to verify pass**

Run: `uv run pytest tests/unit/test_trex_tools.py::TestReservedHelperName -v`
Expected: PASS（2 项）

- [ ] **Step 9: 更新 .gitignore**

`trex_scripts/` 行后追加 `!trex_scripts/trex_common.py`（保留 helper 入库）。

- [ ] **Step 10: 全量单测**

Run: `uv run pytest tests/unit/ -v`
Expected: 全部 PASS（含新增文件）

- [ ] **Step 11: Commit**

```bash
git add trex_scripts/trex_common.py .gitignore src/trex/tools.py \
        tests/unit/test_trex_common.py tests/unit/test_trex_tools.py
git commit -m "feat(trex): add trex_common helper (DST_MAC/SRC_MAC/start_safe) and reserve its name"
```

---

### Task 3: 提示词注入 L2 事实（graph.py + 两个 j2 模板）

**Files:**
- Modify: `src/agent/graph.py`（`_build_system_prompt` 的 render kwargs 加 3 项）
- Modify: `src/prompts/system_prompt.j2`（TRex 块加「已知 L2 拓扑与目的 MAC」小节，脚本模板改引 trex_common）
- Modify: `src/prompts/trex_catalog_prompt.j2`（脚本模板后加同类小节）
- Test: Modify `tests/unit/test_trex_catalog_mode.py`（`TestCatalogPrompt` 追加 4 项）

**Interfaces:**
- Consumes: Task 1 的 `get_trex_dst_mac` / `get_trex_src_mac` / `get_trex_start_force`；Task 2 的 `trex_common` 模块名。
- Produces: 渲染后的 `system_prompt`（catalog 与 experiment 两模式）含 `trex_dst_mac`、`trex_src_mac`、`trex_common`、`start_safe`、`force=True`、`网关`；不含 `100.1.13.1`。

- [ ] **Step 1: Write the failing tests** — `TestCatalogPrompt` 追加

```python
    def test_catalog_prompt_contains_l2_mac_facts(self, monkeypatch):
        monkeypatch.setenv("TREX_DST_MAC", "aa:bb:cc:dd:ee:ff")
        monkeypatch.setenv("TREX_SRC_MAC", "11:22:33:44:55:66")
        prompt = _build_system_prompt(mode="catalog")
        assert "aa:bb:cc:dd:ee:ff" in prompt
        assert "11:22:33:44:55:66" in prompt
        assert "trex_common" in prompt
        assert "start_safe" in prompt
        assert "force=True" in prompt
        assert "网关" in prompt

    def test_catalog_prompt_hides_gateway_ip_literal(self, monkeypatch):
        prompt = _build_system_prompt(mode="catalog")
        assert "100.1.13.1" not in prompt

    def test_experiment_prompt_contains_l2_mac_facts(self, monkeypatch):
        monkeypatch.setattr("src.agent.graph._trex_available", lambda: True)
        monkeypatch.setenv("TREX_DST_MAC", "aa:bb:cc:dd:ee:ff")
        prompt = _build_system_prompt(mode="experiment")
        assert "aa:bb:cc:dd:ee:ff" in prompt
        assert "trex_common" in prompt
        assert "start_safe" in prompt

    def test_experiment_prompt_hides_gateway_ip_literal(self, monkeypatch):
        monkeypatch.setattr("src.agent.graph._trex_available", lambda: True)
        prompt = _build_system_prompt(mode="experiment")
        assert "100.1.13.1" not in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_trex_catalog_mode.py::TestCatalogPrompt -v`
Expected: FAIL — 4 项新断言不满足（无 `trex_common`/MAC 内容）

- [ ] **Step 3: 修改 `src/agent/graph.py` render kwargs**

`template.render(...)` 参数追加：`trex_dst_mac=get_trex_dst_mac()`、`trex_src_mac=get_trex_src_mac()`、`trex_start_force=get_trex_start_force()`；顶部 import 补这三个 getter。

- [ ] **Step 4: 修改两个 j2 模板**

`system_prompt.j2` 的「### 脚本模板示例」前插入「### 已知 L2 拓扑与目的 MAC（必读）」小节：说明目标在网关后、ARP 解析目标必失败、必须 `Ether(dst="{{ trex_dst_mac }}", src="{{ trex_src_mac }}")`（禁止广播 MAC 与自动 ARP 依赖）、裸 `c.start` 会报 `Port 0 dest MAC is invalid ...` 故用 `trex_scripts/trex_common.py` 的 `start_safe()`（内置 `force=True`，当前配置 start_force={{ '已开启' if trex_start_force else '已关闭' }}），给出 `from trex_common import DST_MAC, SRC_MAC, start_safe, make_client` 的完整小模板；末条警告：**严禁把非 allowlist 的 IP（网关 IP 等）写进脚本注释/字符串**，只引用 MAC。`trex_catalog_prompt.j2` 的脚本模板块后加同类小节（措辞强调「脚本面向未来真实执行」；catalog 脚本同样 `from trex_common import ...`）。

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_trex_catalog_mode.py -v`
Expected: PASS（全部，含既有测试）

- [ ] **Step 6: Commit**

```bash
git add src/agent/graph.py src/prompts/system_prompt.j2 src/prompts/trex_catalog_prompt.j2 \
        tests/unit/test_trex_catalog_mode.py
git commit -m "feat(prompts): inject TRex L2 facts (gateway dst MAC, port src MAC, start_safe) into prompts"
```

---

### Task 4: main.py env 注入 + CLAUDE.md 文档

**Files:**
- Modify: `src/main.py`（新增 `_apply_trex_l2_env`，在 TRex 配置段调用）
- Modify: `CLAUDE.md`（Key Files 表 trex 行与「Configuration Flow」补注）
- Test: Modify `tests/unit/test_trex_catalog_mode.py`（新增 `TestTrexL2Env`）

**Interfaces:**
- Consumes: 无。
- Produces: `_apply_trex_l2_env(trex_cfg: dict) -> None` — 对 `dst_mac`/`src_mac`/`start_force` 三个键，仅当 cfg 中值不为 None 时 `os.environ[f"TREX_{key.upper()}"] = str(value)`；调用点在 `os.environ["TREX_TIMEOUT_S"] = ...` 之后。

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_trex_catalog_mode.py` 追加

```python
class TestTrexL2Env:
    def test_apply_trex_l2_env_sets_all(self, monkeypatch):
        import os

        from src.main import _apply_trex_l2_env

        for k in ("TREX_DST_MAC", "TREX_SRC_MAC", "TREX_START_FORCE"):
            monkeypatch.delenv(k, raising=False)
        _apply_trex_l2_env({"dst_mac": "aa:bb:cc:dd:ee:ff",
                            "src_mac": "11:22:33:44:55:66",
                            "start_force": False})
        assert os.environ["TREX_DST_MAC"] == "aa:bb:cc:dd:ee:ff"
        assert os.environ["TREX_SRC_MAC"] == "11:22:33:44:55:66"
        assert os.environ["TREX_START_FORCE"] == "False"

    def test_apply_trex_l2_env_missing_keys_noop(self, monkeypatch):
        import os

        from src.main import _apply_trex_l2_env

        for k in ("TREX_DST_MAC", "TREX_SRC_MAC", "TREX_START_FORCE"):
            monkeypatch.delenv(k, raising=False)
        _apply_trex_l2_env({})
        assert "TREX_DST_MAC" not in os.environ
        assert "TREX_SRC_MAC" not in os.environ
        assert "TREX_START_FORCE" not in os.environ
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_trex_catalog_mode.py::TestTrexL2Env -v`
Expected: FAIL — `ImportError: cannot import name '_apply_trex_l2_env'`

- [ ] **Step 3: Implement `_apply_trex_l2_env` in `src/main.py`**

按 Interfaces 的签名实现；在 main() 中 `os.environ["TREX_TIMEOUT_S"] = str(args.trex_timeout)` 后追加 `_apply_trex_l2_env(trex_cfg)`（`trex_cfg` 已在 main 内定义）。

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_trex_catalog_mode.py::TestTrexL2Env -v`
Expected: PASS（2 项）

- [ ] **Step 5: 更新 CLAUDE.md**

Key Files 表中 `src/trex/config.py` 行追加 `get_trex_dst_mac/get_trex_src_mac/get_trex_start_force`；「Configuration Flow」或 TRex 相关段落补一句：`trex_scripts/trex_common.py` 为生成脚本的公共 L2 辅助模块（DST_MAC/SRC_MAC/start_safe，保留名不可覆盖），提示词已注入网关 dst MAC 事实。

- [ ] **Step 6: 全量单测 + 提交**

Run: `uv run pytest tests/unit/ -v`
Expected: 全部 PASS

```bash
git add src/main.py CLAUDE.md tests/unit/test_trex_catalog_mode.py
git commit -m "feat(main): plumb trex L2 facts from experiment.json into env; document helper"
```

---

## 完成判据

- `uv run pytest tests/unit/ -v` 全绿；`git status` 无遗漏未提交的相关文件。
- 渲染出的两个提示词包含网关 dst MAC / 端口 src MAC / `trex_common` 用法，且不含网关 IP 字面量。
- `trex_scripts/trex_common.py` 被 git 跟踪（.gitignore 例外生效），且 `write_python_file`/`run_python_file` 拒绝 `trex_common.py`。
